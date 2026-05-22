"""Pydantic models for AP2 Mandates (2nd PoC — stub-signature variant).

Schema evolution from 1st PoC:
  - `IntentMandate` now uses structured fields (item_query, price_range,
    allowed_merchants, expires_at, auto_purchase) instead of free-text natural
    language + ad-hoc Constraints.
  - All Mandate types carry a `StubSignature` instead of being wrapped in a JWS
    string. The 1st PoC proved real ES256 JWS; this PoC focuses on data + UX.
  - `LineItem` gains `image_url`, `source_merchant`, `product_url` so the UI can
    show real product visuals when the catalog is backed by SerpAPI.
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
    """

    signer: Literal["user", "merchant", "psp"]
    signed_at: int
    payload_hash: str
    note: str = "stub — 2nd PoC: real signing handled by external device"


class PriceRange(BaseModel):
    from_cents: int
    to_cents: int


# ---------- mandates ----------


class IntentMandate(BaseModel):
    """Captured from the user's structured intent form.

    Bounds what the agent may buy: which merchants, what price band, until when,
    and whether automatic purchasing is permitted (PoC always treats as manual).
    """

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    item_query: str
    price_range: PriceRange
    allowed_merchants: list[str]
    expires_at: int
    auto_purchase: bool = False
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


# ---------- retained but unused in 2nd PoC ----------
# CheckoutMandate / PaymentMandate would be reached only after the user's
# Approve action, which is disabled in this PoC. We omit them rather than ship
# half-defined types; the 1st PoC's commit history preserves the full chain.
