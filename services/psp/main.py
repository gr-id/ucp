"""Payment Service Provider (PSP) — verifies AP2 Mandate chain and authorizes the charge.

Endpoints:
  POST /psp/charge  — accepts a Payment Mandate (JWS) and the full chain inside it.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.shared.crypto import content_hash, verify
from services.shared.eventlog import log_event

app = FastAPI(title="AP2 PSP (demo)")


class ChargeRequest(BaseModel):
    payment_mandate_jws: str


class ChargeResponse(BaseModel):
    status: Literal["authorized", "declined"]
    transaction_id: str
    amount_cents: int
    currency: str
    chain_verified: dict


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "psp"}


@app.post("/psp/charge", response_model=ChargeResponse)
def charge(req: ChargeRequest) -> ChargeResponse:
    # 1. Verify Payment Mandate (user-signed).
    try:
        pm = verify(req.payment_mandate_jws, expected_issuer="user")
    except ValueError as e:
        log_event("psp", "psp.reject", f"Invalid payment mandate: {e}")
        raise HTTPException(400, f"invalid payment mandate: {e}")

    # 2. Verify embedded Checkout Mandate (user-signed).
    try:
        cm = verify(pm["checkout_mandate_jws"], expected_issuer="user")
    except ValueError as e:
        log_event("psp", "psp.reject", f"Invalid checkout mandate: {e}")
        raise HTTPException(400, f"invalid checkout mandate: {e}")

    # 3. Verify embedded Merchant Authorization (merchant-signed).
    try:
        ma = verify(cm["merchant_authorization_jws"], expected_issuer="merchant")
    except ValueError as e:
        log_event("psp", "psp.reject", f"Invalid merchant authorization: {e}")
        raise HTTPException(400, f"invalid merchant authorization: {e}")

    # 4. Verify embedded Intent Mandate (user-signed).
    try:
        im = verify(cm["intent_mandate_jws"], expected_issuer="user")
    except ValueError as e:
        log_event("psp", "psp.reject", f"Invalid intent mandate: {e}")
        raise HTTPException(400, f"invalid intent mandate: {e}")

    # 5. Cross-check binding: checkout body the user signed must match the hash the merchant signed.
    if content_hash(cm["checkout_body"]) != ma["checkout_hash"]:
        log_event("psp", "psp.reject", "merchant_authorization.checkout_hash mismatch")
        raise HTTPException(400, "checkout hash mismatch")

    # 6. Amount must match the signed checkout body.
    if pm["amount_cents"] != cm["checkout_body"]["total_cents"]:
        log_event("psp", "psp.reject", "amount mismatch")
        raise HTTPException(400, "payment amount does not match checkout total")

    # 7. Intent constraints honored.
    max_price = (im.get("constraints") or {}).get("max_price_cents")
    if max_price is not None and pm["amount_cents"] > max_price:
        log_event("psp", "psp.reject", "amount exceeds intent constraint")
        raise HTTPException(400, "payment exceeds intent max_price")

    txn_id = f"txn_{uuid.uuid4().hex[:12]}"
    log_event(
        "psp",
        "psp.charge.authorized",
        f"Authorized ${pm['amount_cents']/100:.2f} {pm['currency']} → {txn_id}",
        {
            "transaction_id": txn_id,
            "amount_cents": pm["amount_cents"],
            "chain": {
                "intent_jti": im.get("jti"),
                "checkout_mandate_jti": cm.get("jti"),
                "merchant_authorization_jti": ma.get("jti"),
                "payment_mandate_jti": pm.get("jti"),
            },
        },
    )

    return ChargeResponse(
        status="authorized",
        transaction_id=txn_id,
        amount_cents=pm["amount_cents"],
        currency=pm["currency"],
        chain_verified={
            "intent_mandate": "✓ signed by user",
            "merchant_authorization": "✓ signed by merchant, bound to checkout body",
            "checkout_mandate": "✓ signed by user, embeds merchant_authorization",
            "payment_mandate": "✓ signed by user, embeds checkout_mandate",
        },
    )
