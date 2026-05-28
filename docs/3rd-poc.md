# 3rd PoC — Multi-Merchant Comparison + Signed Agent Rationale

## What this adds on top of PoC2

PoC2 ended at "merchant authorization issued, cart shown, Approve disabled."
The agent picked one candidate (cheapest, or LLM-semantic match) and the user
saw a single product. Nothing surfaced *why* that product over others, and the
agent's reasoning was free-text in the log at best.

PoC3 inserts a **Comparison Engine** between search and checkout. The user
expresses a **priority preset** (`cheapest` / `balanced` / `trusted` /
`fastest`) which is signed into the IntentMandate. The agent then sees a
deterministic per-candidate scorecard, picks one, and emits a **signed
`AgentDecisionTrace`** explaining the trade-off. The trace is a first-class
mandate-chain object — the agent puts its name on its choice.

## What gets signed by whom

| Object                  | Signer     | Carries                                                |
| ----------------------- | ---------- | ------------------------------------------------------ |
| `IntentMandate`         | `user`     | item query, price band, merchants, expiry, **priority**|
| `ComparisonReport`      | (unsigned) | engine-side scorecard, deterministic                   |
| `MerchantAuthorization` | `merchant` | the checkout body the merchant will honor              |
| `AgentDecisionTrace`    | `agent`    | the chosen candidate, headline, per-candidate tradeoffs|

`StubSignature.signer` is extended to include `"agent"`. The `agent` signer is
the audit-trail wedge: a future-payment-mandate dispute can resolve "did the
agent commit to this choice" without having to replay the full conversation.

## The four priority presets

| Preset    | price | trust | rating | shipping | When to use                                   |
| --------- | ----- | ----- | ------ | -------- | --------------------------------------------- |
| cheapest  | 1.00  | 0.00  | 0.00   | 0.00     | PoC2-compatible; mandate carries the preset   |
| balanced  | 0.40  | 0.25  | 0.25   | 0.10     | Default: no single dimension dominates        |
| trusted   | 0.20  | 0.50  | 0.25   | 0.05     | Repeat-buy items where merchant matters       |
| fastest   | 0.25  | 0.20  | 0.15   | 0.40     | Time-pressure purchases (e.g. weekend race)   |

Weights are expanded at intent-build time and **signed into the mandate's
`payload_hash`**, so changing the preset changes the mandate. The smoke test
asserts this.

## Why the engine is pure Python

The Comparison Engine never asks the LLM to invent numeric fields. It pulls
price/rating/reviews from the catalog and pulls reputation/shipping from a
static demo registry (`services.shared.reputation`). `dimensions_used` in the
report explicitly labels each field's source so the UI can mark the static
ones — e.g. `reputation(source=static_demo_registry)`.

The agent's only judgment task is: read the table, pick a row, write a
one-sentence headline.

## Engine winner vs Agent winner

The agent may agree with or override the engine. We do not hide this — the UI
shows `📊 engine top` on the engine's pick and `🤖 agent override` on the
agent's pick when they differ. The decision trace's `headline` uses an
"Override" / "Concur" prefix in the auto-generated case.

## Mock vs SDK contrast (deliberate)

Mock agent: cheapest-only, `session.comparison = None`,
`session.decision_trace = None`. UI shows an info box explaining the contrast.

SDK agent (Claude Code / Anthropic API): runs
`search_products → compare_candidates → propose_cart(headline=...)`. UI shows
the full table + signed decision trace.

This is the demo's punchline: same UI, same intent, but only the agentic path
produces a signed rationale.

## Files added or changed

- `services/shared/mandates.py` — `PriorityWeights`, `priority`/`priority_preset` on
  `IntentMandate`, new `CandidateScore` / `ComparisonReport` / `TradeoffRow` /
  `AgentDecisionTrace`. `StubSignature.signer` now also accepts `"agent"`.
- `services/shared/intent.py` — preset → weights expansion, priority signed
  into `payload_hash`.
- `services/shared/reputation.py` *(new)* — static_demo_registry of trust
  and shipping per merchant slug.
- `services/shared/comparison.py` *(new)* — deterministic engine +
  `build_decision_trace()` helper that signs the trace.
- `services/merchant/catalog.py` — mock products gain `rating`/`reviews_count`;
  search results are enriched with reputation/shipping fields. Mock data is
  tuned so `cheapest` and `trusted` pick different winners.
- `agent/sdk_agent.py` — new `compare_candidates` MCP tool, propose_cart
  builds & signs `AgentDecisionTrace`, updated system prompt mandates the
  sequence.
- `agent/mock_agent.py` — session fields for `comparison`/`decision_trace`,
  left `None` to preserve the visual contrast.
- `ui/app.py` — priority radio in the form, comparison dataframe + decision
  trace card above the cart, mandate hash visible on the intent summary.
- `scripts/smoke_3rd_poc.py` *(new)* — five assertions covering priority
  hashing, legacy backcompat, engine shape, preset divergence, and trace
  round-trip.

## Limitations carried forward from PoC2

- Cart/Payment Mandate not implemented; Approve still disabled.
- StubSignature in place of real ES256; the 1st PoC commit history holds the
  reference real-signing implementation.
- Reputation/shipping are demo data, **not** real merchant metrics — the UI
  marks them as such (`source=static_demo_registry`).
- Replay protection (nonce) still absent.

## Limitations specific to PoC3

- The agent can write any `headline` it wants. The trace doesn't enforce that
  the headline references the chosen candidate's actual attributes — only
  that the candidate exists in the comparison report.
- SerpAPI doesn't reliably return `rating` for every product; the engine
  drops the dimension for affected candidates and reports it in
  `dropped_dimensions`. The agent is instructed not to impute.
- The preset → weights mapping is hardcoded. A future PoC could let the user
  edit the weights vector directly (it's already signed in the mandate).

## Running the demo

```bash
# Mock catalog (no SerpAPI key needed)
UCP_CATALOG_MODE=mock uv run python scripts/run_demo.py

# Smoke test (no LLM, no network)
uv run python scripts/smoke_3rd_poc.py
```

In the UI: pick `Mock (deterministic)` to see the cheapest-only baseline,
then switch to `Claude Code (local session)` or `Anthropic API (own key)`
and re-submit the same form to see the comparison table + signed trace.
Flip the priority preset between submissions to see the engine winner
move from Walmart's $99 Cloudstride to Target's $119 Pacelane.
