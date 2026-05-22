"""UCP-compatible merchant service (2nd PoC).

Differences from the 1st PoC merchant:
  - No JWS verification — Mandates carry `StubSignature` placeholders. The
    underlying *data* of the Intent is still enforced (price band, allowed
    merchants, expiry); only the cryptographic ceremony is abstracted.
  - `/ucp/search` request body carries the structured intent fields directly.
  - `/ucp/checkout` accepts the full IntentMandate (as JSON) and verifies the
    cart against it.
  - The endpoint chain stops at checkout — the 2nd PoC never reaches
    `/ucp/checkout/{id}/complete`. We keep the route registered so the 1st-PoC
    smoke test can still hit it during regression, but it now operates on the
    new schema.

Endpoints:
  GET  /healthz
  POST /ucp/search                          — discover products
  POST /ucp/checkout                        — open a checkout session
  GET  /ucp/_inspect/state                  — debug view of in-memory checkouts
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Literal

# Load .env at import time so direct `uvicorn services.merchant.main:app`
# launches pick up SERPAPI_KEY / UCP_CATALOG_MODE without manual export.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.merchant import catalog
from services.shared.eventlog import log_event
from services.shared.mandates import (
    CheckoutBody,
    IntentMandate,
    LineItem,
    MerchantAuthorization,
)
from services.shared.stub_sig import stub_sign

app = FastAPI(title="UCP Merchant (2nd PoC)")

_CHECKOUTS: dict[str, dict[str, Any]] = {}

TAX_RATE = 0.08
MERCHANT_ID = "demo-shop"


# ---------- request/response models ----------


class SearchRequest(BaseModel):
    item_query: str
    price_from_cents: int = 0
    price_to_cents: int = 10_000_00
    allowed_merchants: list[str] = []
    # Optional per-request SerpAPI key — overrides server env. Never logged.
    serpapi_key: str | None = None


class CartItemReq(BaseModel):
    product_id: str
    qty: int = 1


class CheckoutCreateRequest(BaseModel):
    items: list[CartItemReq]
    buyer_email: str
    intent_mandate: IntentMandate  # carries StubSignature


class CheckoutCreateResponse(BaseModel):
    checkout: dict
    merchant_authorization: MerchantAuthorization
    catalog_mode: str


# ---------- endpoints ----------


@app.get("/healthz")
def healthz() -> dict:
    return {
        "ok": True,
        "service": "merchant",
        "merchant_id": MERCHANT_ID,
        "catalog_mode": catalog.get_mode(),
    }


@app.post("/ucp/search")
def search(req: SearchRequest) -> dict:
    results = catalog.search(
        query=req.item_query,
        from_cents=req.price_from_cents,
        to_cents=req.price_to_cents,
        allowed_merchants=req.allowed_merchants,
        serpapi_key=req.serpapi_key,
    )
    # Summary of merchant distribution — useful in the Protocol Inspector.
    by_merchant: dict[str, int] = {}
    for r in results:
        m = r.get("source_merchant") or "unknown"
        by_merchant[m] = by_merchant.get(m, 0) + 1

    # Log without the SerpAPI key — it's a per-user secret.
    safe_query = req.model_dump(exclude={"serpapi_key"})
    log_event(
        "merchant",
        "ucp.search",
        f"Searched: {req.item_query!r} ${req.price_from_cents/100:.0f}–${req.price_to_cents/100:.0f} "
        f"in {req.allowed_merchants or 'all'} → {len(results)} hits ({by_merchant})",
        {
            "query": safe_query,
            "user_supplied_serpapi_key": bool(req.serpapi_key),
            "result_count": len(results),
            "by_merchant": by_merchant,
            "catalog_mode": catalog.get_mode(),
        },
    )
    return {
        "results": results,
        "count": len(results),
        "by_merchant": by_merchant,
        "catalog_mode": catalog.get_mode(),
    }


@app.post("/ucp/checkout", response_model=CheckoutCreateResponse)
def create_checkout(req: CheckoutCreateRequest) -> CheckoutCreateResponse:
    intent = req.intent_mandate

    # 1. Intent must still be valid.
    if intent.expires_at < int(time.time()):
        log_event("merchant", "ucp.checkout.reject", f"Intent {intent.jti} expired")
        raise HTTPException(400, "intent mandate expired")

    # 2. Build line items + totals, and verify each item is from an allowed merchant.
    line_items: list[LineItem] = []
    for item in req.items:
        product = catalog.get(item.product_id)
        if product is None:
            raise HTTPException(404, f"unknown product: {item.product_id}")
        if intent.allowed_merchants and product.get("source_merchant") not in intent.allowed_merchants:
            log_event(
                "merchant",
                "ucp.checkout.reject",
                f"product {item.product_id} source {product.get('source_merchant')!r} not in intent.allowed_merchants",
            )
            raise HTTPException(400, f"merchant {product.get('source_merchant')!r} not in intent.allowed_merchants")
        line_items.append(catalog.make_line_item(item.product_id, item.qty))

    subtotal = sum(li.line_total_cents for li in line_items)
    tax = round(subtotal * TAX_RATE)
    total = subtotal + tax

    # 3. Enforce intent price range.
    if total < intent.price_range.from_cents or total > intent.price_range.to_cents:
        log_event(
            "merchant",
            "ucp.checkout.reject",
            f"Total {total} outside intent price range "
            f"[{intent.price_range.from_cents}, {intent.price_range.to_cents}]",
        )
        raise HTTPException(
            400,
            f"total {total} outside intent price range "
            f"[{intent.price_range.from_cents}, {intent.price_range.to_cents}]",
        )

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
    body_dict = checkout.model_dump()

    # 4. Merchant "signs" the checkout body (stub).
    merchant_auth = MerchantAuthorization(
        checkout_id=checkout.id,
        checkout_body=body_dict,
        signature=stub_sign("merchant", body_dict),
    )

    _CHECKOUTS[checkout.id] = {
        "body": body_dict,
        "merchant_authorization": merchant_auth.model_dump(),
        "status": "ready_for_complete",
        "intent_jti": intent.jti,
        "intent_mandate": intent.model_dump(),
    }

    log_event(
        "merchant",
        "ucp.checkout.created",
        f"Checkout {checkout.id} ready (total ${total/100:.2f})",
        {
            "checkout_id": checkout.id,
            "total_cents": total,
            "merchant_authorization": merchant_auth.model_dump(),
            "checkout_body": body_dict,
            "intent_jti": intent.jti,
        },
    )

    return CheckoutCreateResponse(
        checkout=body_dict,
        merchant_authorization=merchant_auth,
        catalog_mode=catalog.get_mode(),
    )


@app.get("/ucp/_inspect/state")
def inspect_state() -> dict:
    return {"checkouts": _CHECKOUTS, "catalog_mode": catalog.get_mode()}
