"""UCP-compatible merchant service (demo).

Endpoints:
  GET  /ucp/search                       — discover products
  POST /ucp/checkout                     — open a checkout session (returns ap2.merchant_authorization)
  POST /ucp/checkout/{id}/complete       — submit ap2.checkout_mandate to finalize
  GET  /ucp/_inspect/state               — debug view of in-memory checkouts
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.merchant import catalog
from services.shared.crypto import content_hash, sign, verify
from services.shared.eventlog import log_event
from services.shared.mandates import (
    CheckoutBody,
    LineItem,
    MerchantAuthorization,
)

app = FastAPI(title="UCP Merchant (demo)")

# In-memory store: checkout_id -> checkout state
_CHECKOUTS: dict[str, dict[str, Any]] = {}

TAX_RATE = 0.08
MERCHANT_ID = "demo-shop"


# ---------- request/response models ----------


class SearchRequest(BaseModel):
    query: str | None = None
    max_price_cents: int | None = None
    color: str | None = None


class CartItemReq(BaseModel):
    product_id: str
    qty: int = 1


class CheckoutCreateRequest(BaseModel):
    items: list[CartItemReq]
    buyer_email: str
    intent_mandate_jws: str  # signed by user — proves there's an authorizing intent


class CheckoutCreateResponse(BaseModel):
    checkout: dict
    ap2: dict  # {"merchant_authorization": "<jws>"}


class CheckoutCompleteRequest(BaseModel):
    checkout_mandate_jws: str  # signed by user, embeds the merchant_authorization


class CheckoutCompleteResponse(BaseModel):
    checkout_id: str
    status: Literal["completed"]
    payment_mandate_jws_request: dict  # what the agent should send to the PSP


# ---------- endpoints ----------


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "merchant", "merchant_id": MERCHANT_ID}


@app.post("/ucp/search")
def search(req: SearchRequest) -> dict:
    results = catalog.search(req.query, req.max_price_cents, req.color)
    log_event(
        "merchant",
        "ucp.search",
        f"Searched: q={req.query!r} max={req.max_price_cents} color={req.color} → {len(results)} hits",
        {"query": req.model_dump(), "result_count": len(results)},
    )
    return {"results": results, "count": len(results)}


@app.post("/ucp/checkout", response_model=CheckoutCreateResponse)
def create_checkout(req: CheckoutCreateRequest) -> CheckoutCreateResponse:
    # 1. Verify the user's Intent Mandate — merchant must see a valid intent before binding.
    try:
        intent = verify(req.intent_mandate_jws, expected_issuer="user")
    except ValueError as e:
        log_event("merchant", "ucp.checkout.reject", f"Invalid intent mandate: {e}")
        raise HTTPException(400, f"invalid intent mandate: {e}")

    # 2. Build line items + totals.
    line_items: list[LineItem] = []
    for item in req.items:
        product = catalog.get(item.product_id)
        if product is None:
            raise HTTPException(404, f"unknown product: {item.product_id}")
        line_items.append(catalog.make_line_item(item.product_id, item.qty))

    subtotal = sum(li.line_total_cents for li in line_items)
    tax = round(subtotal * TAX_RATE)
    total = subtotal + tax

    # 3. Enforce intent constraints.
    max_price = (intent.get("constraints") or {}).get("max_price_cents")
    if max_price is not None and total > max_price:
        log_event(
            "merchant",
            "ucp.checkout.reject",
            f"Total {total} exceeds intent max_price {max_price}",
        )
        raise HTTPException(400, f"total {total} exceeds intent max_price {max_price}")

    checkout = CheckoutBody(
        id=f"chk_{uuid.uuid4().hex[:12]}",
        status="ready_for_complete",
        buyer_email=req.buyer_email,
        line_items=line_items,
        subtotal_cents=subtotal,
        tax_cents=tax,
        total_cents=total,
        merchant_id=MERCHANT_ID,
    )

    # 4. Merchant signs the checkout body — binds it via content_hash.
    body_dict = checkout.model_dump()
    auth = MerchantAuthorization(
        checkout_id=checkout.id,
        checkout_hash=content_hash(body_dict),
    )
    auth_jws = sign("merchant", auth.model_dump())

    _CHECKOUTS[checkout.id] = {
        "body": body_dict,
        "merchant_authorization_jws": auth_jws,
        "status": "ready_for_complete",
        "intent_mandate_jti": intent.get("jti"),
    }

    log_event(
        "merchant",
        "ucp.checkout.created",
        f"Checkout {checkout.id} ready (total ${total/100:.2f})",
        {
            "checkout_id": checkout.id,
            "total_cents": total,
            "merchant_authorization_jws": auth_jws,
            "checkout_body": body_dict,
        },
    )

    return CheckoutCreateResponse(
        checkout=body_dict,
        ap2={"merchant_authorization": auth_jws},
    )


@app.post("/ucp/checkout/{checkout_id}/complete", response_model=CheckoutCompleteResponse)
def complete_checkout(checkout_id: str, req: CheckoutCompleteRequest) -> CheckoutCompleteResponse:
    state = _CHECKOUTS.get(checkout_id)
    if state is None:
        raise HTTPException(404, "unknown checkout")
    if state["status"] != "ready_for_complete":
        raise HTTPException(409, f"checkout state is {state['status']}")

    # Verify user's Checkout Mandate.
    try:
        cm = verify(req.checkout_mandate_jws, expected_issuer="user")
    except ValueError as e:
        log_event("merchant", "ucp.complete.reject", f"Invalid checkout mandate: {e}")
        raise HTTPException(400, f"invalid checkout mandate: {e}")

    # Cross-check: the user-signed checkout body must match what we signed.
    user_body = cm.get("checkout_body")
    if content_hash(user_body) != content_hash(state["body"]):
        log_event("merchant", "ucp.complete.reject", "Checkout body hash mismatch")
        raise HTTPException(400, "checkout body hash mismatch")
    if cm.get("merchant_authorization_jws") != state["merchant_authorization_jws"]:
        log_event("merchant", "ucp.complete.reject", "merchant_authorization mismatch")
        raise HTTPException(400, "merchant_authorization mismatch")
    if cm.get("user_decision") != "approved":
        raise HTTPException(400, "user did not approve")

    # Verify the embedded Intent Mandate too — full chain check.
    try:
        verify(cm["intent_mandate_jws"], expected_issuer="user")
    except ValueError as e:
        raise HTTPException(400, f"invalid embedded intent mandate: {e}")

    state["status"] = "completed"
    log_event(
        "merchant",
        "ucp.complete.ok",
        f"Checkout {checkout_id} completed; agent should now call PSP",
        {"checkout_id": checkout_id, "total_cents": state["body"]["total_cents"]},
    )

    return CheckoutCompleteResponse(
        checkout_id=checkout_id,
        status="completed",
        payment_mandate_jws_request={
            "amount_cents": state["body"]["total_cents"],
            "currency": state["body"]["currency"],
            "merchant_id": state["body"]["merchant_id"],
            "checkout_mandate_jws": req.checkout_mandate_jws,
        },
    )


@app.get("/ucp/_inspect/state")
def inspect_state() -> dict:
    return {"checkouts": _CHECKOUTS}
