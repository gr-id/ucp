# 2nd PoC — 구조화된 쇼핑 의도 + 라이브 UCP 머천트 상품

> *결제 직전*까지의 흐름을 실제 라이브 UCP 머천트(Walmart / Target / Wayfair / Etsy)
> 상품 데이터로 시각화하는 PoC. 1차 PoC가 입증한 서명 체인은 가정으로 두고,
> 데이터·UX 진화에 집중한다.

## 1차 PoC와 무엇이 다른가

| 측면 | 1차 PoC | 2차 PoC |
| --- | --- | --- |
| **입력** | 자연어 채팅 | 5필드 구조화 폼 |
| **카탈로그** | in-memory 5개 | SerpAPI Google Shopping (4개 라이브 머천트) |
| **서명** | 실 ES256 JWS | StubSignature (서명값이 외부 단말에 있다고 가정) |
| **흐름 종착** | PSP 승인까지 | 카트 검토 직전 (Approve 비활성화) |
| **PSP 서비스** | 호출됨 | 미호출 (런처에서 제외) |
| **목적** | 프로토콜 작동 가능성 입증 | 실 데이터 + UX + 사업적 시연 |

## 입력 폼 = Intent Mandate 본문

| 필드 | UI | 의미 |
| --- | --- | --- |
| 구매할 물품 | 텍스트 | `item_query` — SerpAPI 검색어 |
| 가격 범위 | from / to (USD) | `price_range.{from_cents, to_cents}` |
| 쇼핑할 사이트 | 4개 체크박스 + 전체 선택 | `allowed_merchants: list[str]` |
| 유지 시간 | 숫자 (시간) | `expires_at = now + hours×3600` |
| 자동 구매 허용 | Yes / No | `auto_purchase: bool` (옵션 표시만 — 항상 manual approval) |

## 서명 모델 — 왜 stub인가

1차 PoC가 ES256 JWS + RFC 8785 canonicalization으로 4단계 Mandate 체인이
표준 암호 프리미티브만으로 작동함을 증명했다. 2차 PoC는 그 결과를 전제로
삼고, 사용자가 외부 단말(Passkey / OS keystore / HSM)에서 이미 서명할 수
있다고 *가정*한다. 따라서:

- `services/shared/crypto.py` 와 `keys/` 는 2차 PoC에서 사용되지 않음
- 각 Mandate 의 `signature` 필드는 `StubSignature(signer, signed_at, payload_hash)`
- Protocol Inspector 는 mandate JSON 과 stub signature 를 그대로 보여줌
- **그러나** Intent 의 *데이터 강제*는 그대로 살아있음 — 머천트가 카트 생성
  단계에서 `allowed_merchants`, `price_range`, `expires_at` 위반을 거부

## 결제 비활성화 — 왜

한국에서 실제 결제까지 가려면 별도 결정이 필요하다 (자세한 분석은 채팅 로그
또는 별도 노트 참조):

- 한국 머천트 (네이버 · 쿠팡) 의 UCP 어댑팅
- 국내 PG (Toss · 이니시스 등) 의 AP2 어댑터
- 사용자 키 커스터디 (Passkey / 모바일 secure storage)
- 전자금융거래법 · 책임 소재 등 규제 정리

PoC 는 그 모든 결정 전에 *지금 가능한 시연 범위*를 정직하게 보여주는 게
목적. 따라서 Approve 버튼은 명시적으로 비활성화 + 안내 배너 표시.

## 실행

### 사전 (1회)

```powershell
uv sync                          # 의존성 설치
uv sync --group agent            # Claude SDK 모드까지 쓸 경우
# 키 생성 단계는 2차 PoC 에서 불필요
```

### Mock 모드 (즉시 실행 가능)

```powershell
$env:UCP_CATALOG_MODE = "mock"
uv run python scripts/run_demo.py
```

브라우저: <http://localhost:8501>

### SerpAPI 모드 (실 라이브 머천트)

1. <https://serpapi.com/users/sign_up> 가입 (무료 250/월)
2. 발급된 키 설정 후 실행

```powershell
$env:UCP_CATALOG_MODE = "serpapi"
$env:SERPAPI_KEY = "...your-key..."
uv run python scripts/run_demo.py
```

### Smoke test

```powershell
# 통합 (mock + 가능하면 SerpAPI)
uv run python scripts/smoke_2nd_poc.py

# end-to-end (mock catalog로 폼 → 카트 검증)
uv run python scripts/smoke_e2e.py
```

## 시연 권장 흐름

1. **Mock 모드로 먼저 시연** — 결정론적, 빠름, 비용 없음
   - 5필드 폼 채우기 → Submit → 카트 표시 → Approve 비활성화 확인
   - Protocol Inspector 펼쳐서 IntentMandate JSON 의 5필드 + stub signature 보여주기

2. **SerpAPI 모드로 동일 시연 반복**
   - 같은 폼, 같은 결과 흐름인데 카트의 *실제 상품 이미지 + 머천트 배지* 표시
   - "내일 한국 머천트가 UCP 합류하면 이 카드 UI가 그대로 작동" 메시지

3. **부정 케이스 한두 개**
   - 가격 범위를 너무 좁게 → "조건에 맞는 상품 없음" 안내
   - 머천트 하나만 체크 → 검색 결과 분포 변화

## 한계 / 비범위

- **실제 결제**: 별도 PoC (국내 PG 어댑터 + 키 커스터디)
- **한국 컨텍스트**: 사용자 결정으로 의도적 제외 (KRW, 배대지, Toss 등 UI 없음)
- **자동 구매**: 옵션 표시만, 동작 비활성화
- **다중 머천트 카트**: 한 카트는 한 머천트만
- **SD-JWT + key binding**: stub signature 로 추상화
- **분쟁/환불 흐름**: 표준에 정의 없음, PoC 도 다루지 않음

## 회귀

- `scripts/smoke_e2e.py` 가 mock catalog 로 폼 흐름을 검증 — 1차 PoC 의
  자연어 흐름은 폐기됨
- `scripts/smoke_crypto.py` 는 그대로 (crypto.py 자체는 변경 없음). 1차 PoC
  의 키가 있을 때만 PASS
- `services/psp/main.py` 는 그대로 보존 (런처에서만 제외). 미래에 결제 PoC
  단계에서 다시 활성화 가능
