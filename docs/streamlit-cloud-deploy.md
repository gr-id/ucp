# Streamlit Community Cloud — 배포 가이드

> 카드 등록 없이 무료로 호스팅. GitHub repo (`gr-id/ucp`) 를 그대로 사용.

## 한 번만 하는 셋업 (5분)

1. **<https://share.streamlit.io> 접속** → GitHub 계정으로 로그인 (gr-id)

2. 우상단 **Create app** 클릭

3. 폼 입력:
   - **Repository**: `gr-id/ucp`
   - **Branch**: `main`
   - **Main file path**: `ui/app.py`
   - **App URL**: `ucp-poc` (또는 원하는 이름) → 최종 URL: `https://ucp-poc.streamlit.app`

4. **Advanced settings** 펼치고 **Secrets** 영역에 아래 붙여넣기:
   ```toml
   UCP_CATALOG_MODE = "serpapi"
   SERPAPI_KEY = "여기에-당신의-SerpAPI-키"
   ```

5. **Deploy!** 클릭 → 빌드 ~3–5분 → URL 활성화

## 배포 후 동작

배포된 앱에서 사용자는:

- **SerpAPI 키** (사이드바, 선택): 비워두면 당신의 키 사용 (쿼터 공유), 입력하면 본인 키
- **Agent 모드**:
  - **Mock**: 즉시 작동 (LLM 없음)
  - **Claude Code (local session)**: ❌ 작동 안 함 (Streamlit Cloud에는 `claude` CLI 없음)
  - **Anthropic API (own key)**: 사용자가 자기 Anthropic API 키 입력 후 사용

## 코드 수정 시

GitHub `main`에 푸시하면 Streamlit Cloud가 자동으로 재빌드합니다 (1–2분).

수동 재빌드는 Streamlit Cloud 대시보드 → 앱 메뉴 → **Reboot app**.

## 알아두면 좋은 한계

- **Cold start**: 30분 사용 없으면 슬립. 다음 접속 시 깨우는데 ~30초
- **메모리**: 무료 tier 1GB. 우리 앱은 ~500MB로 여유
- **동시 사용자**: 무료는 비공식 권장 ~50 정도
- **로그**: 대시보드에서 실시간 확인 가능
- **`claude` CLI 부재**: "Claude Code" 모드는 작동 안 함 (Anthropic API 모드만 권장)
- **Wayfair/Etsy 결과 분포**: 운동화 쿼리에 Wayfair는 0건 (가구 위주), Etsy는 수공예 위주라 일부 결과만 노출

## 비용

- Streamlit Community Cloud: **$0/월** (무료)
- SerpAPI: 무료 250 쿼리/월 (한 번 검색 = 머천트 수만큼 호출, 즉 4머천트 다 선택 시 4 쿼리)
- 사용자별 본인 키 사용 시: 당신은 0
- Anthropic API: 사용자가 본인 키로 직접 결제 → 당신은 0
