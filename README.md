# UCP + AP2 agentic commerce demo

A presentation-grade demo of an AI shopping agent buying on a user's behalf,
using Google's **Universal Commerce Protocol (UCP)** to interact with the merchant
and **Agent Payments Protocol (AP2)** to authorize the payment.

The whole purchase chain is cryptographically signed and verified end-to-end:

```
  User                     Agent                  Merchant (UCP)         PSP
   |                         |                         |                  |
   | "buy white runners      |                         |                  |
   |  under $150"            |                         |                  |
   |───── prompt ────────────▶|                        |                  |
   |        sign IntentMandate (ES256)                 |                  |
   |                         |── /ucp/search ─────────▶|                  |
   |                         |◀────── products ────────|                  |
   |                         |── /ucp/checkout ───────▶|                  |
   |                         |     +intent_mandate     |                  |
   |                         |◀── checkout +           |                  |
   |                         |     merchant_authz JWS  |                  |
   |◀── cart for approval ───|                         |                  |
   |── ✅ approve ────────────▶|                        |                  |
   |        sign CheckoutMandate (embeds merchant_authz + intent)         |
   |                         |── /ucp/checkout/.../complete ─▶            |
   |                         |◀───── completed ────────|                  |
   |        sign PaymentMandate (embeds CheckoutMandate)                  |
   |                         |───────────── /psp/charge ─────────────────▶|
   |                         |               PSP verifies full chain ✅   |
   |                         |◀──────── txn authorized ───────────────────|
```

## What's inside

| Path | Role |
| --- | --- |
| `services/merchant/` | FastAPI UCP merchant on `:8001` — search, checkout, complete. Signs `merchant_authorization`, enforces intent constraints. |
| `services/psp/` | FastAPI Payment Service Provider on `:8002` — verifies the full Mandate chain and authorizes the charge. |
| `services/shared/crypto.py` | ES256 JWS sign/verify + RFC 8785 JSON Canonicalization (JCS). |
| `services/shared/mandates.py` | Pydantic models for Intent / Merchant Authorization / Checkout / Payment Mandates. |
| `services/shared/eventlog.py` | Append-only event log all services share — drives the Protocol Inspector. |
| `agent/mock_agent.py` | Deterministic agent that drives the flow without an LLM. |
| `agent/sdk_agent.py` | Claude Agent SDK variant — Claude picks the product via MCP tools. |
| `ui/app.py` | Streamlit two-pane demo: chat (left) + protocol inspector with JWS decode (right). |
| `scripts/gen_keys.py` | Generate ES256 keypairs for user / merchant / PSP. |
| `scripts/run_demo.py` | One command that starts merchant + PSP + Streamlit. |
| `scripts/smoke_*.py` | Quick checks: crypto round-trip, end-to-end purchase. |

## Prerequisites

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) (`winget install --id=astral-sh.uv` on Windows)
- For the Claude Agent SDK variant: Claude Code CLI installed and signed in
  (`npm i -g @anthropic-ai/claude-code`, then `claude` once to log in).

## Quickstart

```powershell
uv sync                                # install runtime deps
uv run python scripts/gen_keys.py      # one-time: generate ES256 keypairs
uv run python scripts/run_demo.py      # start merchant + PSP + Streamlit
```

Open <http://localhost:8501>. Try:

> *Find me white running shoes under $150 and buy them.*

For the Claude Agent SDK variant:

```powershell
uv sync --group agent
uv run --group agent python scripts/run_demo.py
```

Then choose **Claude Agent SDK** in the *Agent* dropdown before sending a prompt.

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
