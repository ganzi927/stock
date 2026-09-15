# 작업계획서 v2 — 무료 데이터 제약 하 수치 정밀화

작성 기준일: 2026-09-01. `WORKPLAN.md`(방법론 엄밀화)의 후속.

**전제**: 유료 피드 없음 (KRX Open API + 네이버 금융 + ECOS + KB 수동 업로드만).
목표는 "예측을 맞히는 것"이 아니라 **각 수치가 낼 수 있는 최대 정확도 + 정직한 불확실성 표기**.

---

## 진행 상황

| Phase | 상태 | 비고 |
|---|---|---|
| 필수(H1~H4, M2~M4, M10, M11) | ✅ (2026-09-01) | 콤보박스 제거, 투심게이지 CI 경고, LLM 출력 검증 게이트, temperature=0, 배당 q |
| D1 테스트 스위트 | ✅ | `tests/test_math.py` — BS그릭스/PoT/MaxPain/McClellan/백분위/합성선물 25항목, `python tests/test_math.py` |
| D2 라벨 정합 | ✅ | Breadth "Oscillator", Put/Call "지수옵션", PoT "위험중립"(HTML), fmkorea 주석 삭제, Volatility raw/score, build_scenarios 보조 Wall, dex_neutral near=spot, 25Δ RR 거리가드, SYSTEM_PROMPT 문장수, 위클리 파서 가드, cp949 콘솔 인코딩 |
| A1 KRX spot | ✅ | 옵션 spot을 선물과 동일 스냅샷 KRX SPOT_PRC로 (`options_data.fetch_kospi200_spot`) |
| A2 배당 캘린더 | ✅ | `dividends.py` (손유지, 연1회 갱신) |
| A3 low_confidence | ✅ | 점수화 히스토리 <1년 지표는 합성 제외 + 카드 표기. 현재는 미발동(Strength 2022~, Breadth 2021~) |
| B1 이산 배당 | ✅ | 개별주식: 만기 내 배당락 시 PV→등가 q. 지수는 선물내재 q 유지 |
| B2 장중 T | ✅ (검토) | KRX 종가결제라 close-to-close ACT/365가 이미 정확 — 문서화만 |
| B3 sticky 민감도 | ✅ | Zero Gamma 밴드에 sticky-moneyness 샘플 추가, r±25bp로 축소, "모델오차"→"민감도" |
| B4 IV 윙 외삽 | ✅ | flat→기울기 외삽, 같은 행사가 콜/풋 IV 공동 처리 |
| B5 MaxPain | ✅ | 잔존 OI(OI≫거래량·딥) 명시 제외 + ±20/30/40% 병기 + "windowed·비표준" 라벨 |
| B6 부호 통일 | ✅ | GEX/DEX/VEX/Charm 전부 "딜러 콜롱·풋숏" 하나로 |
| C1 proxy Strength 백분위 + midrank | ✅ | `compute_strength` 백분위 통과, `_rolling_percentile_score` midrank |
| C4 점수 CI 밴드 | ✅ | 각 지표 카드에 "62 ±6" (백분위 표본오차 95% 반폭) |
| C5 backtest 정합 | ✅ | `sentiment_prod`(Vol+P/C), `total6`(Credit제외) 측정 추가. VALIDATION.md 재생성 |
| C2 중복 신호 | ◐ | WORKPLAN Phase 2-2의 1:1 price:internals 재가중으로 이미 처리(Strength 25% weight). 상관행렬 리포트 병기. 추가 ERC는 보류 |
| C3 레짐 조건부 백분위 | ⏸ 보류 | 기능 추가라 회귀 위험. 레짐 의존성은 VALIDATION.md §3에 이미 분해 표기 |
| D3 분기 재실행 | ✅ (문서) | `python backtest.py` → VALIDATION.md 자동 갱신. 분기 1회 |

착수 전 스냅샷: `_backup_20260831/`.

---

## 2026-09-08 추가 — 기준일 일관성 + 내재배당 강건화

문제: `combined_main.py`가 탭마다 다른 기준일을 섞어 냈다(공포탐욕지수=T, 옵션=KRX 야간
배치 지연으로 T-1을 조용히 폴백). 또 만기주(잔존 <10일) 옵션에서 선물내재 q가
스냅샷 노이즈로 폭주(2026-09-07 정규월물 −47%).

| 작업 | 상태 | 내용 |
|---|---|---|
| E1 anchor 고정 | ✅ | `combined_main.py --as-of` — 리포트 전체를 한 거래일에 고정. `generate_fgi_section(as_of=)`가 지표 계열을 트레일링 컷. `generate_options_sections(require_exact=True)` |
| E2 엄격 게이트 | ✅ | anchor 당일 옵션 EOD 없으면 리포트 미생성 + `exit 3`. 폴백 없음. `reports/<d>.pending.json` 시도 기록 |
| E3 멱등 + 메타 | ✅ | 완결 리포트 있으면 AI 재호출 없이 종료. `reports/<d>.meta.json` 사이드카 |
| E4 스케줄러 | ✅ | `run_daily.ps1` 경계계산 제거(호출만). `register_task.ps1` 아침 트리거 06:00 → **07:30**(KRX 야간 배치 후) |
| E5 내재배당 q | ✅ | 풋-콜 패리티 내재 선도가(OptionMetrics/CBOE 방식, `implied_forward_from_chain`) 우선. 잔존<10일 & 만기 내 지수 배당락 없으면 상수 폴백. 타당 밴드는 배당락 유무로 가변(`dividends.INDEX_EXDIV_DATES`) |

변경 전 9/7 리포트 백업: `_backup_20260908/2026-09-07.html.pre-refresh` (9/4 옵션 기준 구본).

---

## Phase A — 데이터 스파인 (무료 내 최대화)

| # | 작업 | 근거 |
|---|---|---|
| A1 | 옵션·개별주식 섹션 spot을 네이버 종가 → **KRX Open API 지수/주가 종가**로 교체 | spot·futures가 같은 소스·같은 스냅샷이어야 basis(→ 내재 q) 오염 없음 |
| A2 | `dividends.py` 무료 배당 캘린더 손작성 (지수 배당락일 + 삼성/하이닉스 배당락일·주당 현금배당액, 연 1회 공시 기반 갱신) | 이산 배당(B1) 입력. 배당은 공시라 무료 |
| A3 | Strength/Breadth 히스토리 한계 **명시적 수용**: raw non-NaN 시작일 리포트 노출, 백분위 창 미충족 구간 `low_confidence=True` → 헤드라인·합성 제외 | KRX 전종목 시세 ~2020 무료 한계. 못 늘리므로 숨기지 않음 |

## Phase B — 옵션 모델 정밀화 (무료, 수학만)

| # | 작업 |
|---|---|
| B1 | 이산 배당: 만기 안에 배당락일 있으면 연속 q 대신 PV(현금배당) 스팟 차감 (A2 사용) |
| B2 | 장중 잔존만기: `days/365` → 시간 단위 `(만기 결제시각 − 기준일 15:30)/8760` |
| B3 | sticky-strike ↔ sticky-moneyness: GEX·Zero Gamma를 두 가정으로 계산해 밴드. 기존 r/q/IV 밴드와 합쳐 "모델오차" → "파라미터·가정 민감도" 재명명 |
| B4 | IV 스마일: 윙 flat 외삽 → 마지막 두 점 기울기 외삽. 같은 행사가 콜·풋 IV 공동 처리 |
| B5 | MaxPain: ±30% 윈도우 → "OI ≫ 최근 20일 거래량" 잔존분만 제외 + 전체 체인. ±20/30/40% 병기. 라벨 "windowed(비표준)" |
| B6 | DEX/GEX/VEX/charm 부호 규약 하나로 통일. 두 모델 다 보이려면 "시나리오 A/B". README "업계 표준 분리" 삭제 |

## Phase C — 합성지수 통계 (무료)

| # | 작업 |
|---|---|
| C1 | proxy Strength도 `_rolling_percentile_score` 통과. 백분위에 midrank |
| C2 | 중복 신호: Momentum·Strength 상관 기반 가중(ERC) 또는 Strength를 저변지표로 재분류. 문서화 |
| C3 | 레짐 조건부 백분위: VKOSPI 중앙값 고/저로 "같은 레짐 내 백분위" 병기(기본값 현행 유지) |
| C4 | 점수 오차밴드: 각 백분위 점수에 유한창 부트스트랩 CI → 카드 "62 (±N)" |
| C5 | `backtest.py`가 출시 지표 그대로 측정. `VALIDATION.md`에 mean(Vol,P/C)·6-way TOTAL 행 |

## Phase D — 검증 / 회귀 방지 (무료)

| # | 작업 |
|---|---|
| D1 | known-answer 테스트 스위트 (`tests/`): BS 그릭스 vs 유한차분, PoT vs 몬테카를로, MaxPain vs 완전탐색, McClellan vs 손계산 |
| D2 | 라벨 정합 일괄: Breadth "Oscillator"(Summation 아님), Put/Call "지수옵션 기반", PoT "위험중립" HTML에도, PCT_WINDOW/CREDIT_SPREAD_WINDOW 주석 fmkorea 문구 삭제, Volatility raw/score 구분, build_scenarios 보조 Wall 사용, dex_neutral near=spot, 25Δ RR 거리 가드, SYSTEM_PROMPT 문장수 통일, 위클리 파서 가드 |
| D3 | 분기 1회 `backtest.py` 재실행 절차 문서화 |

## 실행 순서

D1·D2 먼저 (회귀 방지) → A1·A3 → A2→B1 / B2 / B4·B5·B6 (병렬) → C5 → C1→C2→C3·C4

## 하지 말 것

1. 전종목 시세 2020년 이전 백필 시도 (무료 한계 · 스크래핑 리스크). A3로 정직 표기.
2. 일별 투자자 flow 자동화 (무료 없음). KB 수동 유지, override off.
3. 과거 옵션 체인 백테스트 (무료 히스토리 없음). 옵션 탭 = 당일 스냅샷.
4. fmkorea 수치 추격.

## 기대치

예측력 CI는 안 좁아진다 (데이터 자연 축적 필요). Phase A~D 성과는 "각 숫자가 물리적으로 정확해지고, 얼마나 못 믿을지가 숫자 옆에 붙는다"까지.
