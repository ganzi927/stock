# 20 · 코스피200 옵션 딜러 포지셔닝

담당 코드: `options_data.py`(체인·선물·금리), `greeks.py`(BS 그릭스·PoT),
`dealer_positioning.py`(레벨·프로파일·플로우), `options_main.py`(조립),
`options_charts.py`, `options_report.py`.

**정의.** KRX Open API가 주지 않는 델타/감마 등 그릭스를 IV 입력으로 직접 계산하고,
미결제약정(OI)에 곱해 딜러 헤지 흐름이 바뀔 수 있는 **레벨**을 뽑는다. 방향 예측이 아님.

---

## A. 옵션 체인 조회·파싱 (`options_data.fetch_option_chain`)

- 엔드포인트 `GET {BASE_URL}/drv/opt_bydd_trd?basDd=YYYYMMDD`,
  `BASE_URL = https://data-dbg.krx.co.kr/svc/apis`, 헤더 `AUTH_KEY: <KRX_API_KEY>`.
- 상품: `REGULAR_PROD = "코스피200 옵션"`, `WEEKLY_THU_PROD = "코스피200 위클리(목) 옵션"`.
- **REQ-OPT-1.** `ISU_NM`에 `"(정규)"` 포함 행만 사용(야간세션 중복 제거).
- **REQ-OPT-2 (파싱 정규식).** 행사가는 `[\d,]+(?:\.\d+)?` — 천단위 콤마 허용 후
  `replace(",", "")` → float. (과거 `[\d.]+`라 지수 1,000 돌파 시 상위 행사가가 통째
  누락된 버그. 정규월물 행사가 개수 532 → 1,012로 정상화.)
- 만기: `_nth_weekday(y, m, weekday=3, n=2)` = 해당월 **2번째 목요일**(정규),
  위클리는 `n = W숫자`번째 목요일.
- **REQ-OPT-3 (만기 선택).** `expiry > as_of` 인 시리즈만 남기고(T-0·만료 제외 —
  IV·그릭스 붕괴), 그중 **가장 가까운 만기** 하나만 사용.
- 출력 컬럼: `type`(C/P), `strike`, `expiry`, `iv`(%), `oi`, `volume`, `close`,
  `next_settle`.
- `KRX_API_KEY` 없으면 빈 DataFrame.

---

## B. spot / r / q 결정

### spot
**REQ-OPT-4.** spot은 KRX 선물 응답의 `SPOT_PRC`(`fetch_kospi200_spot`) — 선물 가격과
**같은 스냅샷**. 실패 시 네이버 지수종가로 폴백. (basis → 내재 q 오염 방지, WORKPLAN2 A1.)

### r (무위험이자율)
**REQ-OPT-5.** `fetch_risk_free_rate` — "3개월무위험금리 선물"의 최근월물 `SPOT_PRC`
로부터 `r = (100 − SPOT_PRC)/100`. `0 < r < 0.15` 아니면 `None`.
- `None`이면 `RISK_FREE_RATE = 0.030` 상수. 라벨 `(시장)` / `(가정)`.

### q (배당수익률) — `options_main._resolve_rq`
**REQ-OPT-6.** 다음 순서로 결정하고 `q_source ∈ {"패리티내재","선물내재","가정"}`를 기록:
1. **풋-콜 패리티 내재 선도가** `F*` (`implied_forward_from_chain`): 등가격 `±atm_band
   = 7.5%` 행사가들의 `C−K` 대 `K` 선형회귀 → `slope ≈ −e^(−rT)`, `F* = −절편/기울기`.
   행사가 4개 미만이거나 회귀 불안정(`|slope/(−disc) − 1| > 0.10`)이면 최근접 ATM 단일
   행사가 공식. → `q = r − ln(F*/S)/T`, source `"패리티내재"`.
2. 실패 시 옵션 만기에 근접(±10일)한 **선물 종가**로 `implied_dividend_yield`
   (`F = S·e^((r−q)T)` 역산). source `"선물내재"`.
3. **잔존만기 < 10일 AND 만기 내 지수 배당락일 없음**이면 상수 `DIVIDEND_YIELD = 0.015`
   ("가정"). 짧은 T 탓에 연율화 q가 스냅샷 노이즈로 폭주하기 때문
   (예: 2026-09-07 만기주 선물기준 −47%).
4. **타당 밴드** 벗어나면 상수. 밴드는 만기 내 지수 배당락(`dividends.INDEX_EXDIV_DATES`)
   유무로 가변: 배당락 있으면 `[−0.50, 0.50]`(연말 배당 몰림 → 연율 15~40% 정상),
   없으면 `[−0.02, 0.06]`(KOSPI200 상시 수준).

---

## C. Black-Scholes 그릭스 (`greeks.compute_greeks`)

- Merton 연속배당 모형. `d1 = (ln(S/K) + (r − q + σ²/2)T) / (σ√T)`, `d2 = d1 − σ√T`.
  `σ` clip [1e-4, ∞), `T` clip [1e-6, ∞).
- `delta` = `e^(−qT)·N(d1)` (콜) / `e^(−qT)·(N(d1) − 1)` (풋).
- `gamma` = `e^(−qT)·φ(d1) / (S·σ·√T)`.
- `vega` = `S·e^(−qT)·φ(d1)·√T / 100` (IV **1%p** 변화당).
- `vanna` = `−e^(−qT)·φ(d1)·d2 / σ / 100` (IV 1%p당 델타 변화).
- `theta` = 표준 콜/풋 식 `/ 365` (하루당).
- `charm` = 표준 콜/풋 식 `/ 365` (하루 경과당 델타 변화).
- `CONTRACT_MULTIPLIER = 250_000` (KOSPI200 옵션 1계약 25만원).

**REQ-OPT-7 (IV 스마일 채움, `fill_iv_smile`).** 결측/≤0 IV는:
1. 같은 행사가 반대 타입에 관측 IV 있으면 복사(풋콜 IV 동일 원칙).
2. 타입별 스마일을 log-moneyness 축에서 선형보간, **윙은 마지막 두 점 기울기로 외삽**
   (flat 아님 — 딥OTM 풋 IV 과소평가 방지). IV clip [1e-3, 5.0].
3. 최후수단: 전체 중앙값.

**REQ-OPT-8 (잔존만기).** `T = max((expiry − as_of).days, 0.25) / 365`. KRX 종가결제·
EOD 데이터라 close-to-close ACT/365가 정확 — 장중 분수 보정 없음.

---

## D. 부호 규약 — INV-OPT-1

**하나의** 딜러 인벤토리 모델: **딜러 콜 롱 · 풋 숏** (`+1` 콜 / `−1` 풋).
GEX·DEX·VEX·Charm 전부 동일 적용. SqueezeMetrics / SpotGamma / FlashAlpha `$DEX` 표준.

- **⚠ KRX에서 검증 불가.** KB증권 '금융투자'(딜러 근사) 데이터는 콜·풋 모두 순매수(롱)로
  반대를 시사. 딜러 실제 방향성 포지션은 미국시장에서도 비공개(SpotGamma DDOI) — 검증
  불가능한 모델링 관행이다.
- **불변**: Zero Gamma / Call Wall / Put Wall / DEX Neutral의 **위치**는 전역 부호 반전에
  불변("OI·감마가 집중된 레벨"로는 읽을 수 있음).
- **가변**: "Zero Gamma 위=안정 / 아래=가속" 같은 **국면 해석**과 Net GEX/DEX/Vanna/Charm
  헤드라인의 **부호·크기**는 규약이 뒤집히면 통째로 반대.
- 리포트/AI는 방향 단정 없이 레벨·수치로만 제시하고 `SIGN_CONVENTION_CAVEAT`를 병기한다.
- `sign_overrides`(행사가별 KB 실제 부호)는 코드에 존재하나 **기본 OFF**
  (`options_main.generate_options_sections`에서 `sign_overrides=None` 고정). 켜면 fmkorea
  원본 대비 Zero Gamma 오차가 0.3% → 56%로 악화됨(2026-08-26 검증).

---

## E. 계약별 익스포저 (`with_greeks_at_spot`)

`sign` = 부호 규약(또는 override). `mult` = `CONTRACT_MULTIPLIER`.
- `dex` = `sign · oi · delta · mult · spot`
- `gex` = `sign · oi · gamma · spot² · 0.01 · mult`
- `vex` = `sign · oi · vanna · mult · spot`
- `charm_exp` = `sign · oi · charm · mult · spot`

DEX/VEX/Charm에 `spot`을 곱해 **명목가치(통화 단위)**로 만든다(승수 작은 개별주식에서
0.0 반올림 방지). 종목 간 절대 크기 비교는 무의미 — 자기 히스토리 대비로만.

---

## F. 레벨 (`dealer_positioning.analyze` → `Levels`)

### 그리드
`_oi_weighted_strike_range` = OI 누적 [2%, 98%] 구간 → `active_min/max`.
`grid_lo = min(spot·0.85, active_min·0.97)`, `grid_hi = max(spot·1.15, active_max·1.03)`,
`np.linspace(grid_lo, grid_hi, 141)`.

### Zero Gamma
`gex_profile`(가상 스팟마다 Net GEX 합) → `_interp_zero_cross(near=spot)` = 0 교차 중
**스팟에 가장 가까운** 것. 교차 없으면 `None`(억지 값 금지).

**REQ-OPT-9 (민감도 밴드).** `zero_gamma_lo / hi` = 아래 섭동에서 나온 Zero Gamma
샘플의 min/max:
- `r ± 25bp`, `q ± 100bp`, `IV × 0.95 / 1.05`, `sticky-moneyness` 1샘플
  (`iv_sticky_moneyness=True`, 스마일이 스팟 따라 평행이동).
- 기본은 sticky-strike(행사가별 IV 고정). 표기: `"1,049.9 (민감도 1,043~1,058)"`.

### MaxPain (`compute_max_pain`) — windowed·비표준
- **REQ-OPT-10.** 스팟 `±moneyness_range = 30%` 안의 행사가·계약만 사용. 후보가 3개
  미만이면 `±50%`로 한 단계 확장.
- `_drop_stale_oi`: 딥(±15% 밖) 행사가 중 `oi > STALE_OI_VOL_MULT(200) · max(volume,1)`
  는 "방치 잔존분"으로 제외(SK하이닉스 1,050,000 콜 72,007계약 / 당일 16계약 사례).
- 각 후보 K에 대해 `Σ call_oi·max(K−Kc,0) + Σ put_oi·max(Kp−K,0)` 최소점.
- `max_pain_20 / max_pain_40` = `±20% / ±40%` 병기(민감도). 라벨 "windowed(비표준)".

### Call Wall / Put Wall (`find_walls`)
- **REQ-OPT-11.** 스팟 `±moneyness_range = 30%` 안에서만 탐색.
- `call_wall` = 콜 옵션만의 GEX 합이 최대인 행사가.
- `put_wall` = 풋 옵션만의 GEX 합의 **절대값**이 최대인 행사가.
- 스팟 위/아래 방향 무관(SpotGamma/FlashAlpha 정의).
- `call_wall_above` = 스팟 **위** 콜 GEX 최대(상단 Gamma Wall),
  `put_wall_below` = 스팟 **아래** |풋 GEX| 최대(하단 Gamma Wall). 전역 wall과 같으면
  `None`(중복 방지).

### DEX Neutral MaxPain
`dex_profile` → `_interp_zero_cross(near=spot)` = Net DEX 0 교차(스팟 근방). 자체 정의
(표준 용어 아님), 전역 부호 반전에 불변.

---

## G. 파생 지표

**REQ-OPT-12 (PoT, `greeks.probability_of_touch`).** 만기 전 스팟이 barrier를 한 번이라도
터치할 **위험중립** 확률. 드리프트 있는 BM first-passage(반사원리), 드리프트
`μ = r − q − σ²/2`, `σ` = ATM IV. 검증: `μ=0`이면 `2·N(−|b|/(σ√T))`로 축약.
- 리포트/AI는 반드시 "위험중립(옵션 가격에 내재된) 확률"로 성격을 밝히고 실제 도달
  확률로 단정하지 않는다.

**REQ-OPT-13 (25델타 Risk Reversal, `risk_reversal_25d`).** `25Δ 콜 IV − 25Δ 풋 IV`.
정확히 0.25인 행사가가 없으므로 델타 최근접 행사가 사용 — 단 델타가 0.25에서
`RR_DELTA_TOL = 0.10` 이상 벗어나면 그 leg은 `None`.

**REQ-OPT-14 (positioning_skew).** OI/거래량 기준 콜/풋 쏠림.
`skew = (call − put)/(call + put)`, `oi_pcr = put_oi/call_oi` 등. 25Δ RR(변동성 스큐)과
**다른 축** — 둘이 반대로 나올 수 있고 모순 아님.

**REQ-OPT-15 (합성지수, `synthetic_forward_by_strike`).**
`S = (C − P + K·e^(−rT))·e^(qT)` — 콜·풋 종가가 둘 다 있는 행사가에서 내재 스팟 역산.
실제 스팟과 괴리 = 그 행사가 근방 고평가/저평가.

**REQ-OPT-16 (IV Rank).** ATM IV를 `cache/atm_iv_regular.csv` / `atm_iv_weekly.csv`에
증분 저장하고 그 히스토리의 `_rolling_percentile_score` 최신값. 캐시 초기 며칠은 의미 약함.

---

## H. 시나리오 (`build_scenarios`)

**REQ-OPT-16.** `build_scenarios`는 호환 함수명을 유지하되 관측 레벨 목록을 반환한다.
각 항목은 `name`, `value`, `distance_pct`, `position`, `definition`, `limitation`이다.
유한한 Call/Put Wall·상하단 Wall·Zero Gamma·부분/전체 MaxPain을 보존하고,
종가 대비 위치를 계산한다. Trigger/Target/가격 무효화 계약은 제거한다.
요약·상세·연구 AI·outlook 소비부는 동일 계약을 사용한다.
MaxPain은 최소 내재가치 통계량으로 표시하고 가격 유지·이탈 조건을 붙이지 않는다.
**AC-OPT-10.** 종가 175만원·MaxPain 130만원·Put Wall 170만원 fixture에서도
130만원 값과 종가 아래 위치가 유지되며 상충하는 유지/이탈 조건은 생성되지 않는다.

---

## I. 실행 흐름 (`options_main.generate_options_sections`)

- `require_exact=True`(combined_main): `as_of` 이하 마지막 거래일 옵션 EOD가 없으면
  `([], anchor, False, [])` 반환 → 호출측 생성 중단. **walk-back 안 함.**
- `require_exact=False`(standalone): 최근 영업일부터 5일 walk-back.
- 정규월물 + 위클리(목) 두 섹션. 각 섹션 `expiry_label` = `"기준일 <as_of> · 만기
  <expiry> (T-<days>) · r=..(시장|가정) · q=..(패리티내재|선물내재|가정)"`.
- KB 투자자별 순매수(`uploads/`)가 있으면 AI 코멘트용 사실 문장으로만 요약(계산 미반영).

---

## J. 수용 기준

- **AC-OPT-1.** `tests/test_math.py::test_greeks_vs_fd` — delta/gamma/vega/theta/vanna/
  charm이 중심 유한차분과 rel 1e-3~2e-3 이내(콜·풋 모두).
- **AC-OPT-2.** `test_greeks_call_put_parity` — `delta_c − delta_p = e^(−qT)`,
  gamma/vega/vanna 콜=풋.
- **AC-OPT-3.** `test_pot_driftless_reduction` (`μ=0` → `2N(−|b|/σ√T)`, rel 1e-9) +
  `test_pot_vs_montecarlo` (해석해 vs MC ±3%p).
- **AC-OPT-4.** `test_maxpain_clean_chain_matches_bruteforce` — 잔존 OI 없는 깨끗한
  체인에서 windowed MaxPain == 완전탐색(±2.5).
- **AC-OPT-5.** `test_synthetic_forward_roundtrip` — BS 가격으로 만든 체인에서 모든
  행사가 내재 스팟 ≈ 실제 스팟(1e-6).
- **AC-OPT-6 (⚠ 미검증).** GEX/DEX/VEX/Charm 부호·크기는 실측 대조 불가 — 업계 관행이며
  "검증된 사실" 아님. fmkorea 원본과의 Zero Gamma 근접도(정규월물 2026-08-26: 1,049.9 vs
  1,046.4, 0.3%)가 유일한 정성 참조점.
- **AC-OPT-7.** `expiry_label`의 r/q 소스 태그가 실제 사용 경로와 일치.

---

## K. 미해결 / 한계

- KRX Open API에 옵션 투자자유형별 데이터 없음 → 딜러 인벤토리 부호는 영구 가정.
- 과거 옵션 체인 히스토리 무료로 없음 → 옵션 탭은 당일 스냅샷 only, 백테스트 불가.
- IV Rank 캐시는 신규 축적 중이라 초기 백분위 의미 약함.

## 2026-09-15 근거 감사 정정 (기존 충돌 문구보다 우선)
- REQ-OPT-3: 미래 만기가 없으면 빈 체인을 반환한다. 만료 체인 폴백 금지.
- REQ-OPT-7: IV 컬럼 단위는 퍼센트(20=20%). 기존 소수 기준 clip [0.001,5]를 퍼센트 [0.1,500]으로 환산한다. 이것은 유효성 보장이나 검증된 외삽법이 아니다. 보간/외삽 선택은 기존 가정으로 유지한다.
- REQ-OPT-12: compute_greeks는 유한 양수 S/K/T/sigma와 유한 r/q만 허용하며 잘못된 입력은 ValueError. 서로 다른 floor를 공식 일부에만 적용하지 않는다.
- REQ-OPT-13: sticky-moneyness 프로파일은 실제 관측 spot을 기준으로 스마일을 이동한다. 그리드 중앙값을 관측 spot으로 간주하지 않는다.
- REQ-OPT-10: 거래량 대비 OI 비율만으로 유효 계약을 삭제하지 않는다. 기존 windowed 값은 비표준으로 유지하고, 전 행사가·계약 기준 max_pain_full을 함께 제공한다. 두 값 모두 만기 가격 예측이 아니다.
- REQ-OPT-11: Wall은 타입별 |GEX| 합 최대점이다. 부호 반전으로 콜 Wall이 사라지지 않는다.
- INV-OPT-1 정정: 순매매(flow)는 미결제 순포지션(stock)을 식별하지 못한다. 전역 부호 반전만 영점 위치를 보존하며 개별 계약 부호 변경은 위치도 바꾼다. OI만으로 실제 딜러 헤지량·방향은 식별 불가.
- REQ-OPT-14: 시나리오는 관찰 레벨만 설명한다. Call Wall 돌파=매수 헤지, Zero Gamma 아래=short gamma, MaxPain 수렴을 자동 추론하지 않는다.
- AC-OPT-8: 만료 전용 응답, 20/30% 사이 IV 보간, 비대칭 그리드의 관측 spot, 부호 반전 Wall, 전 행사가 MaxPain, 고OI·저거래량 계약 보존을 회귀 검증한다.

- REQ-OPT-15: IV 캐시는 미래 데이터를 보존하되 백분위 계산은 date<=as_of로 제한한다. 출력명은 IV Percentile이며 최저/최고 기반 IV Rank와 구분한다.
- AC-OPT-9: 미래 IV 캐시 추가 전후 동일 as_of 백분위가 일치한다.
