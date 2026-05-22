"""Build a signed IntentMandate from the 5-field user form.

Form schema (all required):
  item_query:        str   — what to buy (free text)
  price_from_cents:  int   — minimum acceptable price (USD cents)
  price_to_cents:    int   — maximum acceptable price (USD cents)
  allowed_merchants: list[str]  — subset of supported merchants
  valid_hours:       int   — how long the intent remains valid (hours)
  auto_purchase:     bool  — user permission for automatic purchase
                              (PoC always treats as manual approval)
"""

from __future__ import annotations

import time
from typing import Any

from services.shared.mandates import IntentMandate, PriceRange
from services.shared.stub_sig import stub_sign

SUPPORTED_MERCHANTS = ("walmart", "target", "wayfair", "etsy")


class FormValidationError(ValueError):
    pass


def _validate(form: dict[str, Any]) -> None:
    if not form.get("item_query", "").strip():
        raise FormValidationError("구매할 물품(item_query)이 비어 있습니다.")
    pf = int(form.get("price_from_cents", 0))
    pt = int(form.get("price_to_cents", 0))
    if pf < 0 or pt < 0:
        raise FormValidationError("가격은 0 이상이어야 합니다.")
    if pf > pt:
        raise FormValidationError("최저가가 최고가보다 큽니다.")
    merchants = form.get("allowed_merchants") or []
    if not merchants:
        raise FormValidationError("최소 1개 머천트를 선택해야 합니다.")
    unknown = [m for m in merchants if m not in SUPPORTED_MERCHANTS]
    if unknown:
        raise FormValidationError(f"지원하지 않는 머천트: {unknown}")
    vh = int(form.get("valid_hours", 0))
    if vh <= 0:
        raise FormValidationError("유지 시간은 1시간 이상이어야 합니다.")


def build_intent_from_form(form: dict[str, Any]) -> IntentMandate:
    """Validate the form and produce a stub-signed IntentMandate."""
    _validate(form)

    item_query = form["item_query"].strip()
    price_range = PriceRange(
        from_cents=int(form["price_from_cents"]),
        to_cents=int(form["price_to_cents"]),
    )
    allowed_merchants = sorted(set(form["allowed_merchants"]))
    expires_at = int(time.time()) + int(form["valid_hours"]) * 3600
    auto_purchase = bool(form.get("auto_purchase", False))

    # Pre-build the body so we can hash it for the signature; signing covers all
    # fields except the signature itself.
    body_for_hash = {
        "item_query": item_query,
        "price_range": price_range.model_dump(),
        "allowed_merchants": allowed_merchants,
        "expires_at": expires_at,
        "auto_purchase": auto_purchase,
    }
    sig = stub_sign("user", body_for_hash)

    return IntentMandate(
        item_query=item_query,
        price_range=price_range,
        allowed_merchants=allowed_merchants,
        expires_at=expires_at,
        auto_purchase=auto_purchase,
        signature=sig,
    )
