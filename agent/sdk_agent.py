"""Claude Agent SDK variant of the 2nd-PoC shopping agent.

Same form-driven entrypoint as `mock_agent.run_until_cart_form`, but Claude
decides which product to pick by reading the search results' descriptions.

Requires:
  - Claude Code CLI installed and signed in (`claude --version`).
  - `uv sync --group agent`.
"""

from __future__ import annotations

import asyncio
import os
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
from services.shared.comparison import build_comparison, build_decision_trace
from services.shared.eventlog import log_event
from services.shared.intent import build_intent_from_form

_CURRENT: dict[str, AgentSession] = {}


@tool(
    "search_products",
    "Search the UCP merchant catalog within the user's intent constraints. "
    "Returns matching products (id, title, source_merchant, price_cents, description).",
    {"refine_query": str},
)
async def search_products(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    assert session.intent is not None
    # Allow Claude to broaden/narrow the search query while keeping price/merchant constraints intact.
    query_str = args.get("refine_query") or session.intent.item_query
    body = {
        "item_query": query_str,
        "price_from_cents": session.intent.price_range.from_cents,
        "price_to_cents": session.intent.price_range.to_cents,
        "allowed_merchants": session.intent.allowed_merchants,
    }
    if session.serpapi_key:
        body["serpapi_key"] = session.serpapi_key
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{MERCHANT_URL}/ucp/search", json=body)
        r.raise_for_status()
        data = r.json()
    session.candidates = data.get("results", [])
    session.by_merchant = data.get("by_merchant", {})
    session.catalog_mode = data.get("catalog_mode")

    summary = [
        f"{p['id']}: {p['title']} ({p.get('source_merchant')}) — ${p['price_cents']/100:.2f}"
        for p in session.candidates
    ]
    return {
        "content": [
            {
                "type": "text",
                "text": f"{data.get('count', 0)} results (by_merchant={session.by_merchant}):\n"
                + "\n".join(summary or ["(none)"]),
            }
        ]
    }


@tool(
    "compare_candidates",
    "Run the deterministic Comparison Engine on the current search results. Returns a "
    "structured table of candidates with weighted scores under the user's priority. Call "
    "this BEFORE propose_cart so the engine's pre-LLM scoring is on the record and the "
    "agent's choice can be compared with the engine's. The engine output is then shown "
    "to the user as the 'why this option' rationale.",
    {"top_n": int},
)
async def compare_candidates(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    if session.intent is None:
        return {"content": [{"type": "text", "text": "Error: no signed intent."}]}
    if not session.candidates:
        return {
            "content": [
                {"type": "text", "text": "Error: no candidates. Call search_products first."}
            ]
        }
    top_n = max(2, int(args.get("top_n") or 5))
    report = build_comparison(session.intent, session.candidates, top_n=top_n)
    if report is None:
        return {"content": [{"type": "text", "text": "Comparison engine returned no report (empty candidates)."}]}
    session.comparison = report.model_dump()
    log_event(
        "agent",
        "agent.compare",
        f"Comparison engine: {len(report.candidates)} candidates, "
        f"engine_winner={report.engine_winner_id} (preset={session.intent.priority_preset or 'cheapest'})",
        {"comparison": session.comparison},
    )
    # Compact textual representation so the LLM can read and reason over it
    # without having to parse the full JSON.
    rows = []
    for c in report.candidates:
        flag = " <-- engine_top" if c.product_id == report.engine_winner_id else ""
        rating_str = f"{c.rating:.1f}" if c.rating is not None else "—"
        rows.append(
            f"  {c.product_id}  {c.title[:32]:<32}  {c.source_merchant:>8}  "
            f"${c.price_cents/100:6.2f}  rating={rating_str:>4}  rep={c.reputation_score}  "
            f"score={c.weighted_score:.3f}{flag}"
        )
    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Comparison ({len(report.candidates)} candidates, "
                    f"dims={report.dimensions_used}):\n" + "\n".join(rows) +
                    f"\nEngine winner: {report.engine_winner_id}"
                ),
            }
        ]
    }


@tool(
    "propose_cart",
    "Open a UCP checkout for the chosen product. Call this once you have decided which "
    "product best matches the user's intent. The PoC stops after this step (no Approve). "
    "Also accepts a brief `headline` (one sentence) explaining the choice — this becomes "
    "the agent's signed decision trace.",
    {"product_id": str, "qty": int, "headline": str},
)
async def propose_cart(args: dict[str, Any]) -> dict[str, Any]:
    session = _CURRENT["session"]
    if session.intent is None:
        return {"content": [{"type": "text", "text": "Error: no signed intent."}]}
    chosen = next((p for p in session.candidates if p["id"] == args["product_id"]), None)
    if chosen is None:
        return {
            "content": [
                {"type": "text", "text": f"Error: product_id {args['product_id']} not in last search results."}
            ]
        }
    session.selected = chosen
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{MERCHANT_URL}/ucp/checkout",
            json={
                "items": [{"product_id": args["product_id"], "qty": args.get("qty", 1)}],
                "buyer_email": session.form.get("buyer_email", "demo@example.com"),
                "intent_mandate": session.intent.model_dump(),
            },
        )
        if r.status_code != 200:
            err = f"merchant rejected: {r.status_code} {r.text}"
            session.error = err
            return {"content": [{"type": "text", "text": err}]}
        data = r.json()
    session.checkout_body = data["checkout"]
    session.merchant_authorization = data["merchant_authorization"]
    log_event(
        "agent",
        "agent.cart_ready",
        f"Cart ready: {session.checkout_body['id']} (${session.checkout_body['total_cents']/100:.2f})",
        {"checkout": session.checkout_body},
    )

    # 3rd PoC: if a comparison was run, build & sign the agent's decision
    # trace so audit logs show the agent committed to this choice with
    # a stated rationale. Engine vs agent divergence surfaces here.
    if session.comparison is not None:
        from services.shared.mandates import ComparisonReport
        report = ComparisonReport.model_validate(session.comparison)
        headline = (args.get("headline") or "").strip() or None
        try:
            trace = build_decision_trace(
                intent=session.intent,
                report=report,
                agent_winner_id=args["product_id"],
                headline=headline,
            )
            session.decision_trace = trace.model_dump()
            override = trace.agent_winner_id != trace.engine_winner_id
            log_event(
                "agent",
                "agent.rationale",
                ("Override: " if override else "Concur: ") + trace.headline,
                {"decision_trace": session.decision_trace},
            )
        except ValueError as e:
            # Agent picked something outside the comparison set; log but do
            # not block the cart (the merchant has already authorized it).
            log_event("agent", "agent.rationale_skipped", str(e))

    return {
        "content": [
            {
                "type": "text",
                "text": (
                    f"Cart {session.checkout_body['id']} created, total "
                    f"${session.checkout_body['total_cents']/100:.2f}. "
                    "Approval is disabled in this PoC — stop now."
                ),
            }
        ]
    }


SYSTEM_PROMPT = """\
You are an autonomous shopping agent operating under the AP2 Intent Mandate model.

The user's intent is already signed and known to you (item, price range, allowed merchants,
and a priority weighting like 'cheapest' / 'balanced' / 'trusted' / 'fastest').

You must follow this exact sequence:
  1. Call search_products at least once. If results are empty, retry with a broader
     refine_query (drop adjectives, keep the noun) up to 2 more times.
  2. Call compare_candidates(top_n=5). It runs a deterministic Comparison Engine and
     returns a table with price, rating, merchant reputation, and shipping for each
     candidate, plus a per-candidate weighted_score under the user's priority.
  3. Read the comparison table and pick ONE product. You may agree with the engine's
     top pick or override it — but you must base your decision on the fields shown.
     Do NOT invent numeric fields (rating, reputation, price). If a field is missing
     for a candidate, say so in your rationale rather than guessing.
  4. Call propose_cart(product_id=..., qty=1, headline=...). The `headline` is a
     single sentence (<=120 chars) summarizing why you chose this candidate; it will
     be persisted as the agent's signed decision trace and shown to the user.
  5. After propose_cart returns, STOP. Do NOT approve or finalize — the PoC stops at
     cart review.

Never invent products. Never call propose_cart with a product_id not in the comparison
report. If search returns zero matches even after broadening, say so and stop.
"""


async def _run(session: AgentSession) -> None:
    _CURRENT["session"] = session
    log_event("user", "form.submit", f"User submitted form via SDK agent", {"form": session.form})

    # Build & stub-sign the intent (same as mock agent).
    session.intent = build_intent_from_form(session.form)
    log_event(
        "user",
        "intent.built",
        f"Intent {session.intent.jti} signed via form",
        {"intent_mandate": session.intent.model_dump()},
    )

    server = create_sdk_mcp_server(
        name="ucp_ap2",
        version="0.3.0",
        tools=[search_products, compare_candidates, propose_cart],
    )
    intent_summary = (
        f"item_query={session.intent.item_query!r}, "
        f"price ${session.intent.price_range.from_cents/100:.0f}-"
        f"${session.intent.price_range.to_cents/100:.0f}, "
        f"merchants={session.intent.allowed_merchants}, "
        f"priority_preset={session.intent.priority_preset or 'cheapest (default)'}"
    )
    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT + f"\n\nThe user's intent: {intent_summary}.",
        mcp_servers={"ucp_ap2": server},
        allowed_tools=[
            "mcp__ucp_ap2__search_products",
            "mcp__ucp_ap2__compare_candidates",
            "mcp__ucp_ap2__propose_cart",
        ],
        max_turns=10,
    )

    try:
        async for msg in query(
            prompt=f"Find the best match for: {session.intent.item_query}",
            options=options,
        ):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        log_event("agent", "agent.thought", block.text.strip()[:240])
                    elif isinstance(block, ToolUseBlock):
                        log_event(
                            "agent",
                            "agent.tool_use",
                            f"calling {block.name}",
                            {"input": block.input},
                        )
    except Exception as e:
        session.error = str(e)
        log_event("agent", "agent.error", session.error)


def run_until_cart_form_sdk(
    form: dict[str, Any],
    anthropic_key: str | None = None,
    serpapi_key: str | None = None,
) -> AgentSession:
    """SDK-driven equivalent of `mock_agent.run_until_cart_form`.

    Two auth modes:
      - `anthropic_key` provided → call Anthropic API directly using that key.
        Costs are billed to the supplied key's account. Used in distributed
        deployments where each user brings their own credentials.
      - `anthropic_key` is None → fall back to the local `claude` CLI session
        (Claude Code). Used in personal/dev environments where the operator
        is already authenticated via `claude` on the host machine.

    `serpapi_key`: optional per-user SerpAPI key forwarded to the merchant.
    """
    session = AgentSession(form=form, serpapi_key=serpapi_key)

    old_key = os.environ.get("ANTHROPIC_API_KEY")
    if anthropic_key:
        os.environ["ANTHROPIC_API_KEY"] = anthropic_key
    else:
        # Make sure no stale ANTHROPIC_API_KEY interferes — we want the SDK
        # to spawn the `claude` CLI subprocess and use its session credentials.
        os.environ.pop("ANTHROPIC_API_KEY", None)

    try:
        asyncio.run(_run(session))
    finally:
        if old_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = old_key
        else:
            os.environ.pop("ANTHROPIC_API_KEY", None)
    return session
