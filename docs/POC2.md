# UCP + AP2 Agentic Commerce — POC 진행 상황 (POC2까지)

> AI 에이전트가 사용자 대신 결제까지 수행하는 흐름을 Google **UCP** + **AP2** 표준으로 구현한 사내 데모. 두 차례 POC를 거쳐 현재 **POC2 완료** 상태.

| 항목 | 값 |
|---|---|
| Repo | <https://github.com/gr-id/ucp> |
| Branch | `main` |
| Status | **POC2 완료** · 발표·시연 가능 |
| 마지막 업데이트 | 2026-05-22 |

---

## TL;DR

- POC1 (Mock 에이전트) → POC2 (Claude Agent SDK 에이전트) 까지 완료
- 두 에이전트 모두 **같은 UCP 머천트 / AP2 PSP** 와 동일한 4단계 Mandate 체인을 통과
- 단일 노트북에서 풀스택 구동: 머천트(:8001) + PSP(:8002) + Streamlit UI(:8501)
- 모든 결제 단계가 **ES256 JWS 서명·검증** — 누가 무엇을 승인했는지 단일 번들로 감사 가능

## POC1 — Mock Agent (결정론적 흐름)

**목표:** LLM 의존성을 제거한 상태에서 UCP + AP2 프로토콜 체인이 끝단까지 동작하는지 검증.

| 항목 | 내용 |
|---|---|
| 에이전트 구현 | [`agent/mock_agent.py`](../agent/mock_agent.py) — 정해진 규칙으로 검색·선택 |
| 입력 처리 | 사용자 프롬프트를 단순 키워드 매칭으로 Intent 제약 추출 |
| 의도 | 프로토콜 자체의 정합성 입증 — "LLM 없이도 체인 검증이 통과하는가" |
| 결과 | 4단계 Mandate 체인 (Intent → Merchant Authz → Checkout → Payment) 전부 검증 통과 |

**핵심 확인:**
- Intent Mandate 서명 → 머천트가 `intent` 제약 강제
- `merchant_authorization` JWS 가 카트 `content_hash` 로 바인딩
- PSP가 4개 jti 검증 후 가상 트랜잭션 승인

## POC2 — Claude Agent SDK Agent (자연어 의도)

**목표:** LLM 에이전트를 같은 프로토콜에 그대로 끼워 넣을 수 있는지 검증 — **에이전트가 commodity가 될 수 있는가**.

| 항목 | 내용 |
|---|---|
| 에이전트 구현 | [`agent/sdk_agent.py`](../agent/sdk_agent.py) — Claude Code SDK + MCP 도구 |
| 입력 처리 | 자연어 프롬프트 → Claude가 검색·선택 추론 |
| 의도 | 동일 머천트·PSP에 LLM 에이전트가 unmodified로 접속 가능한지 |
| 결과 | Claude가 의미 기반 상품 매칭 + 검색어 자기 보정까지 수행하며 체인 검증 통과 |

**실측 예시:**

> 프롬프트: *"I want a marathon-ready white running shoe. Money is not the issue but stay under $200."*

- 첫 검색 0건 → Claude가 쿼리를 점진적으로 broadening → "shoe" 키워드로 3건 매칭
- 단순 최저가가 아니라 description 의 "carbon plate, 7mm drop" 을 읽고 **Pacelane Pro White** ($145) 선택
- 4단계 서명 체인 검증 통과 → 가상 트랜잭션 `txn_c07e6b27da2a` 승인
- 총 소요 ~43초 (대부분 LLM 호출)

## 두 POC의 공통 컴포넌트

| 컴포넌트 | 역할 | 위치 |
|---|---|---|
| 머천트 (UCP) | 카탈로그 검색, 카트 구성, 체크아웃 세션, `merchant_authorization` JWS 발급 | [`services/merchant/`](../services/merchant) |
| PSP (AP2) | Payment Mandate → 4개 서명 검증 → 가상 승인 | [`services/psp/`](../services/psp) |
| 공유 모듈 | ES256 JWS sign/verify, RFC 8785 JCS, Pydantic Mandate 모델 | [`services/shared/`](../services/shared) |
| Streamlit UI | 좌: 채팅, 우: Protocol Inspector (JWS 디코드) | [`ui/app.py`](../ui/app.py) |

### 4단계 Mandate 체인

1. **Intent Mandate** — 사용자 서명. *"흰 운동화, $150 이하"* 같은 제약을 cryptographically commit
2. **Merchant Authorization** — 머천트 서명. 카트 본문에 `content_hash` 로 바인딩 → 카트 변조 불가
3. **Checkout Mandate** — 사용자 서명. Intent + Merchant_auth 둘 다 임베드 → "이 카트를 이 가격에 승인함"
4. **Payment Mandate** — 사용자 서명. PSP 에게 가는 최종 토큰 — 모든 상위 mandate 포함

어느 한 단계라도 위조하면 cross-binding 이 깨져 PSP 에서 거부됨.

## POC1 → POC2 에서 새로 확인된 것

| 메시지 | 근거 |
|---|---|
| **에이전트가 untrusted여도 안전** | POC2의 Claude는 사용자 키를 보유하지 않음. hallucinate 해도 사용자 승인 단계에서 차단 |
| **에이전트는 commodity가 됨** | 프로토콜이 LLM 벤더를 모름 → 같은 머천트에 ChatGPT/Claude/Gemini 누구나 붙을 수 있음을 실증 |
| **머천트의 새 경쟁축** | 자연어 의도 → 상품 매칭. 우리 카탈로그에서 Claude가 3번 보정 — 실제 머천트는 의미 검색 강해야 함 |
| **신뢰 무게중심 이동** | 머천트·결제망 신뢰 → 사용자 키 커스터디(OS / passkey) 신뢰로 |

## 현재 한계 (POC3 검토용)

- **키 관리**: 디스크 PEM 저장. 프로덕션은 OS keystore / passkey / secure enclave
- **Replay 방지**: nonce / idempotency 없음. Intent 의 `expires_at` 만 존재
- **분쟁 / 환불**: 승인 이후 흐름 미구현
- **SD-JWT+kb**: 데모는 plain JWS. 부분 공개(selective disclosure) 필요 시 업그레이드
- **다중 머천트**: 한 Intent로 여러 후보 비교하는 흐름 없음
- **Identity linking**: UCP 의 OAuth 2.0 buyer linking 생략
- **PSP 리스크**: 항상 승인. 실세계는 fraud signals 검토 필요
- **레이턴시**: 43초 / 거래 — 면대면 결제 기준 너무 김

## 직접 돌려보기

```powershell
# 1) 사전 준비 (1회만)
winget install --id=astral-sh.uv
npm i -g @anthropic-ai/claude-code
claude                                  # /login (SDK 모드 쓸 때만)

# 2) 프로젝트
git clone https://github.com/gr-id/ucp.git
cd ucp
uv sync                                 # POC1 (Mock) 만 쓸 거면 이걸로 충분
uv sync --group agent                   # POC2 (Claude SDK) 도 쓸 거면
uv run python scripts/gen_keys.py       # ES256 키 생성
uv run python scripts/run_demo.py       # 머천트 + PSP + UI 한 번에
```

브라우저 <http://localhost:8501> 접속 후 에이전트 드롭다운에서 **Mock** 또는 **Claude Agent SDK** 선택.

## 5분 시연 흐름

1. (0:00) 아키텍처 한 장 — 에이전트 / 머천트 / PSP 세 박스, 서로 안 믿고 서명만 검증
2. (0:30) 프롬프트 입력. 첫 번째 동작은 머천트 호출이 아니라 **Intent Mandate 서명**
3. (1:30) 우측 인스펙터에서 `merchant_authorization` 펼치기 → JWS 디코드
4. (2:30) Approve 클릭 → **Checkout Mandate** 가 Intent + Merchant_auth 임베드
5. (3:30) PSP 이벤트 펼치기 → 4개 jti 가 한 번에 검증된 `chain_verified` 강조
6. (4:00) 적대적 시나리오 1개: "Find me white *trail* shoes under $150" → 머천트가 Intent 위반으로 거부
7. (4:30) Q&A

## POC3 후보 (요청 받으면 진행)

- 슬라이드 덱 (10장 내외)
- 데모 영상 녹화 (라이브 실패 대비 백업)
- 적대적 테스트 — 변조된 카트, 만료된 Intent, 서명 위조 등
- TypeScript / Next.js 포팅
- 실제 PSP 어댑터 (Stripe sandbox 등)
- SD-JWT+kb 업그레이드

## 참고 자료

- AP2 specification: <https://ap2-protocol.org/specification/>
- UCP specification: <https://ucp.dev/>
- UCP AP2 Mandates extension: <https://ucp.dev/specification/ap2-mandates/>
- UCP GitHub: <https://github.com/Universal-Commerce-Protocol/ucp>
- Google Cloud blog (AP2 announcement): <https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol>

---

*관련 문서: [README.md](../README.md) · [SHARE.md](SHARE.md)*
