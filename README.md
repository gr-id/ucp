# UCP + AP2 agentic commerce demo

Two PoCs in one repo, exploring Google's **Universal Commerce Protocol (UCP)**
and **Agent Payments Protocol (AP2)**:

- **1st PoC** — full 4-mandate signing chain (Intent → MerchantAuth →
  Checkout → Payment), ES256 JWS, in-memory mock catalog, ends with PSP
  approval. *Goal: prove the protocol mechanics work end-to-end.*
  → see git history (`git log --until 2026-05-21`) and `services/shared/crypto.py`.

- **2nd PoC** (current `main`) — structured shopping-intent form,
  **live UCP merchant products** (Walmart / Target / Wayfair / Etsy via SerpAPI),
  stops at the **cart-review screen before payment**. Stub signatures (assume
  user has signing capability on an external device).
  → see [`docs/2nd-poc.md`](docs/2nd-poc.md).

This README documents the **2nd PoC** (current state). For the original full
crypto chain, check the commit history.

```
[ Structured form ]                              [ Live UCP merchants ]
  ┌───────────────┐         ┌───────────┐         ┌─────────────────┐
  │ 구매할 물품    │         │           │         │ Walmart  Target │
  │ 가격 범위     │ Submit  │  Merchant │ search  │ Wayfair  Etsy   │
  │ 사이트 ☑☑☑☐  │ ──────▶ │   :8001   │ ──────▶ │ (via SerpAPI    │
  │ 유지 시간     │         │           │         │  Google Shopping)│
  │ 자동 구매 No  │         └───────────┘         └─────────────────┘
  └───────────────┘                                       │
                                                          ▼
                                              [ 1 product selected, ]
                                              [ stub-signed cart   ]
                                                          │
                                                          ▼
                                              [ Approve disabled — ]
                                              [ "결제 단계 비활성화" ]
```

## What's inside (2nd PoC)

| Path | Role |
| --- | --- |
| `services/merchant/main.py` | FastAPI UCP merchant on `:8001` — `/ucp/search`, `/ucp/checkout`. Enforces Intent constraints (price band, allowed merchants, expiry). |
| `services/merchant/catalog.py` | Catalog interface — `mock` (5 hardcoded) or `serpapi` (live Walmart/Target/Wayfair/Etsy). |
| `services/merchant/serpapi_client.py` | SerpAPI Google Shopping wrapper with 1-hour cache. |
| `services/shared/mandates.py` | Pydantic models — `IntentMandate`, `MerchantAuthorization`, `LineItem`, `StubSignature`. |
| `services/shared/intent.py` | `build_intent_from_form()` — validates the form and produces a stub-signed Intent. |
| `services/shared/stub_sig.py` | `stub_sign(signer, payload)` — placeholder for real device-side signing. |
| `services/shared/eventlog.py` | Append-only event log that drives the Protocol Inspector. |
| `agent/mock_agent.py` | Deterministic agent that picks the cheapest matching product. |
| `agent/sdk_agent.py` | Claude Agent SDK variant — Claude reads descriptions and selects the best semantic match. |
| `ui/app.py` | Streamlit two-pane UI — 5-field intent form (left) + Protocol Inspector (right). |
| `scripts/run_demo.py` | One command: merchant + Streamlit. |
| `scripts/smoke_2nd_poc.py` | Unit smoke (intent builder + mock + optional SerpAPI). |
| `scripts/smoke_e2e.py` | End-to-end smoke (form → cart). |
| `docs/2nd-poc.md` | Detailed scope, design choices, run instructions. |
| `services/psp/`, `services/shared/crypto.py`, `scripts/gen_keys.py` | 1st-PoC artifacts. Preserved but not used by the 2nd PoC. |

## Hosted demo (Streamlit Community Cloud)

Once deployed: <https://ucp-poc.streamlit.app> (or whatever URL you pick).

Setup details: [docs/streamlit-cloud-deploy.md](docs/streamlit-cloud-deploy.md)

The hosted demo runs Mock and Anthropic API agent modes. The "Claude Code (local session)" mode only works when you run the app locally (it requires the `claude` CLI on the host).

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (`winget install --id=astral-sh.uv` on Windows)
- For the Claude Agent SDK variant: Claude Code CLI installed and signed in
  (`npm i -g @anthropic-ai/claude-code`, then `claude` once to log in).
- Optional, for live merchant data: a free SerpAPI key (250 searches/month) —
  <https://serpapi.com/users/sign_up>.

## Quickstart — mock catalog (no external services needed)

```powershell
uv sync
uv run python scripts/run_demo.py
```

Open <http://localhost:8501>. Fill in the form (e.g. `running shoes` / $0–200 /
all merchants / 24 hours / No), click **Submit**, and watch the cart appear
with a merchant badge. The **Approve & sign** button is intentionally
disabled.

## Quickstart — live UCP merchant data (SerpAPI)

```powershell
$env:UCP_CATALOG_MODE = "serpapi"
$env:SERPAPI_KEY = "...your-key..."
uv run python scripts/run_demo.py
```

Same form, but the cart now shows a real product image, real price, and the
real source merchant (Walmart / Target / Wayfair / Etsy).

## Claude Agent SDK variant

```powershell
uv sync --group agent
$env:UCP_CATALOG_MODE = "serpapi"      # or "mock"
$env:SERPAPI_KEY = "..."
uv run --group agent python scripts/run_demo.py
```

Then choose **Claude Agent SDK** in the *Agent* dropdown. Claude reads the
product descriptions and picks the one that best matches your intent (e.g.
"marathon-ready" → prefers a carbon-plate runner over the cheapest match).

## Demo script (talking points for a 5-minute walkthrough)

1. **Show the architecture.** Three boxes — agent, merchant, PSP — connected by signed
   tokens. No one trusts each other; everyone verifies.
2. **Type the prompt.** The user is delegating shopping to an agent. The agent's first act
   is *not* to call the merchant — it's to sign an **Intent Mandate**, which bounds what it
   may buy (max $150, color white).
3. **Show the merchant_authorization in the inspector.** The merchant signed the cart body.
   The agent cannot tamper with line items or price without invalidating this signature.
4. **Click approve.** The user signs a **Checkout Mandate** that wraps *both* the merchant's
   signed body and the original intent. Any inconsistency — wrong price, missing intent,
   different cart — invalidates the chain.
5. **Open the PSP event.** The PSP verifies four signatures: Payment Mandate → Checkout
   Mandate → Merchant Authorization → Intent Mandate. The full audit trail of who
   authorized what is in one verifiable bundle.

## What this demo simplifies vs. the real specs

The UCP AP2 extension specifies SD-JWT+kb (Selective Disclosure JWT with key binding) for
the checkout mandate, and JWS Detached Content for `merchant_authorization`. For demo
clarity we use **plain compact JWS (ES256) everywhere** and bind via embedded fields and
`content_hash` rather than the SD-JWT format. The semantics — proof of who signed what,
and that the parts can be cross-validated — are equivalent for the demo's purpose.

We also:

- Use an in-memory product catalog (5 items), not a real merchant backend.
- Always authorize at the PSP (no risk model, no real money).
- Skip OAuth identity linking — the "user key" lives on disk next to the agent.
- Skip the SD-JWT selective disclosure flow.

These are called out as `TODO`/limitations rather than left implicit.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `claude` not found | CLI not installed | `npm i -g @anthropic-ai/claude-code`, then open a new shell |
| SDK error *"Claude Code returned an error result: success"* with `Not logged in` text | `claude` CLI not authenticated | Run `claude` in a terminal, `/login`, finish OAuth, then retry |
| `uv` not found right after install | Shell PATH hasn't refreshed | Open a new PowerShell window, or `$env:PATH = [System.Environment]::GetEnvironmentVariable('PATH','User') + ';' + [System.Environment]::GetEnvironmentVariable('PATH','Machine')` |
| Streamlit chat input disabled / not typeable | Stuck in `awaiting_approval` state from a previous run | Click **🔄 Reset demo** at the top right |
| Streamlit chat input missing entirely | Old script version cached | Hard reload (Ctrl-Shift-R), or restart `scripts/run_demo.py` |
| `ModuleNotFoundError: No module named 'services'` | Running a script without `sys.path` setup | Always use `uv run python scripts/...` from the project root |
| Demo prompt yields a T-shirt instead of shoes | Search was matching on `description`, not just `title`/`category` | Already fixed; re-pull the repo if you see this |
| `claude-agent-sdk` not installed | Optional group not synced | `uv sync --group agent` |

### Cost notes (Claude Agent SDK mode)

Each prompt in SDK mode consumes Claude Code subscription tokens. A typical
shopping interaction takes ~5–10 tool calls and costs roughly **$0.05–$0.20**.
The Mock agent has zero LLM cost and exercises the same protocol — use it for
repeat demos.

## References

- AP2 specification: <https://ap2-protocol.org/specification/>
- UCP specification: <https://ucp.dev/>
- UCP AP2 Mandates extension: <https://ucp.dev/specification/ap2-mandates/>
- UCP GitHub: <https://github.com/Universal-Commerce-Protocol/ucp>

## Repo layout

```
.
├── pyproject.toml
├── README.md
├── agent/
│   ├── mock_agent.py
│   └── sdk_agent.py
├── services/
│   ├── merchant/{main.py, catalog.py}
│   ├── psp/main.py
│   └── shared/{crypto.py, mandates.py, eventlog.py}
├── ui/app.py
├── scripts/{gen_keys.py, run_demo.py, smoke_crypto.py, smoke_e2e.py}
└── keys/   (generated, gitignored)
```
