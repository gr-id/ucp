"""Smoke test for the 3rd PoC.

Verifies:
  1. Intent with priority preset is built correctly and its payload_hash
     differs from the PoC2-style legacy intent (priority is signed in).
  2. Different presets produce different intent hashes.
  3. Comparison Engine (mock catalog) yields a valid ComparisonReport, with
     normalized scores in [0, 1] and a winner present in the candidate set.
  4. cheapest preset and trusted preset pick different winners against the
     tuned mock catalog (otherwise the demo can't visibly show the effect).
  5. AgentDecisionTrace round-trips through Pydantic and surfaces both
     concur and override cases.

Runs without the SDK agent — pure Python. SerpAPI not required.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Force mock catalog so this test does not depend on SerpAPI.
os.environ["UCP_CATALOG_MODE"] = "mock"

from services.merchant import catalog
from services.shared.comparison import build_comparison, build_decision_trace
from services.shared.intent import build_intent_from_form
from services.shared.mandates import AgentDecisionTrace, ComparisonReport


def section(title: str) -> None:
    print(f"\n=== {title} ===")


_BASE_FORM = {
    "item_query": "running",
    "price_from_cents": 0,
    "price_to_cents": 200_00,
    "allowed_merchants": ["walmart", "target", "wayfair", "etsy"],
    "valid_hours": 24,
    "auto_purchase": False,
}


def test_priority_hash_changes() -> None:
    section("Priority included in Intent signed-payload hash")
    legacy = build_intent_from_form(dict(_BASE_FORM))
    balanced = build_intent_from_form(dict(_BASE_FORM, priority_preset="balanced"))
    trusted = build_intent_from_form(dict(_BASE_FORM, priority_preset="trusted"))

    assert legacy.priority is None and legacy.priority_preset is None
    assert balanced.priority is not None
    assert legacy.signature.payload_hash != balanced.signature.payload_hash, \
        "adding a priority must change the signed payload hash"
    assert balanced.signature.payload_hash != trusted.signature.payload_hash, \
        "different presets must produce different hashes"
    print(f"  legacy   hash={legacy.signature.payload_hash}")
    print(f"  balanced hash={balanced.signature.payload_hash}")
    print(f"  trusted  hash={trusted.signature.payload_hash}")
    print("  ok")


def test_legacy_intent_backcompat() -> None:
    section("Legacy (PoC2) form still produces a valid intent")
    intent = build_intent_from_form(dict(_BASE_FORM))
    assert intent.signature.signer == "user"
    assert intent.expires_at > int(time.time())
    assert intent.priority is None
    assert intent.priority_preset is None
    print(f"  ok — priority absent, mandate jti={intent.jti}")


def test_comparison_engine_shape() -> None:
    section("Comparison Engine (mock catalog)")
    intent = build_intent_from_form(dict(_BASE_FORM, priority_preset="balanced"))
    prods = catalog.search(
        intent.item_query,
        intent.price_range.from_cents,
        intent.price_range.to_cents,
        intent.allowed_merchants,
    )
    assert len(prods) >= 2, "mock catalog should return >=2 candidates for 'running'"

    report = build_comparison(intent, prods, top_n=5)
    assert report is not None
    assert report.engine_winner_id in [c.product_id for c in report.candidates]
    for c in report.candidates:
        assert 0.0 <= c.weighted_score <= 1.0, c
        for dim, v in c.normalized.items():
            assert 0.0 <= v <= 1.0, (dim, v)
    print(f"  {len(report.candidates)} candidates scored, dimensions_used={report.dimensions_used}")
    print(f"  engine_winner={report.engine_winner_id}")
    print("  ok")


def test_priority_swap_changes_winner() -> None:
    section("Different presets pick different engine winners (demo visibility)")
    prods = catalog.search("running", 0, 200_00, ["walmart", "target", "wayfair", "etsy"])
    winners: dict[str, tuple[str, str]] = {}
    for preset in ("cheapest", "balanced", "trusted", "fastest"):
        intent = build_intent_from_form(dict(_BASE_FORM, priority_preset=preset))
        report = build_comparison(intent, prods, top_n=5)
        w = next(c for c in report.candidates if c.product_id == report.engine_winner_id)
        winners[preset] = (w.title, w.source_merchant)
        print(f"  {preset:>10} -> {w.source_merchant:>8}  {w.title}  score={w.weighted_score:.3f}")
    distinct = {v for v in winners.values()}
    assert len(distinct) >= 2, (
        f"the tuned mock catalog should produce >=2 distinct winners across presets; got {distinct}"
    )
    print(f"  distinct winners: {len(distinct)}")
    print("  ok")


def test_decision_trace_concur_and_override() -> None:
    section("AgentDecisionTrace — concur + override + Pydantic round-trip")
    intent = build_intent_from_form(dict(_BASE_FORM, priority_preset="trusted"))
    prods = catalog.search(
        intent.item_query,
        intent.price_range.from_cents,
        intent.price_range.to_cents,
        intent.allowed_merchants,
    )
    report = build_comparison(intent, prods, top_n=5)

    # Concur
    trace_concur = build_decision_trace(intent, report, report.engine_winner_id)
    assert trace_concur.agent_winner_id == trace_concur.engine_winner_id
    assert trace_concur.signature.signer == "agent"
    AgentDecisionTrace.model_validate(trace_concur.model_dump())
    ComparisonReport.model_validate(report.model_dump())

    # Override: pick a different candidate
    other = next(c.product_id for c in report.candidates if c.product_id != report.engine_winner_id)
    trace_override = build_decision_trace(intent, report, other)
    assert trace_override.agent_winner_id != trace_override.engine_winner_id
    assert "Override" in trace_override.headline or "overrode" in trace_override.headline
    print(f"  concur   hash={trace_concur.signature.payload_hash}")
    print(f"  override hash={trace_override.signature.payload_hash}")
    print("  ok")


def main() -> None:
    test_priority_hash_changes()
    test_legacy_intent_backcompat()
    test_comparison_engine_shape()
    test_priority_swap_changes_winner()
    test_decision_trace_concur_and_override()
    print("\nAll 3rd-PoC smoke tests passed.")


if __name__ == "__main__":
    main()
