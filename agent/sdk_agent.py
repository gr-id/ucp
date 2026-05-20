"""Claude Agent SDK variant of the shopping agent.

Same end-state as agent.mock_agent.run_until_cart, but Claude (via the SDK)
decides search parameters and which product to pick, by calling MCP tools.

Stage 2 (user approval → finalize) is unchanged — finalize() from mock_agent
is reused, since that step is purely cryptographic and needs no LLM.

Requires:
  - Claude Code CLI installed and logged in (`claude --version` should work).
  - `uv sync --group agent` to install claude-agent-sdk.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

from agent.mock_agent import AgentSession, MERCHANT_URL
from services.shared.crypto import sign
from services.shared.eventlog import log_event
from services.shared.mandates import Constraints, IntentMandate


# Per-call state — the tools mutate the AgentSession bound to the current call.
_CURRENT: dict[str, AgentSession] = {}


@tool(
    "sign_intent_mandate",
    "Sign the user's Intent Mandate. Call this first — it captures what the user wants and bounds what you may buy. max_price_cents may be null if the user didn't specify a price ceiling.",
    {
        "natural_language": str,
        "max_price_cents": int | None,
        "color": str | None,
    },
)
async def sign_intent_mandate(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    constraints = Constraints(
        max_price_cents=args.get("max_price_cents"),
        currency="USD",
        keywords=[],
    )
    session.intent = IntentMandate(
        natural_language=args["natural_language"],
        constraints=constraints,
        expires_at=int(time.time()) + 600,
    )
    session.intent_jws = sign("user", session.intent.model_dump())
    log_event(
        "user",
        "intent.signed",
        f"User signed Intent Mandate (max=${(constraints.max_price_cents or 0)/100:.0f})",
        {"intent_mandate_jws": session.intent_jws, "intent": session.intent.model_dump()},
    )
    return {
        "content": [
            {"type": "text", "text": f"Intent signed. jti={session.intent.jti}. You may now call search_products."}
        ]
    }


@tool(
    "search_products",
    "Search the UCP merchant catalog. Returns matching products with id, title, price_cents, color.",
    {"query": str, "max_price_cents": int | None, "color": str | None},
)
async def search_products(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{MERCHANT_URL}/ucp/search",
            json={
                "query": args.get("query"),
                "max_price_cents": args.get("max_price_cents"),
                "color": args.get("color"),
            },
        )
        r.raise_for_status()
        data = r.json()
    session.candidates = data["results"]
    summary = [
        f"{p['id']}: {p['title']} ({p['color']}) — ${p['price_cents']/100:.2f}"
        for p in data["results"]
    ]
    return {
        "content": [
            {
                "type": "text",
                "text": f"{data['count']} results:\n" + "\n".join(summary or ["(none)"]),
            }
        ]
    }


@tool(
    "propose_cart",
    "Open a UCP checkout for the chosen product. The merchant will respond with a signed merchant_authorization. Call this once you've decided what to buy.",
    {"product_id": str, "qty": int},
)
async def propose_cart(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    if session.intent_jws is None:
        return {"content": [{"type": "text", "text": "Error: sign_intent_mandate must be called first."}]}
    chosen = next((p for p in session.candidates if p["id"] == args["product_id"]), None)
    session.selected = chosen
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{MERCHANT_URL}/ucp/checkout",
            json={
                "items": [{"product_id": args["product_id"], "qty": args["qty"]}],
                "buyer_email": session.buyer_email,
                "intent_mandate_jws": session.intent_jws,
            },
        )
        if r.status_code != 200:
            return {"content": [{"type": "text", "text": f"Merchant rejected: {r.status_code} {r.text}"}]}
        data = r.json()
    session.checkout_body = data["checkout"]
    session.merchant_authorization_jws = data["ap2"]["merchant_authorization"]
    session.checkout_id = session.checkout_body["id"]
    log_event(
        "agent",
        "agent.cart_ready",
        f"Cart ready: {session.checkout_body['id']} (${session.checkout_body['total_cents']/100:.2f})",
        {"checkout": session.checkout_body},
    )
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Cart {session.checkout_body['id']} created, total "
                    f"${session.checkout_body['total_cents']/100:.2f}. "
                    "Awaiting user approval — stop here."
                ),
            }
        ]
    }


SYSTEM_PROMPT = """\
You are an autonomous shopping agent operating under the AP2 (Agent Payments Protocol) trust model.

Process for every purchase request:
  1. Call sign_intent_mandate FIRST with the user's natural-language request and any constraints
     (max price, color, etc.) you can extract.
  2. Call search_products with a focused query and the same constraints.
  3. Pick ONE product that best satisfies the user — prefer the option closest to the user's stated
     intent over the cheapest. Tie-break by price.
  4. Call propose_cart with product_id and qty=1.
  5. After propose_cart returns, STOP. Do not attempt to finalize — the user must approve in the UI.

Never invent products. Never call propose_cart with a product that didn't appear in search_products.
If search returns zero matches, say so and stop.
"""


async def _run(session: AgentSession) -> None:
    _CURRENT["session"] = session
    log_event("user", "user.prompt", f"User: {session.user_prompt}")

    server = create_sdk_mcp_server(
        name="ucp_ap2",
        version="0.1.0",
        tools=[sign_intent_mandate, search_products, propose_cart],
    )
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={"ucp_ap2": server},
        allowed_tools=[
            "mcp__ucp_ap2__sign_intent_mandate",
            "mcp__ucp_ap2__search_products",
            "mcp__ucp_ap2__propose_cart",
        ],
        max_turns=10,
    )

    async for msg in query(prompt=session.user_prompt, options=options):
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    log_event("agent", "agent.thought", block.text.strip()[:200])
                elif isinstance(block, ToolUseBlock):
                    log_event("agent", "agent.tool_use", f"calling {block.name}", {"input": block.input})


def run_until_cart_sdk(prompt: str) -> AgentSession:
    """SDK-driven equivalent of mock_agent.run_until_cart."""
    session = AgentSession(user_prompt=prompt)
    asyncio.run(_run(session))
    return session
