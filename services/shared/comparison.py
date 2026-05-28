"""Comparison Engine (3rd PoC).

Pure-Python, deterministic. Given an IntentMandate and a list of product
dicts (as returned by `services.merchant.catalog.search`), produces a
ComparisonReport with per-candidate normalized scores and an engine-picked
winner.

Why pure Python (no LLM):
  - The agent's job is to read this table and decide; it must not be asked
    to invent numbers it cannot observe.
  - The output is reproducible across runs, which lets us assert behaviour
    in smoke tests (same input → same winner).

Dimensions:
  - price       : lower is better; missing prices fail the candidate.
  - rating      : higher is better; absent → dimension dropped for that
                  candidate, never imputed.
  - reputation  : static_demo_registry per merchant. Always present.
  - shipping    : static days_eta per merchant. Always present.

The agent may still override the engine's pick (see AgentDecisionTrace).
Surfacing the divergence in the UI is the point.
"""

from __future__ import annotations

from typing import Any

from services.shared.mandates import (
    PRIORITY_PRESETS,
    AgentDecisionTrace,
    CandidateScore,
    ComparisonReport,
    IntentMandate,
    PriorityWeights,
    TradeoffRow,
)
from services.shared.stub_sig import stub_sign
from services.shared.reputation import (
    SOURCE_TAG,
    is_registered,
    reputation_score,
    shipping_days,
    shipping_note,
)

# Hard caps for normalization that don't depend on the candidate set.
# Ratings are 0..5 on the SerpAPI side. Shipping ETA worst-case ~14 days.
_MAX_RATING = 5.0
_MAX_SHIPPING_DAYS_FOR_NORM = 14.0


def _resolve_weights(intent: IntentMandate) -> PriorityWeights:
    """Pick the weights vector the engine should use.

    Priority order: explicit weights on the intent → preset on the intent →
    default `cheapest` (PoC2-compatible: price-only).
    """
    if intent.priority is not None:
        return intent.priority
    if intent.priority_preset is not None:
        return PRIORITY_PRESETS[intent.priority_preset].model_copy()
    return PRIORITY_PRESETS["cheapest"].model_copy()


def _norm_price(price_cents: int, lo: int, hi: int) -> float:
    """Lower price → higher score. Linear within the candidate-set range."""
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (price_cents - lo) / (hi - lo)))


def _norm_rating(rating: float | None) -> float | None:
    if rating is None:
        return None
    return max(0.0, min(1.0, float(rating) / _MAX_RATING))


def _norm_reputation(score: int) -> float:
    return max(0.0, min(1.0, score / 100.0))


def _norm_shipping(days: int) -> float:
    return max(0.0, min(1.0, 1.0 - (days / _MAX_SHIPPING_DAYS_FOR_NORM)))


def _build_pros_cons(
    cand_idx: int,
    candidates_raw: list[dict[str, Any]],
    normalized_per_dim: dict[str, list[float | None]],
) -> tuple[list[str], list[str]]:
    """Auto-derive 'lowest price' / 'highest rating' style flags."""
    pros: list[str] = []
    cons: list[str] = []
    for dim, vals in normalized_per_dim.items():
        present = [(i, v) for i, v in enumerate(vals) if v is not None]
        if not present:
            continue
        # winner_idx by max
        max_i, max_v = max(present, key=lambda iv: iv[1])
        min_i, min_v = min(present, key=lambda iv: iv[1])
        my_v = vals[cand_idx]
        if my_v is None:
            continue
        if cand_idx == max_i and len(present) > 1 and max_v > min_v:
            pros.append(f"best {dim}")
        if cand_idx == min_i and len(present) > 1 and max_v > min_v:
            cons.append(f"worst {dim}")
    return pros, cons


def build_comparison(
    intent: IntentMandate,
    products: list[dict[str, Any]],
    top_n: int = 5,
) -> ComparisonReport | None:
    """Build a ComparisonReport from search results.

    Returns None if `products` is empty (caller should skip the comparison
    step and stay on PoC2 behaviour).
    """
    if not products:
        return None

    weights = _resolve_weights(intent)

    # Take the top_n by price ascending as the candidate set. We intentionally
    # don't pre-filter by rating/reputation because the engine should expose
    # those tradeoffs, not hide them.
    candidates_raw = sorted(products, key=lambda p: p["price_cents"])[:top_n]

    prices = [p["price_cents"] for p in candidates_raw]
    lo, hi = min(prices), max(prices)

    # Per-dimension normalized arrays for pros/cons derivation.
    per_dim: dict[str, list[float | None]] = {
        "price": [_norm_price(p, lo, hi) for p in prices],
        "rating": [_norm_rating(p.get("rating")) for p in candidates_raw],
        "reputation": [_norm_reputation(reputation_score(p.get("source_merchant") or "")) for p in candidates_raw],
        "shipping": [_norm_shipping(shipping_days(p.get("source_merchant") or "")) for p in candidates_raw],
    }

    dropped_dimensions_some: set[str] = set()
    candidates: list[CandidateScore] = []
    weighted_scores: list[float] = []

    for i, raw in enumerate(candidates_raw):
        merchant = raw.get("source_merchant") or "unknown"
        normalized: dict[str, float] = {}
        # Build the weighted score, re-normalizing across dims that are
        # actually present for *this* candidate (so absent rating doesn't
        # unfairly penalize it).
        active_dims: list[tuple[str, float, float]] = []  # (dim, norm, weight)
        for dim, weight in [
            ("price", weights.price),
            ("rating", weights.rating),
            ("reputation", weights.trust),
            ("shipping", weights.shipping),
        ]:
            n = per_dim[dim][i]
            if n is None:
                dropped_dimensions_some.add(dim)
                continue
            normalized[dim] = round(n, 4)
            active_dims.append((dim, n, weight))

        total_w = sum(w for _, _, w in active_dims)
        if total_w <= 0:
            score = 0.0
        else:
            score = sum(n * w for _, n, w in active_dims) / total_w
        weighted_scores.append(score)

        pros, cons = _build_pros_cons(i, candidates_raw, per_dim)

        candidates.append(
            CandidateScore(
                product_id=raw["id"],
                title=raw["title"],
                source_merchant=merchant,
                price_cents=raw["price_cents"],
                rating=(float(raw["rating"]) if raw.get("rating") is not None else None),
                reviews_count=(int(raw["reviews_count"]) if raw.get("reviews_count") is not None else None),
                reputation_score=reputation_score(merchant),
                shipping_note=shipping_note(merchant),
                normalized=normalized,
                weighted_score=round(score, 4),
                pros=pros,
                cons=cons,
            )
        )

    # Engine winner = highest weighted score, stable tiebreak on price.
    winner_idx = max(
        range(len(candidates)),
        key=lambda i: (weighted_scores[i], -candidates[i].price_cents),
    )
    winner = candidates[winner_idx]
    runner_ups = [c.product_id for j, c in enumerate(candidates) if j != winner_idx]

    # dimensions_used: source-tag the static fields so the UI can show them
    # as not-real-data.
    dimensions_used = [
        "price",
        f"rating(source=catalog;missing_for={sum(1 for c in candidates if c.rating is None)})",
        f"reputation(source={SOURCE_TAG})",
        f"shipping(source={SOURCE_TAG})",
    ]

    # If every candidate from a merchant outside the registry, mark it.
    for c in candidates:
        if not is_registered(c.source_merchant):
            dimensions_used.append(f"reputation_default_used:{c.source_merchant}")

    return ComparisonReport(
        intent_jti=intent.jti,
        candidates=candidates,
        engine_winner_id=winner.product_id,
        runner_ups=runner_ups,
        dimensions_used=dimensions_used,
    )


# ---------- Agent decision trace builder ----------


_PRESET_DESCRIPTIONS = {
    "cheapest": "the user asked for the cheapest viable option",
    "balanced": "the user asked for a balanced trade-off across price, trust, rating, and shipping",
    "trusted":  "the user asked for the most trusted merchant and best-reviewed item",
    "fastest":  "the user prioritized shipping speed",
}


def _describe_priority(intent: IntentMandate) -> str:
    if intent.priority_preset and intent.priority_preset in _PRESET_DESCRIPTIONS:
        return _PRESET_DESCRIPTIONS[intent.priority_preset]
    if intent.priority is not None:
        w = intent.priority
        return (
            f"weights price={w.price:.2f} trust={w.trust:.2f} "
            f"rating={w.rating:.2f} shipping={w.shipping:.2f}"
        )
    return "no priority specified — defaulted to cheapest"


def _dropped_dimensions(report: ComparisonReport) -> list[str]:
    """Names of dimensions the engine could not use for at least one candidate."""
    dropped: set[str] = set()
    for c in report.candidates:
        for dim in ("price", "rating", "reputation", "shipping"):
            if dim not in c.normalized:
                dropped.add(dim)
    return sorted(dropped)


def build_decision_trace(
    intent: IntentMandate,
    report: ComparisonReport,
    agent_winner_id: str,
    headline: str | None = None,
) -> AgentDecisionTrace:
    """Build a signed AgentDecisionTrace from the comparison report + the
    agent's chosen winner.

    `headline` may be supplied by the LLM; if None, we synthesize one. The
    winner_id must exist in the report.
    """
    by_id = {c.product_id: c for c in report.candidates}
    if agent_winner_id not in by_id:
        raise ValueError(f"agent_winner_id {agent_winner_id!r} not in comparison report")
    winner = by_id[agent_winner_id]
    engine_winner = by_id[report.engine_winner_id]

    if headline is None:
        if agent_winner_id == report.engine_winner_id:
            headline = (
                f"Picked {winner.title} ({winner.source_merchant}) — engine top pick "
                f"under preset '{intent.priority_preset or 'cheapest'}'."
            )
        else:
            headline = (
                f"Agent overrode engine: picked {winner.title} "
                f"({winner.source_merchant}) over engine top {engine_winner.title} "
                f"({engine_winner.source_merchant})."
            )

    tradeoffs: list[TradeoffRow] = []
    for c in report.candidates:
        is_winner = c.product_id == agent_winner_id
        tradeoffs.append(
            TradeoffRow(
                product_id=c.product_id,
                relative_strengths=c.pros,
                relative_weaknesses=c.cons,
                why_not_chosen=(
                    None
                    if is_winner
                    else f"score {c.weighted_score:.3f} vs winner {winner.weighted_score:.3f}"
                ),
            )
        )

    body_for_hash: dict[str, object] = {
        "intent_jti": intent.jti,
        "engine_winner_id": report.engine_winner_id,
        "agent_winner_id": agent_winner_id,
        "headline": headline,
        "tradeoffs": [t.model_dump() for t in tradeoffs],
        "priority_explanation": _describe_priority(intent),
        "dropped_dimensions": _dropped_dimensions(report),
    }
    sig = stub_sign("agent", body_for_hash)

    return AgentDecisionTrace(
        intent_jti=intent.jti,
        engine_winner_id=report.engine_winner_id,
        agent_winner_id=agent_winner_id,
        headline=headline,
        tradeoffs=tradeoffs,
        priority_explanation=_describe_priority(intent),
        dropped_dimensions=_dropped_dimensions(report),
        signature=sig,
    )
