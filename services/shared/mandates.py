"""Pydantic models for AP2 Mandates (2nd/3rd PoC — stub-signature variant).

Schema evolution from 1st PoC:
  - `IntentMandate` now uses structured fields (item_query, price_range,
    allowed_merchants, expires_at, auto_purchase) instead of free-text natural
    language + ad-hoc Constraints.
  - All Mandate types carry a `StubSignature` instead of being wrapped in a JWS
    string. The 1st PoC proved real ES256 JWS; this PoC focuses on data + UX.
  - `LineItem` gains `image_url`, `source_merchant`, `product_url` so the UI can
    show real product visuals when the catalog is backed by SerpAPI.

3rd PoC additions (multi-merchant comparison + agent negotiation):
  - `PriorityWeights` + `priority_preset` on `IntentMandate` — the user's
    weighting across price / trust / rating / shipping. Optional & backward
    compatible. Included in the Intent's signed payload hash so altering the
    priority alters the mandate (auditable).
  - `CandidateScore` / `ComparisonReport` — the merchant-side comparison engine
    output: per-candidate normalized scores + winner.
  - `TradeoffRow` / `AgentDecisionTrace` — the agent's signed rationale for why
    it picked one candidate over the others. `signer="agent"` so the audit log
    can show "the agent committed to this decision."
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> int:
    return int(time.time())


def _jti() -> str:
    return f"mnd_{uuid.uuid4().hex[:16]}"


# ---------- shared ----------


class StubSignature(BaseModel):
    """Placeholder for a real signature.

    The 2nd PoC assumes the signer (user or merchant) holds signing capability
    on an external device. We carry the signer identity, timestamp, and a short
    payload hash so the Protocol Inspector can show "what would have been
    signed" without performing actual cryptographic verification.

    3rd PoC: `agent` is now also a permitted signer — the agent signs its
    `AgentDecisionTrace` so its choice between candidates is auditable.
    """

    signer: Literal["user", "merchant", "psp", "agent"]
    signed_at: int
    payload_hash: str
    note: str = "stub — real signing handled by external device"


class PriceRange(BaseModel):
    from_cents: int
    to_cents: int


# ---------- 3rd-PoC: priority weights ----------


PriorityPreset = Literal["cheapest", "balanced", "trusted", "fastest"]


class PriorityWeights(BaseModel):
    """User's relative emphasis across the comparison dimensions.

    All four dimensions are present so the Comparison Engine never has to
    guess. Sum is not constrained to 1.0 — the engine normalizes. Backward
    compatible: an IntentMandate without `priority` falls back to the
    cheapest-only behaviour of PoC2.
    """

    price: float = 0.5
    trust: float = 0.2
    rating: float = 0.2
    shipping: float = 0.1


# Public preset → weights mapping. UI surfaces only presets to keep the demo
# legible; the underlying mandate still carries the full weights vector.
PRIORITY_PRESETS: dict[str, PriorityWeights] = {
    "cheapest": PriorityWeights(price=1.0, trust=0.0, rating=0.0, shipping=0.0),
    "balanced": PriorityWeights(price=0.4, trust=0.25, rating=0.25, shipping=0.1),
    "trusted":  PriorityWeights(price=0.2, trust=0.5,  rating=0.25, shipping=0.05),
    "fastest":  PriorityWeights(price=0.25, trust=0.2, rating=0.15, shipping=0.4),
}


# ---------- mandates ----------


class IntentMandate(BaseModel):
    """Captured from the user's structured intent form.

    Bounds what the agent may buy: which merchants, what price band, until when,
    and whether automatic purchasing is permitted (PoC always treats as manual).

    3rd-PoC fields (Optional for backward compatibility):
      - `priority_preset`: the human-readable label the user selected.
      - `priority`: the expanded weights vector. Both are signed into the
        Intent's payload_hash so the agent cannot silently mutate them.
    """

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    item_query: str
    price_range: PriceRange
    allowed_merchants: list[str]
    expires_at: int
    auto_purchase: bool = False
    priority_preset: PriorityPreset | None = None
    priority: PriorityWeights | None = None
    signature: StubSignature


class LineItem(BaseModel):
    product_id: str
    title: str
    qty: int
    unit_price_cents: int
    image_url: str | None = None
    source_merchant: str | None = None
    product_url: str | None = None

    @property
    def line_total_cents(self) -> int:
        return self.qty * self.unit_price_cents


class CheckoutBody(BaseModel):
    """The cart the merchant has assembled and is willing to honor."""

    id: str
    status: Literal["ready_for_complete", "completed", "cancelled"]
    buyer_email: str
    line_items: list[LineItem]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    currency: str = "USD"
    merchant_id: str = "demo-shop"
    created_at: int = Field(default_factory=_now)


class MerchantAuthorization(BaseModel):
    """Merchant's commitment to a specific checkout body."""

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    checkout_id: str
    checkout_body: dict[str, Any]
    signature: StubSignature


# ---------- 3rd PoC: comparison report + agent decision trace ----------


class CandidateScore(BaseModel):
    """A single product candidate scored along the comparison dimensions.

    Numeric fields come from the catalog (price, rating, reviews) or the
    deterministic enrichment layer (reputation_score, shipping_note). The
    Comparison Engine never asks the LLM to invent numbers — `normalized`
    and `weighted_score` are computed in pure Python.
    """

    product_id: str
    title: str
    source_merchant: str
    price_cents: int
    rating: float | None = None
    reviews_count: int | None = None
    reputation_score: int            # 0–100, static_demo_registry
    shipping_note: str               # human-readable, deterministic per merchant
    normalized: dict[str, float]     # dim → 0..1
    weighted_score: float            # 0..1
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class ComparisonReport(BaseModel):
    """Merchant-side comparison artifact, pre-LLM.

    The agent is shown this table and asked to pick a winner with reasoning.
    The engine's own top pick is `engine_winner_id`; the agent's pick lives
    on `AgentDecisionTrace`. Any divergence is a feature (surface it in UI).
    """

    intent_jti: str
    candidates: list[CandidateScore]
    engine_winner_id: str
    runner_ups: list[str]
    dimensions_used: list[str]       # e.g. ["price", "rating", "reputation_score(source=static_demo_registry)"]
    generated_at: int = Field(default_factory=_now)


class TradeoffRow(BaseModel):
    product_id: str
    relative_strengths: list[str]
    relative_weaknesses: list[str]
    why_not_chosen: str | None = None  # None for the winner


class AgentDecisionTrace(BaseModel):
    """The agent's *signed* rationale for picking one candidate over others.

    `signer="agent"` distinguishes this from user- and merchant-signed
    mandates. It documents how the user's priority shaped the decision and
    notes any dimensions that had to be dropped (e.g. ratings unavailable).
    """

    intent_jti: str
    engine_winner_id: str            # what the engine would have picked
    agent_winner_id: str             # what the agent actually picked
    headline: str
    tradeoffs: list[TradeoffRow]
    priority_explanation: str
    dropped_dimensions: list[str] = Field(default_factory=list)
    generated_at: int = Field(default_factory=_now)
    signature: StubSignature


# ---------- retained but unused in 2nd PoC ----------
# CheckoutMandate / PaymentMandate would be reached only after the user's
# Approve action, which is disabled in this PoC. We omit them rather than ship
# half-defined types; the 1st PoC's commit history preserves the full chain.
