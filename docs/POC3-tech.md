# POC3 — 기술적 관점 분석

> 다중 머천트 비교 + 서명된 Agent Rationale 의 **프로토콜 / 코드 / 검증** 측면 분석. 사업적 관점은 [POC3-business.md](POC3-business.md).

| 항목 | 값 |
|---|---|
| Status | POC3 구현 완료 |
| 마지막 업데이트 | 2026-05-27 |
| 스택 | Python 3.11, FastAPI, Streamlit, Pydantic, Claude Agent SDK |
| 변경 mandate 수 | IntentMandate (확장) + AgentDecisionTrace (신규) |
| 신규 모듈 | `services/shared/{reputation,comparison}.py` |
| 테스트 | `scripts/smoke_3rd_poc.py` — 5/5 통과 + POC2 smoke 무회귀 |

---

## TL;DR (기술)

- `IntentMandate` 에 **Optional `priority_preset` + `priority` (PriorityWeights)** 추가. 두 필드 모두 **`payload_hash` 산출 대상**에 포함되어 mandate 무결성 보장
- `services/shared/comparison.py` — **순수 Python 결정론 엔진**. 가격·rating·평판·배송 4차원 정규화 + 가중치 평균 + tiebreak (`max(score, -price)`). LLM 은 점수 계산에 관여하지 않음
- `AgentDecisionTrace` 신규 — `signer="agent"` 로 서명. `StubSignature.signer` Literal 확장이 유일한 호환 변경점
- SDK 에이전트 MCP 툴 시퀀스: `search_products` → **`compare_candidates(top_n)`** → `propose_cart(product_id, qty, headline)`. SYSTEM_PROMPT 가 순서를 강제
- `dimensions_used` 에 **데이터 출처 라벨**(`reputation(source=static_demo_registry)`) 부착 — LLM 의 환각 영역과 데모 stub 영역을 코드 레벨에서 분리
- 모든 변경은 **하위호환** — `priority` 가 없는 POC2 형태의 Intent 도 그대로 통과 (smoke 가 검증)

## 변경 표면 (코드 차원)

| 종류 | 파일 | 핵심 변경 |
|---|---|---|
| 수정 | `services/shared/mandates.py` | `StubSignature.signer` 에 `"agent"` 추가, `PriorityWeights` / `PRIORITY_PRESETS` / `IntentMandate.priority{,_preset}` / `CandidateScore` / `ComparisonReport` / `TradeoffRow` / `AgentDecisionTrace` 모델 |
| 수정 | `services/shared/intent.py` | preset → weights 확장, **priority 를 `body_for_hash` 에 포함**, `SUPPORTED_PRIORITIES` 노출 |
| 수정 | `services/merchant/catalog.py` | mock 상품에 `rating`/`reviews_count` 추가 (preset 별 분기 가능하도록 가격·평점 튜닝), `_enrich()` 헬퍼로 검색 결과에 reputation/shipping 부착 |
| 수정 | `agent/sdk_agent.py` | `compare_candidates` 신규 MCP 툴, `propose_cart` 가 `AgentDecisionTrace` 빌드·서명, SYSTEM_PROMPT 가 4단계 시퀀스 강제, MCP 서버 버전 0.2.0 → 0.3.0 |
| 수정 | `agent/mock_agent.py` | `AgentSession` 에 `comparison`/`decision_trace` 필드만 추가. **로직은 그대로 — cheapest 만 고름.** Mock vs SDK 의 시각적 대비를 위해 의도적으로 `None` 유지 |
| 수정 | `ui/app.py` | priority 라디오, 비교표(`st.dataframe`), 서명된 trace 카드, mandate hash 노출, Mock 안내 박스 |
| **신규** | `services/shared/reputation.py` | 4개 머천트 정적 trust/shipping. `SOURCE_TAG = "static_demo_registry"` 명시 |
| **신규** | `services/shared/comparison.py` | `build_comparison()`, `build_decision_trace()`. 환각 방지 + 결정론 보장 |
| **신규** | `scripts/smoke_3rd_poc.py` | 5개 invariant 테스트 |
| **신규** | `docs/3rd-poc.md` | 설계 메모 (영어) |

## Comparison Engine 알고리즘

```python
# services/shared/comparison.py — 요약 의사코드
def build_comparison(intent, products, top_n=5):
    weights = intent.priority or PRESETS[intent.priority_preset or "cheapest"]
    candidates = sorted(products, key=price)[:top_n]
    lo, hi = min(prices), max(prices)

    for c in candidates:
        norm = {
            "price":     1 - (c.price - lo) / (hi - lo),          # 실측
            "rating":    c.rating / 5.0 if c.rating else None,    # 실측 (없을 수 있음)
            "reputation": reputation_score(c.merchant) / 100,     # static_demo_registry
            "shipping":  1 - (shipping_days(c.merchant) / 14),    # static_demo_registry
        }
        # 누락된 차원은 가중치에서 제외하고 활성 차원만으로 재정규화
        active = [(d, n, w) for d, (n, w) in zip(norm, weights) if n is not None]
        score = sum(n * w for _, n, w in active) / sum(w for _, _, w in active)

    winner = argmax(score, tiebreak=-price)
```

**설계상의 핵심 4가지:**

1. **데이터 출처 분리**: `price` / `rating` 은 catalog 실측, `reputation` / `shipping` 은 static_demo_registry. 둘이 섞이지 않게 `dimensions_used` 에 출처 라벨 부착
2. **결손 차원의 fair 처리**: rating 이 없는 후보를 0점 처리하지 않고, 해당 후보에만 한해 rating 가중치를 빼고 나머지 차원으로 재정규화 → 결손이 페널티가 되지 않음
3. **결정론**: 같은 입력 = 같은 출력. smoke 테스트가 이를 검증 (`test_comparison_engine_shape`, `test_priority_swap_changes_winner`)
4. **tiebreak**: `(score, -price)` 사전식 비교 — 동점일 때 더 싼 후보가 이김. 우연성 제거

## AgentDecisionTrace 설계

```python
class AgentDecisionTrace(BaseModel):
    intent_jti: str
    engine_winner_id: str         # 엔진이 골랐을 후보
    agent_winner_id: str          # 에이전트가 실제로 고른 후보
    headline: str                 # 자유 텍스트 (LLM 또는 자동 생성)
    tradeoffs: list[TradeoffRow]  # 후보별 strengths/weaknesses/why_not_chosen
    priority_explanation: str     # preset → 의미 풀이
    dropped_dimensions: list[str] # 데이터 부족으로 무시된 차원
    signature: StubSignature      # signer="agent"
```

**서명 대상 (`body_for_hash`)**: `intent_jti`, `engine_winner_id`, `agent_winner_id`, `headline`, `tradeoffs` (직렬화), `priority_explanation`, `dropped_dimensions` — 즉 *결정에 영향을 준 모든 것*. `generated_at` 은 의도적으로 hash 에서 제외 (동일 결정의 재현성을 보장).

**`engine_winner_id` 와 `agent_winner_id` 의 분리** 가 POC3 의 가장 중요한 audit point. 같으면 concur, 다르면 override. UI 와 이벤트 로그가 두 경우를 시각적·구조적으로 구분 (`📊 engine top` / `🤖 agent override` / `✅ engine + agent`).

## IntentMandate 의 priority 무결성

```python
# services/shared/intent.py — body_for_hash 빌드
body_for_hash = {
    "item_query": ...,
    "price_range": ...,
    "allowed_merchants": ...,
    "expires_at": ...,
    "auto_purchase": ...,
}
if preset is not None:
    body_for_hash["priority_preset"] = preset
    body_for_hash["priority"] = priority.model_dump()
sig = stub_sign("user", body_for_hash)
```

priority 가 있을 때만 hash 입력에 포함되도록 가드 — 그 결과 POC2 형태의 legacy Intent 는 **동일한 hash 함수로 동일한 hash 를 산출**한다. smoke 가 검증.

```
preset=None       hash=9d621dab998eaf55  (legacy)
preset=cheapest   hash=0c5e6f...
preset=balanced   hash=00106c2d246beaea
preset=trusted    hash=39159347c7cc6360
preset=fastest    hash=...
```

각 hash 가 모두 distinct → 사용자가 같은 의도에 priority 만 바꿔도 **새 mandate jti, 새 payload_hash** 를 받는다. 변조 시 hash 불일치로 검출 가능.

## SDK Agent 시퀀스 강제

MCP 툴 등록 + SYSTEM_PROMPT 두 군데에서 강제:

```python
# agent/sdk_agent.py
allowed_tools=[
    "mcp__ucp_ap2__search_products",
    "mcp__ucp_ap2__compare_candidates",
    "mcp__ucp_ap2__propose_cart",
]
SYSTEM_PROMPT = """
1. Call search_products at least once. [...]
2. Call compare_candidates(top_n=5). [...]
3. Read the comparison table and pick ONE product. [...]
   Do NOT invent numeric fields (rating, reputation, price).
4. Call propose_cart(product_id, qty=1, headline=...). [...]
"""
```

`propose_cart` 는 내부적으로 **comparison 이 세션에 없으면 trace 생성을 건너뛰고, 있어도 `product_id` 가 보고서에 없으면 `ValueError` → `agent.rationale_skipped` 이벤트** 를 남긴다 — 에이전트가 시퀀스를 어겨도 시스템이 무너지진 않음.

## 검증 — smoke_3rd_poc.py 가 보장하는 invariant

| 테스트 | Invariant |
|---|---|
| `test_priority_hash_changes` | priority 추가/변경 ⇒ `payload_hash` 변동. 4개 preset + legacy 가 모두 distinct hash |
| `test_legacy_intent_backcompat` | priority 없는 POC2 형 폼이 그대로 통과, `priority=None`, `priority_preset=None` |
| `test_comparison_engine_shape` | 모든 후보의 `weighted_score ∈ [0, 1]`, 모든 `normalized[dim] ∈ [0, 1]`, winner ∈ candidates |
| `test_priority_swap_changes_winner` | 4개 preset 이 ≥2개 distinct winner 산출 — 데모가 "의미 있는 차이" 를 보이는지 |
| `test_decision_trace_concur_and_override` | concur/override 모두 빌드되고 Pydantic 라운드트립이 깨끗함, `signer="agent"`, headline 자동생성이 케이스별 분기 |

추가로 `scripts/smoke_2nd_poc.py` 가 무회귀 검증 — 기존 흐름이 깨지지 않았는지.

## 알려진 기술적 한계

- **StubSignature**: 실 ES256 JWS 미사용. PoC1 의 구현이 reference 로 남아 있음
- **rating 결손**: SerpAPI 가 모든 후보에 rating 을 주지 않음 → 엔진은 dimension drop 후 `dropped_dimensions` 에 보고. 에이전트는 발명 금지 (system prompt 명시)
- **headline 자유도**: 에이전트가 headline 에 임의 텍스트를 쓸 수 있음. 후보의 실제 속성을 참조했는지는 enforce 하지 않음 — 자연어 검증은 별도 hook 필요
- **Engine override 정책 부재**: 에이전트가 엔진 winner 와 다른 후보를 골라도 trace 에만 기록되고 거부되지 않음. 거부 정책이 필요하면 머천트/policy 레이어 추가 필요
- **Cart / Payment Mandate 미진입**: POC2 와 동일. AP2 4-mandate 풀체인은 별도 PoC
- **Replay 방지·키 관리·분쟁 흐름**: POC2 보고서의 한계 이월

## 다음 기술 PoC 후보 (구현 비용 추정)

| 후보 | 소요 | 의존성 |
|---|---|---|
| **적대적 테스트 하니스** | 1–2일 | 기존 코드 + 변조 시나리오 6–8개 |
| **결제 풀체인 (Stripe Sandbox)** | 3–5일 | Stripe 계정, Cart/Payment Mandate 정의 |
| **SD-JWT + key binding** | 5–7일 | jwcrypto/pyjwt, key store, holder/verifier 분리 |
| **자율 구매 (`auto_purchase`)** | 2–3일 | 가드레일·예산·만료 검증 + e2e 시연 |
| **분쟁/환불 흐름** | 5–7일 | Refund Mandate 정의 + `AgentDecisionTrace` 가 증거로 어떻게 쓰이는지 |

## 검증 명령 모음

```powershell
# 단위 + 통합 (LLM·네트워크 불필요)
uv run python scripts/smoke_3rd_poc.py     # 신규
uv run python scripts/smoke_2nd_poc.py     # 무회귀

# 실시연 (선택)
uv run python scripts/run_demo.py
# → http://localhost:8501
# → Mock 으로 한 번, SDK 로 한 번, priority 바꿔가며 비교
```

---

*관련: [POC3-business.md](POC3-business.md) · [POC2.md](POC2.md) · [3rd-poc.md](3rd-poc.md) (설계 메모, 영문)*
