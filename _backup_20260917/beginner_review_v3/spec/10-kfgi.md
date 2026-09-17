# 10 · KFGI — 한국형 공포탐욕지수

담당 코드: `indicators.py`(계산), `main.generate_fgi_section`(조립),
`ecos_data.py` / `krx_api.py` / `krx_market.py` / `naver_data.py`(입력).

**정의.** KFGI = CNN Fear & Greed Index의 한국판. 구성요소 7개, raw 정의는 CNN + fmkorea
05-13/05-20 원본 + 업계 표준(StockCharts McClellan 등)에 맞췄다. 점수↑ = 탐욕, 점수↓ = 공포.

> `RECONCILIATION.md §5`는 조사 당시(504일 창, Volatility 50일MA, Breadth Summation
> Index) 사양이다. **아래는 현행 코드 기준**이며, 세 항목은 대형주 전술 readout 목적상
> 의도적으로 이탈했다(`indicators.py` docstring 참조).

---

## A. 점수화 — 전 지표 공통

**REQ-KFGI-1.** 모든 raw 계열은 `_rolling_percentile_score`로 0~100 점수화한다.

- 창 `PCT_WINDOW = 252` 거래일(약 1년). 튜닝값 아님 — CNN "최근 1년" 관행 + 롤링 백분위
  표준 lookback.
- 각 시점 점수 = 그 값이 직전 252거래일 안에서의 백분위(midrank: `(below + 0.5·equal)/(n-1)·100`).
  동점 계단함수(Credit 등)에서 극단에 달라붙지 않게 midrank 사용.
- `min_periods = max(MIN_PERIODS_FLOOR=60, PCT_WINDOW·MIN_PERIODS_FRAC=0.5) = 126`.
  창이 이만큼 안 차면 점수는 `NaN`(N/A).
- 공포 방향 지표(값↑ = 공포)는 `invert=True` → `score = 100 − pct`.

**REQ-KFGI-2 (as_of 트렁케이션).** `generate_fgi_section(as_of=...)`이면 모든 지표
DataFrame을 `date <= as_of`로 자른다. 컷은 롤링 계산 **이후** → 트레일링 창 정확,
look-ahead 없음.

---

## B. 7개 지표 사양

각 지표는 `IndicatorResult(name, raw, score, is_proxy, note, low_confidence,
scored_since, score_ci)`를 낸다. `raw`는 표시용, `score`가 합성 입력.

### 1. Momentum  (`compute_momentum`)
- raw = `close / SMA125(close)` (KOSPI200 종가, `SMA125` min_periods 20).
- `invert=False`. 프록시 없음(항상 real).
- 근거: CNN "Stock Price Momentum" = 지수/125일 MA 이격도.

### 2. Volatility  (`compute_volatility_real` / `_proxy`)
- **real**: 계열 = `VKOSPI`의 `VKOSPI_MA_DAYS = 20`일 이동평균(min_periods 10),
  `invert=True`. `raw` 컬럼 = 표시용 당일 VKOSPI.
- **proxy**(`vkospi` 캐시 비었을 때, `is_proxy=True`): 20일 실현변동성 연율화
  (`ret.rolling(20).std()·√252·100`), `invert=True`.
- 근거: CNN 원본은 VIX **50일** MA. 대형주 전술 반응성 위해 20일로 단축한 의도적 이탈
  (IC로 고른 값 아님).

### 3. Credit Spread  (`compute_credit_spread`) — 매크로 배경
- raw = `spread` = 회사채 BBB-(3Y) − 회사채 AA-(3Y) 수익률 (ECOS `817Y002`,
  `010320000` − `010300000`). `invert=True`(좁을수록 위험선호 = 탐욕).
- 창 `CREDIT_SPREAD_WINDOW = 252`.
- **REQ-KFGI-3.** `MACRO_BACKDROP = {"Credit Spread"}` — TOTAL·투심·추세 **어디에도
  넣지 않는다**. 카드로만 표시. 이유: (1) 2026년 BBB- 회사채 시장 동결 → 매트릭스
  프라이싱 계단함수(최근 252일 중 |Δ|>0.01인 날 11일), (2) 거시 변수이지 대형주
  세그먼트 심리 아님, (3) 백테스트 IC가 강하나 2020·2022 두 위기에 의존.
- `ECOS_API_KEY` 없으면 `None` → N/A.

### 4. Strength  (`compute_strength_real` / `compute_strength`)
- **real**: `strength_raw` = (52주 신고가 종목수 − 신저가 종목수) / 유효종목수 × 100,
  `STRENGTH_SMOOTH_DAYS = 5`일 평활 후 백분위. `invert=False`.
  - 유니버스/52주 판정은 `krx_market.compute_breadth_and_strength_raw`:
    `STRENGTH_WINDOW = 252`, `min_periods = 252`(진짜 52주 다 차야 인정),
    `STRENGTH_UNIVERSE_N = 200`(일자별 시총 상위 200 ≈ 코스피200). 창 미충족
    종목-일자는 집계 제외(가짜 0 아닌 NaN).
- **proxy**(시장 캐시 없을 때): 지수 자체의 252일 고저 구간 내 위치(%K) → 백분위.
- 근거: CNN "52주 신고가−신저가". 유니버스는 fmkorea "코스피200" 근사(대형주 목표).

### 5. Breadth  (`compute_breadth_real` / `compute_breadth_proxy`)
- **real**: `breadth_raw` = (상승종목 거래량 − 하락종목 거래량) / (상승+하락 거래량)
  ∈ [−1,1] (유니버스 = 시총 상위 200, `krx_market`), → McClellan **Oscillator**
  `EMA(BREADTH_EMA_FAST=19) − EMA(BREADTH_EMA_SLOW=39)` (adjust=False) → 백분위.
- **proxy**: `sign(Δclose)·volume`의 20일 합 → 백분위.
- **REQ-KFGI-4.** CNN "Stock Price Breadth"는 이 Oscillator를 **누적한 Summation
  Index**를 쓴다. 여기선 Summation이 비정상(누적)이라 캐시 시작일에 따라 분포가 표류하고
  백분위가 양극단에 달라붙어서, **준정상인 Oscillator 자체를 백분위**한다 — 의도적
  이탈, "CNN과 동일" 아님. 거래량 기반이라는 점은 동일.

### 6. Safe Haven Demand  (`compute_safe_haven`)
- raw = (KOSPI200 20일 수익률 − 채권 20일 수익률) × 100. `invert=False`(주식이 채권보다
  잘 나갈수록 탐욕).
- 채권 레그 = `ecos_data.synthetic_bond10y_index()` — 국고채 10년 금리 → 합성 총수익
  지수(수정듀레이션 `BOND10Y_DURATION = 8.5`). ECOS 키 없으면 KOSEF 148070 ETF 캐시로
  폴백(`BOND_ETF_CODE`, 히스토리 짧음 — cross-check용).
- 근거: CNN "Safe Haven Demand" = 주식 20일 − 국채 20일 수익률.

### 7. Put/Call Ratio  (`compute_putcall_real`)
- 표시 raw = 코스피200 옵션 정규세션 당일 `put_vol / call_vol`.
  점수 입력은 이 비율의 `PUTCALL_MA_DAYS = 5`일 이동평균이며 `invert=True`.
  거래량비는 순매수 또는 투자자 의도를 식별하지 못한다.
- 근거: CNN "5일 평균 P/C". CNN은 개별주 P/C지만 한국엔 없어 지수옵션으로 대체 —
  기관 헤지 지배로 신호가 약함(note에 명시).
- `KRX_API_KEY` 없으면 `None` → N/A.

---

## C. 합성 지수

**REQ-KFGI-5 (합성 자격).** `_composite_eligible(r)` = `r.score is not None` **AND**
`r.name not in MACRO_BACKDROP` **AND** `not r.low_confidence`.

- `low_confidence` = 점수화된 표본 수 `n_scored < PCT_WINDOW(252)`. 백분위 기준 분포가
  얇아 시점 간·지표 간 비교 불안정 → 합성 제외 + 카드 표기.
  (2026-09 현재 미발동: Strength 2022~, Breadth 2021~.)

**REQ-KFGI-6 (TOTAL).** `total_fgi` = 합성 자격 지표 score의 **등가중 평균**. "참고용
CNN 비교값"이며 리포트 헤드라인이 아니다("25 미만이면 매수"식 사용 금지).

**REQ-KFGI-7 (서브지수, `subindices`).**
- **투심지수 sentiment** = `mean(Volatility, Put/Call Ratio)`. 점수↑ = 평활 변동성·
  풋콜 거래량비가 각자의 과거 대비 낮음. 구성별 수준이 다를 수 있으며 실제 헤지수요를 뜻하지 않는다.
- **추세지수 trend** = `mean( Momentum, mean(Strength, Breadth) )`.
  가격추세:시장저변 = **1:1** 가중(Momentum과 거의 중복인 Strength가 2/3을 먹지
  않도록). 가용한 것만 평균.
- `SENTIMENT_INDICATORS = {"Volatility", "Put/Call Ratio"}`,
  `TREND_INDICATORS = {"Momentum","Strength","Breadth"}`,
  `TREND_PRICE = {"Momentum"}`, `TREND_INTERNALS = {"Strength","Breadth"}`.

**REQ-KFGI-8 (점수 CI).** `score_ci` = `1.96·√(p(1−p)/n_eff)·100` (점 단위),
`p = score/100`, `n_eff = min(n_scored, 252)`. 카드에 "62 ±6" 형태로 병기.

**REQ-KFGI-9 (상관행렬).** `subscore_correlations` — score 시계열 피어슨 상관행렬
(겹치는 구간, 최소 60일). 등가중이 "중립적"이라는 전제를 검증 가능하게 리포트에 병기.

**REQ-KFGI-10 (TOTAL 추이).** 최근 60거래일 TOTAL 추이는 일자별로 각 지표 score를
평균하되 `credit_spread` 컬럼을 제외(= `total_fgi`와 동일 규약).

---

## D. 방향성 — 예측 단정 금지

백테스트(`backtest.py` / `VALIDATION.md`)상:
- 파생 지표(Volatility·Put/Call)는 **역행**(공포↑ → 이후 수익률↑) 기대. 단독 CI는
  대체로 0을 걸침.
- 가격·저변(Momentum·Strength·Breadth)은 **순행**. Momentum만 +60/120일에서 겨우 0을
  벗어남. Strength·Breadth는 전부 0 포함.
- 단일 TOTAL은 두 신호가 상쇄 — 7/7 구간 전 시계 CI가 0 포함. **타이밍 신호 아님.**
- **REQ-KFGI-11.** 리포트·AI 코멘트는 "이 조합이면 오른다/내린다", "수익률이 좋았다"
  식 서술을 하지 않는다. 현재 상태 readout만.

---

## E. 수용 기준

- **REQ-KFGI-14 / AC-KFGI-9.** 설명은 일반 백분위와 `100−백분위` 역산 점수를 구분한다.
  역산 20점이면 평활 원자료가 과거 대비 높은 쪽임을 설명하고 투심 구성별 점수 차이를 표시한다.
  P/C 당일 raw와 MA5 점수 입력을 구분한다. Strength real은 신고가−신저가 비율의 5일 평활,
  proxy는 지수의 252일 고저 범위 내 위치이며 이를 상승·하락 종목 규모라고 쓰지 않는다.

- **AC-KFGI-1.** `tests/test_math.py::test_percentile_score_monotone_and_invert` —
  순증가 시리즈 최근값 ≈ 상위(>95), `invert` = `100 − 정방향`(겹치는 구간 오차 1e-9),
  범위 [0,100].
- **AC-KFGI-2.** `tests/test_math.py::test_mcclellan_oscillator_by_hand` —
  `BREADTH_EMA_FAST=19`, `BREADTH_EMA_SLOW=39`, `pandas ewm(adjust=False)` == 손계산
  재귀 EMA.
- **AC-KFGI-3.** TOTAL·투심·추세는 `Credit Spread`를 절대 포함하지 않는다
  (`indicators._composite_eligible` + `main.py` `score_cols` 필터). 회귀 시
  `backtest.py`의 `SIX`/`SENTIMENT_PROD` 정의와 정확히 일치해야 한다.
- **AC-KFGI-4.** `low_confidence` 지표는 `total_fgi`·`subindices` 결과에 반영되지
  않는다.
- **AC-KFGI-5 (예측력, `VALIDATION.md`).** 분기 1회 `python backtest.py` 재실행.
  단조성: 투심 분위-수익률 ρ ≈ −1.0, 추세 ρ ≈ +0.8 유지가 정성 기준. IC CI가 0을
  걸치는 항목은 "방향성 있음"으로 쓰지 않는다.

---

## F. 미해결 / 한계

- KOSPI200 정확한 구성종목 불가(KRX 로그인 요구) → 시총 상위 200 근사(~90%+ 겹침).
- Breadth·Strength 전종목 히스토리 하한 2020-09(KRX Open API 무료 한계). 7개 지표가
  전부 존재하는 구간 ≈ 2021-09~ (`DATA_INVENTORY.md`).
- KOSDAQ 미편입(`ksq_bydd_trd` 이용신청 안 함) → KOSPI만.
- 정규화 창 252는 fmkorea 명시값. 189~378 튜닝 여지는 미실시.

## 2026-09-15 근거 감사 정정 (기존 충돌 문구보다 우선)
- REQ-KFGI-8: 자기상관·평활을 무시한 이항식은 점수의 95% CI로 쓸 수 없다. 검증된 추정법 선정 전 score_ci=None; CI를 만들어 표시하지 않는다.
- REQ-KFGI-12: Breadth는 한쪽 등락 거래량이 없는 날 그쪽 합을 0으로 정렬한다. 양쪽 합이 0인 날은 NaN이다.
- AC-KFGI-6: 전 종목 상승/하락일의 breadth_raw는 각각 +1/-1, 전 종목 보합일은 NaN이다.
- AC-KFGI-7: 점수 시계열이 있어도 score_ci는 None이다.

- REQ-KFGI-13: 백분위 분모에는 유한 관측값만 포함한다. 최신 값 결측이면 점수도 NaN. 이전 값 결측을 낮은 순위로 간주하지 않는다.
- AC-KFGI-8: NaN이 섞인 상수 창은 50점, 현재값 NaN은 NaN, 상승 창의 최대값은 100점이다.
