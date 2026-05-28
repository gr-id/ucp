# POC3 — 사업적 관점 분석

> 다중 머천트 비교 + 서명된 Agent Rationale 의 **시장 / 가치 / 이해관계자** 측면 분석. 기술적 관점은 [POC3-tech.md](POC3-tech.md).

| 항목 | 값 |
|---|---|
| Status | POC3 구현·시연 가능 |
| 마지막 업데이트 | 2026-05-27 |
| 핵심 메시지 | "에이전트의 판단 자체를 protocol 객체로" |
| 시연 길이 | 5분 (라이브) / 슬라이드 10장 |

---

## TL;DR (사업)

- POC2 까지는 **"에이전트가 결제까지 통과시킬 수 있다"** 를 증명. POC3 는 그 다음 질문 — **"왜 이걸 골랐는지를 사후에 검증·반박할 수 있는가?"** — 에 답한다
- 사용자 우선순위(`cheapest/balanced/trusted/fastest`) 가 **서명된 mandate 의 일부**가 되며, 에이전트의 선택 근거가 **`signer="agent"` 로 서명된 audit 객체**로 남는다
- **머천트 평판이 retrieval/decision 의 1급 차원으로 승격** — 가격만 보지 않는 에이전트 쇼핑이 가능해진다. 이는 머천트 측에 "신뢰" 라는 새 경쟁축을 만든다
- Mock vs SDK 같은 UI 비교를 통해 **"LLM 이 추가로 만들어내는 비즈니스 가치"** 를 한 화면에서 보여줄 수 있다 — 서명된 trade-off 결정
- 분쟁·환불·감사 시 책임 추적이 가능해져 **PSP/머천트의 위험 감소** → AP2 채택의 한 가지 영업 포인트가 추가

## POC3 가 해결하는 사업 문제

| 문제 | POC2 까지의 상태 | POC3 의 답 |
|---|---|---|
| 에이전트가 결제한 뒤 분쟁이 발생하면 "왜 이걸 골랐는지" 가 흩어진 로그뿐 | LLM 대화 로그 + 머천트 카트 — 부인 가능 | `AgentDecisionTrace` 가 후보·점수·근거를 한 객체로 묶고 에이전트가 서명 |
| 사용자가 "신뢰할 만한 곳에서 사고 싶다" 를 어떻게 표현하나 | 자연어 프롬프트에 묻힘 | `priority_preset="trusted"` 라는 명시적 protocol 필드, mandate 에 서명 |
| 에이전트가 가격만 보고 brand-damaging 한 후보를 고를 위험 | 막을 방법이 없음 (그냥 cheapest) | 평판·rating·shipping 이 score 차원에 포함, 사용자가 가중치 조정 가능 |
| 머천트가 자신의 평판/배송 우위를 retrieval 단계에 노출할 채널이 없음 | SerpAPI ranking 에 종속 | 평판 점수가 명시적 비교 차원 (현재는 demo registry, 사업화 시 별도 source 필요) |

## 가치 제안 — 누가 뭘 얻는가

| 이해관계자 | POC3 가 주는 가치 |
|---|---|
| **사용자** | "내 우선순위" 가 단순 UI 옵션이 아니라 mandate. 에이전트가 그 선언을 바꾸려면 새 서명이 필요 — 모르는 사이 cheapest 가 trusted 로 둔갑하는 일을 방지 |
| **머천트** | "신뢰" 라는 새 경쟁축. 가격이 비싸도 평판·평점·배송에서 선택될 수 있는 슬롯이 protocol 레벨에 존재 |
| **PSP / 결제망** | 분쟁 시 `AgentDecisionTrace` 를 증거로 쓸 수 있음 → 차지백·사기 클레임 처리 비용 감소 (잠재) |
| **플랫폼 / 마켓플레이스** | 에이전트의 의사결정이 동질화되지 않도록 — 같은 SerpAPI 결과에서도 priority 에 따라 다른 winner 가 나옴. 머천트가 LLM 벤더에게만 종속되는 위험 완화 |
| **법무 / 컴플라이언스** | "에이전트가 자기 결정에 서명했다" 는 부인불가성 — 자동화된 commerce 의 감사 추적 |
| **C-level** | POC2 의 "에이전트는 commodity" 메시지에 더해, **머천트 차별화의 새 슬롯** 을 시연 가능 |

## 경쟁·차별 축

**POC2** 가 만든 메시지 ("LLM 벤더 무관, 우리 머천트는 어느 에이전트와도 연결됨") 위에, **POC3** 는 다음을 추가한다:

> "에이전트가 우리 머천트를 *왜* 골랐는지를 protocol 이 기록·증명한다."

이 메시지의 영업 활용:

- **머천트 영업**: "당신의 평판/리뷰/배송 우위가 가격에 묻히지 않습니다. priority 가 'trusted' 인 사용자에게는 당신이 선택될 수 있는 슬롯이 protocol 에 박혀 있습니다."
- **PSP 영업**: "에이전트 분쟁이 늘어날 텐데, 우리는 서명된 의사결정 trace 로 처리 비용을 낮춥니다."
- **에이전트 벤더**: "당신 에이전트의 판단이 부인불가성을 갖춘 audit object 가 됩니다 — enterprise 채택에 유리."

## 실측 데모 — 같은 의도, 다른 우선순위, 다른 결과

Mock 카탈로그 4개 상품, intent="running", $0–$200, 모든 머천트 허용.

| 사용자 의도 (priority) | Engine winner | 머천트 | 가격 | 차이 |
|---|---|---|---|---|
| cheapest | Cloudstride White Runners | walmart | **$99** | — |
| balanced | Cloudstride White Runners | walmart | $99 | rating 보정 → 같은 winner |
| **trusted** | **Pacelane Pro White** | **target** | **$119** | **+$20** 더 내고 Target 선택 |
| fastest | Cloudstride White Runners | walmart | $99 | 2-day 배송 우위 |

→ **$20 의 가격 차이를 사용자가 의식적으로 선택**한 결과. mandate hash 가 바뀌므로 사후에 "사용자가 이 trade-off 를 승인했다" 가 cryptographically 증명됨.

이 표 자체가 5분 데모의 핵심 슬라이드 — 시연 시 priority 라디오를 클릭해 같은 데이터에서 winner 가 이동하는 걸 라이브로 보여줄 수 있다.

## 데모 흐름 — 사업적 강조점

1. (0:00) POC2 한 줄 요약 → 질문 *"에이전트가 분쟁 시 부인 가능한가?"*
2. (0:30) Mock 으로 폼 제출 — 카트만 보임. **"오늘의 commerce 가 이 상태"**
3. (1:30) SDK 로 같은 폼 제출 — 비교표 + 서명된 trace 카드 등장. **"여기에 audit layer 가 추가된다"**
4. (2:30) Protocol Inspector 에서 `agent.rationale` 이벤트 펼치기 — `signer="agent"` 강조. **"에이전트가 자기 판단에 서명했다"**
5. (3:30) priority 를 cheapest → trusted 로 바꿔 재제출. **Walmart $99 → Target $119 로 winner 이동, mandate hash 도 바뀜**
6. (4:00) 폐쇄 — *"머천트 입장에서 이 슬롯에 어떻게 들어갈 것인가"* 가 다음 질문

## 리스크 / 한계 (사업 측면)

| 영역 | 이슈 | 완화 방안 |
|---|---|---|
| 평판 데이터 출처 | 현재 `static_demo_registry` 는 demo 용 — 실제 사업화엔 평판 API 파트너십 또는 머천트 자체 신고 + 검증 체계 필요 | Trust Pilot / BBB / 자체 review aggregator 와의 연동 PoC |
| 에이전트 override | 에이전트가 엔진 winner 와 다른 후보를 골라도 거부되지 않음 | 머천트/플랫폼이 override 정책(예: score 차이 ≥ X 시 거부) 부착, 정책도 mandate 화 가능 |
| 사용자 가중치 오설정 | 모든 사용자가 `trusted/fastest` 의 의미를 알지 않음 | UI 에 preset 가중치 미리보기 추가됨 (`price=0.4 trust=0.25 ...`). 추후 가이드/툴팁 강화 |
| headline 자유도 | 에이전트가 그럴듯한 거짓 headline 을 쓸 위험 | 1차로는 audit 기록만, 2차로 LLM-as-judge 검증 hook |
| 평판 점수의 객관성 분쟁 | "왜 우리 머천트가 70 점인가" 같은 분쟁 발생 가능 | 출처 라벨(`dimensions_used`) 이 protocol 에 박혀 있어, 점수 산출 주체에 책임이 명확히 귀속됨 |
| 시연 카탈로그 다양성 | Mock 4개로는 winner 분기가 2개에 머묾 | SerpAPI 라이브 모드 또는 데모용 mock 확장 |

## ROI / 채택 시나리오

### 단기 (3–6개월)

- **머천트 BD 자료**: POC3 보고서 + 5분 데모 영상 → 우리 머천트가 "trusted" 슬롯에 들어가는 시나리오 제시
- **PSP / 분쟁 처리**: `AgentDecisionTrace` 가 분쟁 케이스에서 어떻게 쓰일지 white paper 1장
- **에이전트 벤더 협업**: Claude/ChatGPT/Gemini 각 SDK 에서 동일 흐름이 돌아가는지 추가 검증 (POC2 메시지 강화)

### 중기 (6–12개월)

- 실제 평판 데이터 소스 파트너십 (1–2곳)
- 결제 풀체인 (Stripe Sandbox → 실 PG) 추가하여 e2e 데모
- 적대적 테스트 하니스 (변조·만료·위조) 추가 — 보안 발표 자료로 활용

### 장기 (12개월+)

- AP2 / UCP 표준화 그룹에 `AgentDecisionTrace` 제안 — 표준화 시 우리가 reference impl 보유
- 분쟁/환불 흐름까지 포함한 end-to-end 자동화 → 차지백 감소가 정량적으로 보이는 case study 1건

## 다음 POC 제안 — 사업 임팩트 우선순위

| 순위 | 후보 | 사업적 메시지 | 시연 가치 |
|---|---|---|---|
| 1 | **적대적 테스트 하니스** | "변조·만료·위조를 자동으로 검출" — 보안·법무 청중 강력 | 6–8 시나리오 표 + 거부 로그 |
| 2 | **결제 풀체인 (Stripe Sandbox)** | "AP2 4-mandate 가 처음부터 끝까지 동작" — 결제 의사결정자 청중 | 카트 → 승인 → 가짜 trans 영상 |
| 3 | **자율 구매 활성화** | "사람 개입 없이 의도→구매" — agentic commerce 의 정점 | 가드레일과 e2e 라이브 |
| 4 | **분쟁/환불 흐름** | "`AgentDecisionTrace` 가 분쟁 증거가 된다" — PSP·법무 청중 | 환불 시뮬레이션 + trace 참조 |
| 5 | **SD-JWT + key binding** | "데모 stub 을 표준 서명으로 교체" — 표준 준수 메시지 | 기술 발표용, 사업 임팩트는 간접 |

POC3 보고서가 잘 받아들여지면 **1번(적대적 테스트)** 으로 가는 게 자연스럽다 — 코드량 적고 임팩트 큰 follow-up. POC3 가 만든 mandate 객체들을 그대로 변조해 거부 결과를 보여주면 *"이 protocol 이 왜 필요한가"* 가 한 번 더 강화된다.

---

*관련: [POC3-tech.md](POC3-tech.md) · [POC2.md](POC2.md) · [SHARE.md](SHARE.md)*
