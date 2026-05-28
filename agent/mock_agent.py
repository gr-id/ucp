"""Mock shopping agent — 2nd PoC, form-driven.

Runs the structured-intent flow without an LLM:
  1. Build & stub-sign an IntentMandate from the form dict.
  2. UCP search across the form's allowed merchants and price band.
  3. Pick the cheapest matching product (no semantic reasoning).
  4. UCP checkout — receive the merchant's StubSignature.
  5. STOP. The 2nd PoC never proceeds to Approve / Payment.

The PSP service is never contacted; the `finalize()` API of the 1st PoC is gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from services.shared.eventlog import log_event
from services.shared.intent import build_intent_from_form
from services.shared.mandates import IntentMandate, MerchantAuthorization

MERCHANT_URL = "http://localhost:8001"


@dataclass
class AgentSession:
    form: dict[str, Any]
    intent: IntentMandate | None = None
    candidates: list[dict] = field(default_factory=list)
    by_merchant: dict[str, int] = field(default_factory=dict)
    selected: dict | None = None
    checkout_body: dict | None = None
    merchant_authorization: dict | None = None
    catalog_mode: str | None = None
    error: str | None = None
    # 3rd-PoC: comparison report + signed decision trace. Mock agent leaves
    # these None to keep the cheap-vs-rich-rationale contrast visible in UI.
    comparison: dict | None = None
    decision_trace: dict | None = None
    # Per-user secrets, never logged. Held only for the duration of the call.
    serpapi_key: str | None = None


def _step_build_intent(session: AgentSession) -> None:
    session.intent = build_intent_from_form(session.form)
    log_event(
        "user",
        "intent.built",
        f"Intent {session.intent.jti} signed "
        f"(${session.intent.price_range.from_cents/100:.0f}–${session.intent.price_range.to_cents/100:.0f}, "
        f"{session.intent.allowed_merchants}, exp {session.intent.expires_at})",
        {"intent_mandate": session.intent.model_dump()},
    )


def _step_search(session: AgentSession) -> None:
    assert session.intent is not None
    body = {
        "item_query": session.intent.item_query,
        "price_from_cents": session.intent.price_range.from_cents,
        "price_to_cents": session.intent.price_range.to_cents,
        "allowed_merchants": session.intent.allowed_merchants,
    }
    if session.serpapi_key:
        body["serpapi_key"] = session.serpapi_key
    with httpx.Client(timeout=30) as client:
        r = client.post(f"{MERCHANT_URL}/ucp/search", json=body)
        r.raise_for_status()
        data = r.json()
    session.candidates = data.get("results", [])
    session.by_merchant = data.get("by_merchant", {})
    session.catalog_mode = data.get("catalog_mode")


def _step_select(session: AgentSession) -> None:
    if not session.candidates:
        return
    session.selected = min(session.candidates, key=lambda p: p["price_cents"])
    log_event(
        "agent",
        "agent.select",
        f"Selected {session.selected['title']} from {session.selected.get('source_merchant')} "
        f"(${session.selected['price_cents']/100:.2f})",
        {"selected": session.selected, "candidates_count": len(session.candidates)},
    )


def _step_checkout(session: AgentSession) -> None:
    assert session.intent is not None and session.selected is not None
    with httpx.Client(timeout=15) as client:
        r = client.post(
            f"{MERCHANT_URL}/ucp/checkout",
            json={
                "items": [{"product_id": session.selected["id"], "qty": 1}],
                "buyer_email": session.form.get("buyer_email", "demo@example.com"),
                "intent_mandate": session.intent.model_dump(),
            },
        )
        if r.status_code != 200:
            session.error = f"merchant rejected: {r.status_code} {r.text}"
            log_event("merchant", "ucp.checkout.reject", session.error)
            return
        data = r.json()
    session.checkout_body = data["checkout"]
    session.merchant_authorization = data["merchant_authorization"]
    log_event(
        "agent",
        "agent.cart_ready",
        f"Cart ready: {session.checkout_body['id']} (${session.checkout_body['total_cents']/100:.2f}) "
        f"— PoC stops here (no Approve).",
        {"checkout": session.checkout_body},
    )


def run_until_cart_form(form: dict[str, Any], serpapi_key: str | None = None) -> AgentSession:
    """Drive the entire 2nd-PoC flow up to (but not including) Approve.

    `serpapi_key` is the per-user SerpAPI key; if None the server falls back
    to its SERPAPI_KEY env var.
    """
    session = AgentSession(form=form, serpapi_key=serpapi_key)
    log_event(
        "user",
        "form.submit",
        f"User submitted form: {form.get('item_query')!r} in {form.get('allowed_merchants')}",
        {"form": form, "user_supplied_serpapi_key": bool(serpapi_key)},
    )
    try:
        _step_build_intent(session)
        _step_search(session)
        _step_select(session)
        if session.selected is not None:
            _step_checkout(session)
    except Exception as e:
        session.error = str(e)
        log_event("agent", "agent.error", session.error)
    return session
