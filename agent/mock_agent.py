"""Mock shopping agent — runs the full UCP+AP2 flow without an LLM.

Drives the demo end-to-end:
  1. Parse the user prompt (very naive — keyword extraction).
  2. Sign an Intent Mandate.
  3. UCP search → pick the cheapest match within constraints.
  4. UCP checkout → receive merchant_authorization.
  5. Pause for user approval (caller decides).
  6. Sign Checkout Mandate → complete checkout.
  7. Sign Payment Mandate → PSP charge.

The agent never directly handles money — only signs verifiable credentials
and orchestrates calls between the UCP merchant and the PSP.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from services.shared.crypto import sign
from services.shared.eventlog import log_event
from services.shared.mandates import (
    CheckoutMandate,
    Constraints,
    IntentMandate,
    PaymentMandate,
)

MERCHANT_URL = "http://localhost:8001"
PSP_URL = "http://localhost:8002"


# ---------- naive prompt parsing ----------


def parse_prompt(prompt: str) -> tuple[str, Constraints]:
    """Extract a UCP search query and constraints from a free-text prompt.

    The real demo uses Claude — this is just enough to make the mock useful.
    """
    text = prompt.lower()

    # Price ceiling — "$150", "under 150", "150달러 이하" etc.
    max_price_cents: int | None = None
    m = re.search(r"\$?\s*(\d{2,5})\s*(달러|usd|dollars?)?\s*(이하|미만|under|below)?", text)
    if m:
        # Be conservative: only treat as a ceiling if we see "under/이하/미만" or a $ prefix.
        if "$" in prompt or any(w in text for w in ("under", "below", "이하", "미만", "보다 싼")):
            max_price_cents = int(m.group(1)) * 100

    color: str | None = None
    for c, kw in [
        ("white", ("white", "흰", "흰색")),
        ("black", ("black", "검", "검정", "블랙")),
    ]:
        if any(k in text for k in kw):
            color = c
            break

    keywords: list[str] = []
    for kw in ("running", "trail", "tee", "shoe", "shoes", "runner", "runners", "운동화", "신발", "티", "셔츠"):
        if kw in text:
            keywords.append(kw)

    # Build a search query that catalog.search can match against.
    if any(k in text for k in ("running", "runner", "runners", "운동화")):
        search_q = "running"
    elif "trail" in text:
        search_q = "trail"
    elif any(k in text for k in ("tee", "티", "셔츠")):
        search_q = "tech tee"
    else:
        search_q = ""

    constraints = Constraints(
        max_price_cents=max_price_cents,
        currency="USD",
        keywords=keywords,
    )
    return search_q, constraints


# ---------- agent state ----------


@dataclass
class AgentSession:
    user_prompt: str
    buyer_email: str = "demo@example.com"
    intent: IntentMandate | None = None
    intent_jws: str | None = None
    search_query: str = ""
    candidates: list[dict] = field(default_factory=list)
    selected: dict | None = None
    checkout_body: dict | None = None
    merchant_authorization_jws: str | None = None
    checkout_id: str | None = None
    checkout_mandate_jws: str | None = None
    psp_result: dict | None = None


# ---------- agent steps ----------


def step_create_intent(session: AgentSession) -> None:
    q, constraints = parse_prompt(session.user_prompt)
    session.search_query = q
    session.intent = IntentMandate(
        natural_language=session.user_prompt,
        constraints=constraints,
        expires_at=int(time.time()) + 600,
    )
    session.intent_jws = sign("user", session.intent.model_dump())
    log_event(
        "user",
        "intent.signed",
        f"User signed Intent Mandate (q={q!r}, max=${(constraints.max_price_cents or 0)/100:.0f})",
        {"intent_mandate_jws": session.intent_jws, "intent": session.intent.model_dump()},
    )


def step_search_and_select(session: AgentSession) -> None:
    assert session.intent is not None
    with httpx.Client(timeout=10) as client:
        r = client.post(
            f"{MERCHANT_URL}/ucp/search",
            json={
                "query": session.search_query,
                "max_price_cents": session.intent.constraints.max_price_cents,
                "color": _color_from_keywords(session.intent.natural_language),
            },
        )
        r.raise_for_status()
        data = r.json()
    session.candidates = data["results"]
    if not session.candidates:
        log_event("agent", "search.empty", "No matching products")
        return
    session.selected = min(session.candidates, key=lambda p: p["price_cents"])
    log_event(
        "agent",
        "agent.select",
        f"Agent selected {session.selected['title']} (${session.selected['price_cents']/100:.2f})",
        {"candidates": session.candidates, "selected": session.selected},
    )


def _color_from_keywords(prompt: str) -> str | None:
    text = prompt.lower()
    if any(k in text for k in ("white", "흰", "흰색")):
        return "white"
    if any(k in text for k in ("black", "검", "검정", "블랙")):
        return "black"
    return None


def step_create_checkout(session: AgentSession) -> None:
    assert session.selected is not None and session.intent_jws is not None
    with httpx.Client(timeout=10) as client:
        r = client.post(
            f"{MERCHANT_URL}/ucp/checkout",
            json={
                "items": [{"product_id": session.selected["id"], "qty": 1}],
                "buyer_email": session.buyer_email,
                "intent_mandate_jws": session.intent_jws,
            },
        )
        r.raise_for_status()
        data = r.json()
    session.checkout_body = data["checkout"]
    session.merchant_authorization_jws = data["ap2"]["merchant_authorization"]
    session.checkout_id = session.checkout_body["id"]
    log_event(
        "agent",
        "agent.cart_ready",
        f"Cart ready for user review: {session.checkout_body['id']} (${session.checkout_body['total_cents']/100:.2f})",
        {"checkout": session.checkout_body},
    )


def step_user_approve_and_complete(session: AgentSession) -> None:
    """User has approved the cart in the UI — sign Checkout Mandate and complete."""
    assert (
        session.intent_jws is not None
        and session.checkout_body is not None
        and session.merchant_authorization_jws is not None
        and session.checkout_id is not None
    )
    cm = CheckoutMandate(
        intent_mandate_jws=session.intent_jws,
        checkout_body=session.checkout_body,
        merchant_authorization_jws=session.merchant_authorization_jws,
        user_decision="approved",
    )
    cm_jws = sign("user", cm.model_dump())
    session.checkout_mandate_jws = cm_jws
    log_event(
        "user",
        "checkout_mandate.signed",
        "User signed Checkout Mandate (approves cart + binds merchant_authorization)",
        {"checkout_mandate_jws": cm_jws, "checkout_mandate": cm.model_dump()},
    )

    with httpx.Client(timeout=10) as client:
        r = client.post(
            f"{MERCHANT_URL}/ucp/checkout/{session.checkout_id}/complete",
            json={"checkout_mandate_jws": cm_jws},
        )
        r.raise_for_status()
        complete = r.json()

    # Sign Payment Mandate and send to PSP.
    pm = PaymentMandate(
        checkout_mandate_jws=cm_jws,
        amount_cents=complete["payment_mandate_jws_request"]["amount_cents"],
        currency=complete["payment_mandate_jws_request"]["currency"],
        merchant_id=complete["payment_mandate_jws_request"]["merchant_id"],
    )
    pm_jws = sign("user", pm.model_dump())
    log_event(
        "user",
        "payment_mandate.signed",
        f"User signed Payment Mandate for ${pm.amount_cents/100:.2f}",
        {"payment_mandate_jws": pm_jws, "payment_mandate": pm.model_dump()},
    )

    with httpx.Client(timeout=10) as client:
        r = client.post(
            f"{PSP_URL}/psp/charge",
            json={"payment_mandate_jws": pm_jws},
        )
        r.raise_for_status()
        session.psp_result = r.json()

    log_event(
        "agent",
        "agent.done",
        f"Purchase complete: {session.psp_result['transaction_id']}",
        {"psp_result": session.psp_result},
    )


def run_until_cart(prompt: str) -> AgentSession:
    """Stage 1: create intent + search + propose cart. Stops for user approval."""
    session = AgentSession(user_prompt=prompt)
    log_event("user", "user.prompt", f"User: {prompt}")
    step_create_intent(session)
    step_search_and_select(session)
    if session.selected is not None:
        step_create_checkout(session)
    return session


def finalize(session: AgentSession) -> AgentSession:
    """Stage 2: called after the user clicks 'Approve' in the UI."""
    step_user_approve_and_complete(session)
    return session
