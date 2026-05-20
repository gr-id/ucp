# UCP + AP2 Agentic Commerce — Internal Demo

> AI 에이전트가 사용자 대신 쇼핑하는 흐름을 Google의 **Universal Commerce Protocol (UCP)** + **Agent Payments Protocol (AP2)** 표준으로 끝까지 구현해본 실험 데모. 코드 · 발표 자료 · 시연 가능.

**Repo:** `<github-org>/ucp-ap2-demo` (TBD)
**Demo URL (local):** `http://localhost:8501` 실행 시
**Status:** 데모 가능 · 프로덕션 아님

---

## TL;DR

- 에이전트에게 신용카드를 주지 않고도 "대신 사줘"를 안전하게 시킬 수 있다 — **사용자가 서명한 4단계 Mandate 체인**이 그 답
- 데모는 **단일 노트북에서 풀스택**이 돌아간다: UCP 머천트(:8001) + AP2 PSP(:8002) + Streamlit UI(:8501)
- 에이전트는 두 가지 — **Mock** (LLM 없음) / **Claude Agent SDK** (자연어 의도 → 상품 선택 reasoning)
- 모든 결제 단계가 **ES256 JWS로 서명·검증**되어 누가 무엇을 승인했는지 단일 번들로 감사 가능
- **돈은 실제로 안 나간다** — PSP는 mock, 카드 토큰도 가짜

## 왜 이 실험을 했나

2026년 1월 Google이 UCP를 NRF 키노트에서 발표하면서 OpenAI ACP, Apple 등도 비슷한 표준에 묶이는 흐름. 에이전트 커머스가 어떤 모양으로 굳어질지를 **직접 코드로 만져봐야** 판단이 됐고, 그 결과가 이 데모.

## 무엇이 만들어졌나

```
사용자 ──prompt──▶ 에이전트 ──UCP──▶ 머천트(:8001) ─signs─▶ merchant_authorization
                     │                    │
                     │           시그니처 발급                                           
사용자 ◀──카트 검토── 에이전트                                                          
   │                                                                                  
   │── ✅ 승인 ─────▶ 에이전트 ──UCP──▶ 머천트 (CheckoutMandate 검증 + 완료)             
                     └─────AP2────▶ PSP(:8002) (4단계 서명 체인 검증) ──▶ 트랜잭션 ID
```

### 컴포넌트

| 컴포넌트 | 역할 | 위치 |
|---|---|---|
| **머천트 (UCP)** | 카탈로그 검색, 카트 구성, 체크아웃 세션, `merchant_authorization` JWS 발급 | `services/merchant/` |
| **PSP (AP2)** | Payment Mandate 수신 → Intent/Merchant/Checkout/Payment 4개 서명 검증 → 가상 승인 | `services/psp/` |
| **공유 모듈** | ES256 JWS sign/verify, RFC 8785 JSON Canonicalization, Pydantic Mandate 모델 | `services/shared/` |
| **에이전트 (Mock)** | LLM 없이 결정론적으로 흐름 구동 | `agent/mock_agent.py` |
| **에이전트 (Claude SDK)** | Claude가 MCP 도구 호출해서 상품 선택 — 자연어 의도 처리 | `agent/sdk_agent.py` |
| **Streamlit UI** | 좌: 채팅, 우: Protocol Inspector (JWS 디코드 보여줌) | `ui/app.py` |

### 4단계 Mandate 체인

1. **Intent Mandate** — 사용자가 서명. *"흰 운동화, $150 이하"* 같은 제약을 cryptographically commit
2. **Merchant Authorization** — 머천트가 서명. 카트 본문에 `content_hash`로 바인딩 → 카트 변조 불가
3. **Checkout Mandate** — 사용자가 서명. Intent + Merchant_auth 둘 다 임베드 → "이 카트를 이 가격에 승인함"
4. **Payment Mandate** — 사용자가 서명. PSP에게 가는 최종 토큰 — 모든 상위 mandate를 포함

**핵심 속성:** 어느 한 단계라도 위조하면 cross-binding이 깨져 PSP에서 거부됨.

## 실제로 돌려본 결과

> 프롬프트: *"I want a marathon-ready white running shoe. Money is not the issue but stay under $200."*

- Claude가 **자기 보정**: 첫 검색 0건 → 쿼리 점진적 broadening → "shoe" 키워드로 3건 매칭
- **의도 정렬 선택**: 단순 최저가가 아니라 description에서 "carbon plate, 7mm drop" 읽고 **Pacelane Pro White** ($145) 선택
- 4단계 서명 체인 검증 통과 → 가상 트랜잭션 `txn_c07e6b27da2a` 승인
- 전체 소요 ~43초 (그중 LLM 호출이 대부분)

## 발표에서 강조하는 것

| 메시지 | 근거 |
|---|---|
| **에이전트는 untrusted여도 안전** | 우리 데모 Claude는 사용자 키를 갖지 않음. hallucinate해도 사용자 승인 단계에서 차단됨 |
| **에이전트는 commodity가 됨** | 프로토콜이 LLM 벤더를 모름 → 같은 머천트에 ChatGPT/Claude/Gemini 누구나 붙을 수 있음 |
| **머천트의 새 경쟁축** | 자연어 의도 → 상품 매칭. 우리 카탈로그에서 Claude가 3번 보정 — 실제 머천트는 의미 검색 강해야 함 |
| **신뢰 무게중심 이동** | 머천트·결제망 신뢰 → 사용자 키 커스터디(OS/passkey) 신뢰로 |

## 한계 (다음 단계 검토용)

- **키 관리**: 디스크 PEM 저장. 프로덕션은 OS keystore / passkey / secure enclave
- **Replay 방지**: nonce/idempotency 없음. Intent의 `expires_at`만 있음
- **분쟁/환불**: 승인 이후 흐름 미구현
- **SD-JWT+kb**: 데모는 plain JWS. 부분 공개(selective disclosure) 필요 시 업그레이드
- **다중 머천트**: 한 Intent로 여러 후보 비교하는 흐름 없음
- **Identity linking**: UCP의 OAuth 2.0 buyer linking 생략
- **PSP 리스크**: 항상 승인. 실세계는 fraud signals 검토 필요
- **레이턴시**: 43초/거래는 면대면 결제 기준 너무 김

## 직접 돌려보려면

```powershell
# 1. 사전 준비 (1회만)
winget install --id=astral-sh.uv
npm i -g @anthropic-ai/claude-code
claude                                  # /login으로 인증 (SDK 모드 쓸 때만)

# 2. 프로젝트
git clone <repo-url>
cd ucp-ap2-demo
uv sync                                 # Mock 모드만 쓸 거면 이걸로 충분
uv sync --group agent                   # Claude SDK 모드도 쓸 거면
uv run python scripts/gen_keys.py       # ES256 키 생성
uv run python scripts/run_demo.py       # 머천트 + PSP + UI 한 번에
```

브라우저에서 <http://localhost:8501> → 프롬프트 입력.

**처음엔 Mock 모드 추천** — 안정적이고 빠르고 토큰 비용 없음.

## 시연 흐름 (5분 데모용)

1. (0:00) 아키텍처 한 장 — 에이전트 / 머천트 / PSP 세 박스, 서로 안 믿고 서명만 검증
2. (0:30) 프롬프트 입력. 첫 번째로 일어나는 일은 머천트 호출이 아니라 **Intent Mandate 서명**
3. (1:30) 우측 인스펙터에서 `merchant_authorization` 펼치기 → JWS 디코드 보여주기. "이건 머천트만 만들 수 있고, 우리는 그걸 검증할 수 있음"
4. (2:30) Approve 클릭 → **Checkout Mandate** 가 Intent + Merchant_auth 를 둘 다 임베드하는 걸 보여주기
5. (3:30) PSP 이벤트 펼치기 → 4개 jti가 한 번에 검증된 chain_verified 필드 강조
6. (4:00) 적대적 시나리오 1개: "Find me white *trail* shoes under $150" → 머천트가 Intent 위반으로 거부
7. (4:30) Q&A

## 추가로 만들 수 있는 것 (요청 받으면 진행)

- 슬라이드 덱 (10장 내외)
- 데모 영상 녹화 (라이브 실패 대비 백업)
- 적대적 테스트 — 변조된 카트, 만료된 Intent, 서명 위조 등
- TypeScript/Next.js 포팅
- 실제 PSP 어댑터 (Stripe sandbox 등)

## 참고 자료

- AP2 specification: <https://ap2-protocol.org/specification/>
- UCP specification: <https://ucp.dev/>
- UCP AP2 Mandates extension: <https://ucp.dev/specification/ap2-mandates/>
- UCP GitHub: <https://github.com/Universal-Commerce-Protocol/ucp>
- Google Cloud blog (AP2 announcement): <https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol>

---

*문서 작성: Claude Code · 코드 리뷰/질문 환영*
