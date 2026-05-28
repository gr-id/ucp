"""Streamlit UI for the 2nd PoC — structured shopping-intent form + cart preview.

Left:  structured form (5 fields = Intent Mandate body)
Right: protocol inspector (Mandate JSON + stub signatures)

The Approve button is intentionally disabled in this PoC. To reach actual
payment, real PG integration + signing infra are needed (see docs/2nd-poc.md).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --- Streamlit Cloud secrets bridge -----------------------------------------
# On Streamlit Cloud, secrets live in st.secrets (toml). Promote a few of
# them to os.environ so the merchant subprocess + serpapi_client inherit them.
# Locally, falling back to .env (loaded by run_demo.py / merchant/main.py).
def _promote_secrets() -> None:
    try:
        secrets = st.secrets  # raises if no secrets configured
    except Exception:
        return
    for key in ("SERPAPI_KEY", "UCP_CATALOG_MODE"):
        try:
            value = secrets.get(key)
        except Exception:
            value = None
        if value and not os.environ.get(key):
            os.environ[key] = str(value)


_promote_secrets()


# --- Embedded merchant subprocess ------------------------------------------
# In a hosted Streamlit deployment we have a single Python process. The
# merchant FastAPI service is started in-process via subprocess.Popen and
# cached so it survives Streamlit's script reruns. Locally, `run_demo.py`
# starts the merchant separately and this cached spawn is harmless (the port
# bind will fail and we just rely on the externally-running one).
MERCHANT_URL = "http://localhost:8001"


@st.cache_resource(show_spinner=False)
def _start_merchant_subprocess() -> dict:
    """Start the merchant FastAPI on 127.0.0.1:8001 if it isn't already up.

    Returns a small dict (cache_resource needs a return value). Idempotent.
    """
    # If something is already responding, do nothing.
    try:
        if httpx.get(f"{MERCHANT_URL}/healthz", timeout=0.5).status_code == 200:
            return {"started": False, "reason": "already-running"}
    except Exception:
        pass

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "services.merchant.main:app",
            "--host", "127.0.0.1",
            "--port", "8001",
            "--log-level", "warning",
        ],
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    # Wait briefly for readiness.
    for _ in range(30):
        try:
            if httpx.get(f"{MERCHANT_URL}/healthz", timeout=1).status_code == 200:
                return {"started": True, "pid": proc.pid}
        except Exception:
            pass
        time.sleep(0.5)
    return {"started": True, "pid": proc.pid, "warning": "merchant did not respond in 15s"}


_start_merchant_subprocess()


from agent.mock_agent import AgentSession, run_until_cart_form  # noqa: E402
from services.shared.eventlog import read_all, reset  # noqa: E402
from services.shared.intent import SUPPORTED_MERCHANTS, SUPPORTED_PRIORITIES  # noqa: E402
from services.shared.mandates import PRIORITY_PRESETS  # noqa: E402

st.set_page_config(page_title="UCP + AP2 — 3rd PoC", layout="wide", page_icon="🛒")


def services_up() -> bool:
    try:
        return httpx.get(f"{MERCHANT_URL}/healthz", timeout=0.5).status_code == 200
    except Exception:
        return False


def merchant_mode() -> str:
    try:
        return httpx.get(f"{MERCHANT_URL}/healthz", timeout=0.5).json().get("catalog_mode", "?")
    except Exception:
        return "?"


def cents(c: int) -> str:
    return f"${c / 100:,.2f}"


AGENT_MODES = [
    "Mock (deterministic)",
    "Claude Code (local session)",
    "Anthropic API (own key)",
]


def init_state() -> None:
    st.session_state.setdefault("session", None)
    st.session_state.setdefault("submitted", False)
    st.session_state.setdefault("agent_mode", AGENT_MODES[0])
    st.session_state.setdefault("merchants_selected", list(SUPPORTED_MERCHANTS))
    st.session_state.setdefault("user_serpapi_key", "")
    st.session_state.setdefault("user_anthropic_key", "")
    st.session_state.setdefault("priority_preset", "balanced")


def reset_demo() -> None:
    reset()
    st.session_state.session = None
    st.session_state.submitted = False


init_state()


# ===== HEADER =====
st.title("🛒 UCP + AP2 — 3rd PoC")
st.caption(
    "Structured shopping intent → multi-merchant comparison → signed agent rationale → cart preview. "
    "Payment step is intentionally disabled."
)

ok = services_up()
mode = merchant_mode() if ok else "?"
cols = st.columns([1.2, 1.2, 1.4, 0.9])
cols[0].metric("Merchant", "🟢 up" if ok else "🔴 down", help=MERCHANT_URL)
cols[1].metric("Catalog mode", mode, help="Set UCP_CATALOG_MODE env var to switch")
cols[2].selectbox(
    "Agent",
    AGENT_MODES,
    key="agent_mode",
    help=(
        "Mock: 결정론적, LLM 없음 (비용 0).\n"
        "Claude Code: 로컬 `claude` CLI 세션을 사용 (본인 환경 전용).\n"
        "Anthropic API: 사용자가 본인 키 입력 (배포 환경용)."
    ),
)
cols[3].button("🔄 Reset", on_click=reset_demo, use_container_width=True)

if not ok:
    st.error("Merchant 서비스가 응답하지 않습니다.\n\n`uv run python scripts/run_demo.py`")
    st.stop()

# ===== SIDEBAR: per-user API keys =====
with st.sidebar:
    st.markdown("### 🔑 내 API 키")
    st.caption(
        "키는 이 브라우저 세션에만 저장되고 어디에도 기록되지 않습니다. "
        "탭을 닫으면 사라집니다."
    )

    if mode == "serpapi":
        st.session_state.user_serpapi_key = st.text_input(
            "SerpAPI 키 (선택)",
            value=st.session_state.user_serpapi_key,
            type="password",
            help=(
                "비워두면 서버에 설정된 키를 사용합니다 (운영자 쿼터). "
                "본인 키를 입력하면 본인 쿼터로 호출됩니다. "
                "https://serpapi.com/users/sign_up — 무료 250/월."
            ),
            placeholder="serpapi 키 (선택)",
        )
        if st.session_state.user_serpapi_key:
            st.caption("✅ 본인 SerpAPI 키 사용")
        else:
            server_has_key = bool(os.environ.get("SERPAPI_KEY"))
            if server_has_key:
                st.caption("⚙️ 서버 키 사용 중")
            else:
                st.warning("서버·본인 키 모두 없음 — 검색 결과 없음")

    if st.session_state.agent_mode == "Anthropic API (own key)":
        st.session_state.user_anthropic_key = st.text_input(
            "Anthropic API 키 (필수)",
            value=st.session_state.user_anthropic_key,
            type="password",
            help=(
                "Anthropic API 모드에는 본인 키가 필요합니다. "
                "https://console.anthropic.com → API Keys. "
                "키는 호출 동안만 환경변수에 임시 적용된 뒤 즉시 복원됩니다."
            ),
            placeholder="sk-ant-...",
        )
        if not st.session_state.user_anthropic_key:
            st.warning("Anthropic API 모드는 본인 키 입력이 필수입니다.")
    elif st.session_state.agent_mode == "Claude Code (local session)":
        st.caption(
            "ℹ️ 서버 호스트의 `claude` CLI 로그인을 그대로 사용합니다. "
            "본인 로컬 환경에서만 작동하며, 배포 환경에서는 Anthropic API 모드를 쓰세요."
        )

    st.markdown("---")
    st.caption("Mock 모드는 LLM 비용 0. SerpAPI 키도 비워두면 서버 키로 검색.")


# ===== TWO-PANE LAYOUT =====
left, right = st.columns([1.0, 1.4], gap="large")


# ---------- LEFT: form + cart ----------
with left:
    st.subheader("1. 쇼핑 의도 입력")

    if not st.session_state.submitted:
        with st.form(key="intent_form"):
            item_query = st.text_input(
                "구매할 물품",
                placeholder="예: white running shoes",
                help="자유 텍스트. SerpAPI 모드에서는 Google Shopping 검색어로 사용됩니다.",
            )

            price_c1, price_c2 = st.columns(2)
            price_from = price_c1.number_input("최저가 (USD)", min_value=0, max_value=100000, value=0, step=5)
            price_to = price_c2.number_input("최고가 (USD)", min_value=1, max_value=100000, value=200, step=5)

            st.markdown("**쇼핑할 사이트** (UCP 라이브 머천트)")
            all_checked = all(m in st.session_state.merchants_selected for m in SUPPORTED_MERCHANTS)
            select_all = st.checkbox("전체 선택", value=all_checked, key="select_all_chk")

            if select_all and not all_checked:
                st.session_state.merchants_selected = list(SUPPORTED_MERCHANTS)
            elif not select_all and all_checked:
                # User just unchecked select-all from a fully-checked state
                st.session_state.merchants_selected = []

            merchant_cols = st.columns(len(SUPPORTED_MERCHANTS))
            selected: list[str] = []
            labels = {"walmart": "🟦 Walmart", "target": "🟥 Target", "wayfair": "🟧 Wayfair", "etsy": "🟫 Etsy"}
            for i, m in enumerate(SUPPORTED_MERCHANTS):
                default = m in st.session_state.merchants_selected
                if merchant_cols[i].checkbox(labels[m], value=default, key=f"chk_{m}"):
                    selected.append(m)

            valid_hours = st.number_input("유지 시간 (시간)", min_value=1, max_value=720, value=24, step=1,
                                          help="Intent Mandate 가 유효한 기간")

            priority_labels = {
                "cheapest": "💰 cheapest",
                "balanced": "⚖️ balanced",
                "trusted":  "🏆 trusted",
                "fastest":  "⚡ fastest",
            }
            current_default = st.session_state.get("priority_preset", "balanced")
            priority_preset = st.radio(
                "우선순위",
                list(SUPPORTED_PRIORITIES),
                index=list(SUPPORTED_PRIORITIES).index(current_default),
                format_func=lambda p: priority_labels.get(p, p),
                horizontal=True,
                help=(
                    "에이전트가 후보를 비교할 때 쓸 가중치 프리셋.\n"
                    "이 선택은 Intent Mandate의 payload_hash 에 포함되어 서명됩니다 — 변경하면 새 mandate."
                ),
            )
            # Caption: show the expanded weights vector under the selected preset.
            _w = PRIORITY_PRESETS[priority_preset]
            st.caption(
                f"가중치: price={_w.price:.2f}  trust={_w.trust:.2f}  "
                f"rating={_w.rating:.2f}  shipping={_w.shipping:.2f}"
            )

            auto_purchase = st.radio(
                "자동 구매 허용",
                ["No", "Yes"],
                horizontal=True,
                help="이 PoC는 옵션 표시만 제공 — 항상 manual approval 단계에서 멈춥니다.",
            )

            submitted = st.form_submit_button("🚀 Submit", type="primary", use_container_width=True)

        if submitted:
            st.session_state.merchants_selected = selected
            st.session_state.priority_preset = priority_preset
            reset()
            form_data = {
                "item_query": item_query,
                "price_from_cents": int(price_from) * 100,
                "price_to_cents": int(price_to) * 100,
                "allowed_merchants": selected,
                "valid_hours": int(valid_hours),
                "auto_purchase": (auto_purchase == "Yes"),
                "priority_preset": priority_preset,
                "buyer_email": "demo@example.com",
            }
            serpapi_key = st.session_state.user_serpapi_key.strip() or None
            anthropic_key = st.session_state.user_anthropic_key.strip() or None
            mode = st.session_state.agent_mode

            # Validation specific to Anthropic API mode.
            if mode == "Anthropic API (own key)" and not anthropic_key:
                st.session_state.session = None
                st.session_state.submitted = False
                st.error("좌측 사이드바에 Anthropic API 키를 입력해주세요.")
                st.stop()

            with st.spinner("Building intent + searching live merchants…"):
                if mode == "Mock (deterministic)":
                    session: AgentSession = run_until_cart_form(form_data, serpapi_key=serpapi_key)
                elif mode == "Claude Code (local session)":
                    from agent.sdk_agent import run_until_cart_form_sdk
                    session = run_until_cart_form_sdk(
                        form_data,
                        anthropic_key=None,           # use local claude CLI
                        serpapi_key=serpapi_key,
                    )
                else:  # "Anthropic API (own key)"
                    from agent.sdk_agent import run_until_cart_form_sdk
                    session = run_until_cart_form_sdk(
                        form_data,
                        anthropic_key=anthropic_key,
                        serpapi_key=serpapi_key,
                    )
            st.session_state.session = session
            st.session_state.submitted = True
            st.rerun()
    else:
        session: AgentSession = st.session_state.session
        if session is None:
            st.warning("세션이 없습니다. 다시 시도해주세요.")
        else:
            st.markdown("##### Intent 요약")
            if session.intent is not None:
                intent_box = st.container(border=True)
                with intent_box:
                    preset_label = session.intent.priority_preset or "—"
                    st.markdown(
                        f"**물품:** {session.intent.item_query}  \n"
                        f"**가격대:** {cents(session.intent.price_range.from_cents)} – "
                        f"{cents(session.intent.price_range.to_cents)}  \n"
                        f"**머천트:** {', '.join(session.intent.allowed_merchants)}  \n"
                        f"**우선순위:** `{preset_label}`  \n"
                        f"**자동 구매:** {'Yes' if session.intent.auto_purchase else 'No'}  \n"
                        f"<small><code>mandate hash: {session.intent.signature.payload_hash}</code></small>",
                        unsafe_allow_html=True,
                    )

            # 3rd-PoC: comparison + signed agent decision trace (SDK mode only).
            if session.comparison:
                st.markdown("##### 2. Agent 비교 결과")
                comp = session.comparison
                rows = []
                for c in comp["candidates"]:
                    is_engine = c["product_id"] == comp["engine_winner_id"]
                    is_agent = (
                        session.decision_trace
                        and c["product_id"] == session.decision_trace.get("agent_winner_id")
                    )
                    pick = ""
                    if is_engine and is_agent:
                        pick = "✅ engine + agent"
                    elif is_engine:
                        pick = "📊 engine top"
                    elif is_agent:
                        pick = "🤖 agent override"
                    rows.append({
                        "pick": pick,
                        "merchant": c["source_merchant"],
                        "title": c["title"][:38],
                        "price": f"${c['price_cents']/100:.2f}",
                        "rating": (f"{c['rating']:.1f}" if c.get("rating") is not None else "—"),
                        "reviews": c.get("reviews_count") or "—",
                        "reputation": c["reputation_score"],
                        "shipping": c["shipping_note"][:24],
                        "score": round(c["weighted_score"], 3),
                    })
                st.dataframe(rows, hide_index=True, use_container_width=True)
                st.caption(
                    f"dimensions: {' · '.join(comp['dimensions_used'])} "
                    "(reputation/shipping는 demo 정적 레지스트리)"
                )

                if session.decision_trace:
                    dt = session.decision_trace
                    override = dt["agent_winner_id"] != dt["engine_winner_id"]
                    badge = "🤖 OVERRIDE" if override else "✅ CONCUR"
                    trace_box = st.container(border=True)
                    with trace_box:
                        st.markdown(f"**{badge}** — {dt['headline']}")
                        st.markdown(
                            f"<small>우선순위 적용: {dt['priority_explanation']}</small>",
                            unsafe_allow_html=True,
                        )
                        if dt.get("dropped_dimensions"):
                            st.markdown(
                                f"<small>⚠️ 데이터 부족으로 무시된 차원: "
                                f"{', '.join(dt['dropped_dimensions'])}</small>",
                                unsafe_allow_html=True,
                            )
                        st.markdown(
                            f"<small><code>decision_trace signer={dt['signature']['signer']} "
                            f"hash={dt['signature']['payload_hash']}</code></small>",
                            unsafe_allow_html=True,
                        )
                        with st.expander("후보별 trade-off"):
                            for row in dt["tradeoffs"]:
                                head = f"`{row['product_id']}`"
                                if row.get("why_not_chosen") is None:
                                    head += " — **선택됨**"
                                else:
                                    head += f" — {row['why_not_chosen']}"
                                st.markdown(head)
                                if row.get("relative_strengths"):
                                    st.markdown(
                                        f"  &nbsp;&nbsp;➕ {', '.join(row['relative_strengths'])}",
                                        unsafe_allow_html=True,
                                    )
                                if row.get("relative_weaknesses"):
                                    st.markdown(
                                        f"  &nbsp;&nbsp;➖ {', '.join(row['relative_weaknesses'])}",
                                        unsafe_allow_html=True,
                                    )
            else:
                # Mock agent does not produce a comparison report. Surface the
                # contrast explicitly so the demo shows what SDK adds.
                if session.intent is not None and session.selected is not None:
                    st.info(
                        "ℹ️ Mock 에이전트는 단순히 최저가 후보를 고릅니다. "
                        "SDK 에이전트(Claude Code / Anthropic API)는 동일 검색 결과를 "
                        "Comparison Engine 으로 점수화하고, 서명된 의사결정 근거를 남깁니다."
                    )

            st.markdown("##### 3. 카트")
            if session.error:
                st.error(session.error)
            elif session.selected is None:
                st.info(
                    f"선택한 머천트({', '.join(session.intent.allowed_merchants) if session.intent else ''})에서 "
                    f"조건에 맞는 상품을 찾지 못했습니다. 가격 범위 또는 머천트 선택을 넓혀보세요."
                )
            else:
                p = session.selected
                cart_box = st.container(border=True)
                with cart_box:
                    img_col, info_col = st.columns([1, 2])
                    if p.get("image_url"):
                        img_col.image(p["image_url"], use_container_width=True)
                    else:
                        img_col.markdown("🖼️ _(이미지 없음)_")
                    badge = p.get("source_merchant", "").upper()
                    info_col.markdown(f"`{badge}` **{p['title']}**")
                    info_col.markdown(f"{cents(p['price_cents'])}  ·  {p.get('brand','')}")
                    if p.get("description"):
                        info_col.markdown(f"<small>{p['description'][:200]}</small>", unsafe_allow_html=True)
                    if p.get("product_url"):
                        info_col.markdown(f"[원본 상품 페이지 ↗]({p['product_url']})")

                if session.checkout_body:
                    cb = session.checkout_body
                    st.markdown(
                        f"**Subtotal** {cents(cb['subtotal_cents'])}  ·  "
                        f"**Tax** {cents(cb['tax_cents'])}  ·  "
                        f"**Total** {cents(cb['total_cents'])}"
                    )

                st.warning(
                    "**결제 단계 비활성화** — 이 PoC는 카트 검토까지만 보여줍니다. "
                    "실제 PSP 호출 없음, Approve 버튼은 비활성 상태입니다."
                )
                btn_c1, btn_c2 = st.columns(2)
                btn_c1.button("✅ Approve & sign", disabled=True, use_container_width=True,
                              help="결제 단계는 비활성화. 실제 시스템에서는 사용자가 외부 단말로 Checkout Mandate에 서명.")
                btn_c2.button("❌ Decline / 다시", on_click=reset_demo, use_container_width=True)


# ---------- RIGHT: protocol inspector ----------
with right:
    st.subheader("Protocol inspector")
    events = read_all()
    if not events:
        st.caption("이벤트 없음. 좌측 폼을 작성하고 Submit 하세요.")
    else:
        actor_icon = {"user": "👤", "agent": "🤖", "merchant": "🏪", "psp": "💳"}
        for ev in events:
            icon = actor_icon.get(ev["actor"], "•")
            with st.expander(
                f"{icon} **{ev['actor']}** · `{ev['kind']}` — {ev['summary']}",
                expanded=False,
            ):
                detail = ev.get("detail") or {}
                if detail:
                    st.json(detail)
