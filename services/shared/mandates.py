"""Pydantic models for AP2 Mandates (simplified JWS-only demo variant).

Spec correspondence:
  IntentMandate     — AP2 Intent Mandate (signed by user)
  MerchantAuthorization — UCP `ap2.merchant_authorization` (signed by merchant)
  CheckoutMandate   — UCP `ap2.checkout_mandate` (signed by user, embeds checkout)
  PaymentMandate    — AP2 Payment Mandate (signed by user, sent to PSP)
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


class Constraints(BaseModel):
    max_price_cents: int | None = None
    currency: str = "USD"
    keywords: list[str] = Field(default_factory=list)


class IntentMandate(BaseModel):
    """Captured before the agent does anything. Bounds what the agent may buy."""

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    natural_language: str
    constraints: Constraints
    expires_at: int


class LineItem(BaseModel):
    product_id: str
    title: str
    qty: int
    unit_price_cents: int

    @property
    def line_total_cents(self) -> int:
        return self.qty * self.unit_price_cents


class CheckoutBody(BaseModel):
    """The UCP checkout object the merchant returns. Signed by the merchant."""

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
    """Signed by merchant; binds the checkout body via content_hash."""

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    checkout_id: str
    checkout_hash: str  # base64url(sha256(JCS(CheckoutBody)))


class CheckoutMandate(BaseModel):
    """Signed by user; commits user to a specific checkout. Embeds the prior chain."""

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    intent_mandate_jws: str  # signed Intent Mandate
    checkout_body: dict[str, Any]  # the exact body the merchant signed
    merchant_authorization_jws: str  # merchant's signature over checkout body
    user_decision: Literal["approved", "declined"] = "approved"


class PaymentMethod(BaseModel):
    type: Literal["card_token"] = "card_token"
    token: str = "tok_demo_visa_4242"
    last4: str = "4242"


class PaymentMandate(BaseModel):
    """Signed by user; sent to PSP along with the prior chain to authorize charge."""

    jti: str = Field(default_factory=_jti)
    iat: int = Field(default_factory=_now)
    checkout_mandate_jws: str
    amount_cents: int
    currency: str = "USD"
    merchant_id: str
    payment_method: PaymentMethod = Field(default_factory=PaymentMethod)
