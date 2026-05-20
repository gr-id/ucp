"""Streamlit demo UI: chat (left) + protocol inspector (right).

Shows the UCP+AP2 flow visually so you can present:
  - what the user says
  - what the agent decides
  - which mandate is signed at each step (with JWS decoded)
  - the final PSP authorization

Requires the merchant (:8001) and PSP (:8002) services to be running.
Use `uv run python scripts/run_demo.py` to launch everything at once.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.mock_agent import AgentSession, finalize, run_until_cart  # noqa: E402
from services.shared.crypto import decode_unverified  # noqa: E402
from services.shared.eventlog import read_all, reset  # noqa: E402

st.set_page_config(page_title="UCP + AP2 demo", layout="wide", page_icon="🛒")

MERCHANT_URL = "http://localhost:8001"
PSP_URL = "http://localhost:8002"


# ---------- helpers ----------


def services_up() -> tuple[bool, bool]:
    def up(url: str) -> bool:
        try:
            return httpx.get(f"{url}/healthz", timeout=0.5).status_code == 200
        except Exception:
            return False

    return up(MERCHANT_URL), up(PSP_URL)


def cents(c: int) -> str:
    return f"${c / 100:,.2f}"


# ---------- session state ----------


def init_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session" not in st.session_state:
        st.session_state.session = None
    if "stage" not in st.session_state:
        st.session_state.stage = "idle"  # idle | awaiting_approval | completed


def reset_demo() -> None:
    reset()
    st.session_state.messages = []
    st.session_state.session = None
    st.session_state.stage = "idle"


init_state()


# ---------- header ----------

st.title("🛒 UCP + AP2 agentic commerce demo")
st.caption(
    "Watch an AI agent shop on your behalf — every step is cryptographically signed "
    "by the user, the merchant, and verified end-to-end by the PSP."
)

merchant_ok, psp_ok = services_up()
status_cols = st.columns(4)
status_cols[0].metric("Merchant (UCP)", "🟢 up" if merchant_ok else "🔴 down", help=MERCHANT_URL)
status_cols[1].metric("PSP (AP2)", "🟢 up" if psp_ok else "🔴 down", help=PSP_URL)
agent_mode = status_cols[2].selectbox(
    "Agent",
    ["Mock (deterministic)", "Claude Agent SDK"],
    help="Mock uses a hardcoded flow. SDK lets Claude decide search params and product choice via MCP tools.",
)
status_cols[3].button("🔄 Reset demo", on_click=reset_demo, use_container_width=True)

if not (merchant_ok and psp_ok):
    st.error(
        "Services not reachable. Start them with:\n\n"
        "```\nuv run python scripts/run_demo.py\n```"
    )
    st.stop()


# ---------- two-pane layout ----------

left, right = st.columns([1.1, 1.4], gap="large")


# === LEFT: chat ===
with left:
    st.subheader("Chat")
    chat_box = st.container(height=540, border=True)

    with chat_box:
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if "cart" in msg:
                    cart = msg["cart"]
                    for li in cart["line_items"]:
                        st.markdown(f"- **{li['title']}** × {li['qty']} — {cents(li['unit_price_cents'])}")
                    st.markdown(
                        f"Subtotal: {cents(cart['subtotal_cents'])}  ·  "
                        f"Tax: {cents(cart['tax_cents'])}  ·  "
                        f"**Total: {cents(cart['total_cents'])}**"
                    )
                if "txn" in msg:
                    st.success(
                        f"Transaction **{msg['txn']['transaction_id']}** authorized for "
                        f"{cents(msg['txn']['amount_cents'])}"
                    )

        if st.session_state.stage == "awaiting_approval":
            st.info("Cart is ready. Approve to sign the Checkout Mandate and finalize payment.")
            cols = st.columns(2)
            if cols[0].button("✅ Approve & sign", type="primary", use_container_width=True):
                with st.spinner("Signing Checkout + Payment Mandates…"):
                    finalize(st.session_state.session)
                txn = st.session_state.session.psp_result
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "Done. The PSP verified the full mandate chain and authorized the charge.",
                        "txn": txn,
                    }
                )
                st.session_state.stage = "completed"
                st.rerun()
            if cols[1].button("❌ Decline", use_container_width=True):
                st.session_state.messages.append(
                    {"role": "assistant", "content": "Purchase declined by user. No payment mandate was signed."}
                )
                st.session_state.stage = "completed"
                st.rerun()

# === RIGHT: protocol inspector ===
with right:
    st.subheader("Protocol inspector")
    events = read_all()
    if not events:
        st.caption("No protocol events yet. Send a message in the chat to start.")
    else:
        actor_icon = {"user": "👤", "agent": "🤖", "merchant": "🏪", "psp": "💳"}
        for i, ev in enumerate(events):
            icon = actor_icon.get(ev["actor"], "•")
            with st.expander(f"{icon} **{ev['actor']}** · `{ev['kind']}` — {ev['summary']}", expanded=False):
                detail = ev.get("detail") or {}

                # Find any JWS-looking strings and decode them.
                jws_fields = {k: v for k, v in detail.items() if k.endswith("_jws") and isinstance(v, str)}
                if jws_fields:
                    for k, tok in jws_fields.items():
                        st.markdown(f"**{k}** (decoded)")
                        try:
                            decoded = decode_unverified(tok)
                            st.json(decoded)
                        except Exception as e:
                            st.warning(f"Could not decode: {e}")
                        st.code(tok, language=None)

                other = {k: v for k, v in detail.items() if k not in jws_fields}
                if other:
                    st.markdown("**Other detail**")
                    st.json(other)


# === chat input — at page root so Streamlit can pin it to the bottom ===
# Only disable while there's an actual cart awaiting approval; otherwise stale
# state could lock the user out.
awaiting_real_cart = (
    st.session_state.stage == "awaiting_approval"
    and st.session_state.session is not None
    and st.session_state.session.checkout_body is not None
)
prompt = st.chat_input(
    "Try: 'Find me white running shoes under $150 and buy them.'",
    disabled=awaiting_real_cart,
)
if prompt:
    reset()  # clear protocol log for this run
    st.session_state.messages = [{"role": "user", "content": prompt}]
    with st.spinner("Agent is shopping…"):
        if agent_mode.startswith("Claude"):
            from agent.sdk_agent import run_until_cart_sdk

            session: AgentSession = run_until_cart_sdk(prompt)
        else:
            session = run_until_cart(prompt)
    st.session_state.session = session
    if session.selected is None:
        st.session_state.messages.append(
            {"role": "assistant", "content": "No products matched your constraints."}
        )
        st.session_state.stage = "completed"
    else:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    f"I found **{session.selected['title']}** "
                    f"({cents(session.selected['price_cents'])}). "
                    f"Here's your cart — please approve to proceed."
                ),
                "cart": session.checkout_body,
            }
        )
        st.session_state.stage = "awaiting_approval"
    st.rerun()
