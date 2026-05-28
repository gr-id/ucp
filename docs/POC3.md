# UCP + AP2 Agentic Commerce — POC3 보고서 (인덱스)

> POC2 까지의 흐름 위에 **다중 머천트 비교 + 서명된 Agent Rationale** 을 추가한 PoC. 보고서는 관점에 따라 두 파일로 분리되어 있다.

| 항목 | 값 |
|---|---|
| Repo | <https://github.com/gr-id/ucp> |
| Branch | `main` |
| Status | **POC3 완료** · 발표·시연 가능 |
| 마지막 업데이트 | 2026-05-27 |

---

## 두 관점으로 나뉜 보고서

### 📐 [POC3-tech.md](POC3-tech.md) — 기술적 관점

프로토콜·코드·검증 측면. 누가 이 보고서를 읽으면 좋은가:

- **엔지니어 / 아키텍트** — mandate 스키마 변경, Comparison Engine 알고리즘, 서명 설계, MCP 툴 시퀀스
- **보안 / 인프라** — `AgentDecisionTrace` 의 `signer="agent"`, payload_hash 무결성, 데이터 출처 분리
- **QA** — `scripts/smoke_3rd_poc.py` 가 보장하는 5개 invariant + POC2 무회귀

핵심 내용:
- IntentMandate 의 priority 확장과 하위호환 설계
- Comparison Engine 의 정규화·가중치·결손차원 재정규화 알고리즘
- AgentDecisionTrace 의 서명 대상 (`body_for_hash`) 과 engine/agent winner 분리
- 변경된 파일 표면 + 다음 기술 PoC 후보별 소요 추정

### 💼 [POC3-business.md](POC3-business.md) — 사업적 관점

시장·가치·이해관계자 측면. 누가 이 보고서를 읽으면 좋은가:

- **C-level / 사업 기획** — POC2 "에이전트는 commodity" 위에 추가되는 새 차별축
- **머천트 BD / 영업** — "신뢰" 라는 새 경쟁 슬롯의 영업 활용
- **PSP / 분쟁 처리** — `AgentDecisionTrace` 가 차지백·사기 처리 비용을 어떻게 낮출 수 있는가
- **법무 / 컴플라이언스** — 에이전트의 부인불가성 확보

핵심 내용:
- 누가 무엇을 얻는가 (이해관계자별 가치 제안)
- 같은 의도·다른 우선순위가 만든 실측 결과 ($99 vs $119 의 의식적 선택)
- 5분 데모의 사업적 강조점
- 리스크 / 채택 시나리오 (단기·중기·장기)
- 사업 임팩트 기준 다음 POC 후보 우선순위

---

## 빠른 컨텍스트 — POC3 한 줄 요약

> POC1: 프로토콜이 닫힌다 · POC2: LLM 에이전트가 그 안에 끼워진다 · **POC3: 에이전트의 판단 자체가 mandate 체인에 서명되어 들어간다**

```
사용자 폼 + 우선순위 라디오
   ↓ (priority 가 payload_hash 에 서명됨)
IntentMandate [signer="user"]
   ↓
UCP /ucp/search  →  enriched products (rating + reputation + shipping)
   ↓
Comparison Engine (순수 Python, 결정론)
   ↓
ComparisonReport  →  Claude SDK Agent
   ↓
AgentDecisionTrace [signer="agent"]   ← 신규
   ↓
MerchantAuthorization [signer="merchant"]
   ↓
카트 표시 (Approve 비활성 — POC2 종착점 유지)
```

전체 설계 메모(영문)는 [3rd-poc.md](3rd-poc.md), 이전 PoC 흐름은 [POC2.md](POC2.md).

---

## 빠른 검증

```powershell
uv run python scripts/smoke_3rd_poc.py    # 5/5 통과
uv run python scripts/smoke_2nd_poc.py    # POC2 무회귀
uv run python scripts/run_demo.py         # 라이브 데모
```

---

*관련 문서: [POC3-tech.md](POC3-tech.md) · [POC3-business.md](POC3-business.md) · [POC2.md](POC2.md) · [3rd-poc.md](3rd-poc.md) · [SHARE.md](SHARE.md)*
