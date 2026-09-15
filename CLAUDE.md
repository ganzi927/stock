# CLAUDE.md — 이 저장소 작업 규칙

## 핵심 규칙: 사양 주도 개발 (Spec-Driven Development)

**이 프로젝트의 모든 변경은 `spec/`를 통해서만 개발되고 관리된다.** 계산 로직·데이터
계약·실행 흐름·자동화·AI 프롬프트를 바꾸려는 모든 작업은 다음 순서를 따른다.

1. **사양 먼저.** 바꿀 대상의 spec 파일(`spec/00`~`spec/60`)을 먼저 연다. 해당
   요구사항(REQ-*)·불변조건(INV-*)·수용 기준(AC-*)을 찾아 **원하는 최종 상태로
   먼저 수정**한다. 새 동작이면 새 REQ 번호를 부여한다.
2. **사양에 맞춰 구현.** 그 다음에 코드를 고친다. 코드는 spec을 만족시키는 수단이다.
3. **수용 기준 갱신·검증.** 바뀐 REQ에 대응하는 AC를 갱신하고, 가능하면
   `tests/test_math.py`에 known-answer 케이스를 추가한다. `python tests/test_math.py`가
   통과해야 한다.
4. **상태표 갱신.** `spec/README.md`의 상태표에서 해당 행의 "마지막 정합 확인" 날짜와
   드리프트 칸을 갱신한다.
5. **스냅샷.** 로직을 바꾸는 커밋 전에 `_backup_YYYYMMDD/`에 관련 파일 스냅샷을 남긴다.

이 다섯 단계는 **한 커밋 안에서** 함께 이뤄진다. 코드만 바뀌고 spec이 안 바뀐 커밋,
또는 그 반대는 이 프로젝트에서 미완성으로 간주한다.

### 기준 우선순위

- **코드가 최종 기준(authority)이다.** 이미 존재하는 코드와 spec이 어긋나면 구현이
  옳다고 보고 spec을 코드에 맞춘다 — **단**, 그 어긋남이 의도치 않은 버그로 판명되면
  버그로 처리하고 위 1~5단계로 고친다.
- 새로 만드는 동작은 반대다: **spec이 먼저**고 코드가 따라온다.

### 예외 (spec 갱신 불필요)

순수 리팩터링(동작 불변), 오타·주석 수정, HTML/CSS 표현 변경(`report.py`·
`options_report.py`·`charts.py`의 레이아웃), 로그 문구, 의존성 버전 범프.
계산 결과·계약·exit code·파일 스키마가 바뀌면 예외가 아니다.

## 방향성·투자 조언 금지

리포트·AI 코멘트·커밋 메시지 어디에도 "오른다/내린다", "매수/매도", "수익률이
좋았다/나빴다" 식 서술을 넣지 않는다. 이 도구는 시장 맥락 readout이지 예측기가 아니다
(`spec/10-kfgi.md` REQ-KFGI-11, `spec/40-outlook-ai.md` INV-AI-1).

## 실행·검증

- 운영 진입점: `python combined_main.py [--as-of YYYY-MM-DD] [--force]`
- 단독: `python main.py` / `python options_main.py` / `python stock_options_main.py`
- 테스트: `python tests/test_math.py` (exit 0 필수)
- 예측력 재검증(분기 1회): `python backtest.py` → `VALIDATION.md` 갱신
- venv: `venv\Scripts\python.exe`

## 문서 지도

| 목적 | 파일 |
|---|---|
| **정식 사양 (변경의 출발점)** | `spec/` — 인덱스 `spec/README.md` |
| 사용자용 개요 | `README.md` |
| fmkorea 대조·조사 이력 | `RECONCILIATION.md` |
| 예측력 백테스트 결과 | `VALIDATION.md` |
| 데이터 시작일·품질 한계 | `DATA_INVENTORY.md` |
| 과거 작업계획 (완료) | `WORKPLAN.md`, `WORKPLAN2.md` |
