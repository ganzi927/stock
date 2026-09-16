# 99 · 용어 · 부호 규약 · 단위

---

## KFGI

| 용어 | 정의 |
|---|---|
| **KFGI** | 한국형 공포탐욕지수. CNN Fear & Greed Index의 한국판. 0~100, 높을수록 탐욕. |
| **raw** | 지표의 원값(이격도·스프레드·비율 등). 표시용. |
| **score** | raw를 직전 252거래일(`PCT_WINDOW`) 백분위로 0~100 변환한 값. 합성 입력. |
| **invert** | 공포 방향 raw(값↑ = 공포)를 `100 − 백분위`로 뒤집는 것. Volatility·Put/Call·Credit. |
| **proxy / is_proxy** | API 키가 없어 근사식으로 대체한 지표(Volatility·Strength·Breadth). |
| **low_confidence** | 점수화 히스토리 < 252일. 합성에서 제외, 카드엔 표기. |
| **MACRO_BACKDROP** | 합성(TOTAL·투심·추세)에서 빼고 배경으로만 보는 지표 = Credit Spread. |
| **추세지수(trend)** | `mean( Momentum, mean(Strength, Breadth) )`. 가격추세:시장저변 1:1. 순행 기대. |
| **투심지수(sentiment)** | `mean(Volatility, Put/Call Ratio)`. 역행 지표. 점수↑ = 안심/방심. |
| **score_ci** | 백분위 점수의 표본오차 95% 반폭. `1.96·√(p(1−p)/n_eff)·100`. |
| **McClellan Oscillator** | `EMA19 − EMA39` (여기선 ratio-adjusted net advancing volume에 적용). CNN의 Summation Index는 **안 씀**(의도적). |

---

## 옵션

| 용어 | 정의 |
|---|---|
| **spot** | 기초자산 현재가. 옵션 섹션은 KRX 선물 응답의 `SPOT_PRC`(동일 스냅샷). |
| **r** | 무위험이자율. 3개월무위험금리 선물 `SPOT_PRC` → `(100−x)/100`, 실패 시 3.0% 가정. |
| **q** | 배당수익률. 패리티내재 → 선물내재 → 상수(1.5% 지수 / 종목별 개별주식) 순. |
| **T** | 잔존만기(연). `max((expiry − as_of).days, 0.25) / 365`. ACT/365 close-to-close. |
| **GEX** | Gamma Exposure. `sign · OI · Γ · spot² · 0.01 · multiplier`. |
| **DEX** | Delta Exposure(명목가치). `sign · OI · δ · multiplier · spot`. |
| **VEX** | Vanna Exposure. `sign · OI · vanna · multiplier · spot`. |
| **Charm Flow** | `sign · OI · charm · multiplier · spot`. 하루 경과당 델타 명목가치 변화. |
| **Zero Gamma / Gamma Flip** | 합산 GEX 프로파일이 부호를 바꾸는(0 교차) 지점. 스팟 근방 크로스. |
| **Call Wall** | 콜 옵션만의 GEX 합이 최대인 행사가(스팟 위/아래 무관). |
| **Put Wall** | 풋 옵션만의 |GEX| 합이 최대인 행사가. |
| **상/하단 Gamma Wall** | `call_wall_above` / `put_wall_below` — 스팟 위/아래로 제한한 변형. |
| **MaxPain** | 만기 결제가 가정 시 콜+풋 내재가치 총합이 최소인 행사가. 여기선 스팟 ±30% windowed(비표준). |
| **DEX Neutral MaxPain** | Net DEX 프로파일의 0 교차. 자체 정의, 전역 부호 반전에 불변. |
| **PoT (Probability of Touch)** | 만기 전 barrier를 한 번이라도 터치할 **위험중립** 확률. 실제 확률 아님. |
| **25Δ Risk Reversal** | `25델타 콜 IV − 25델타 풋 IV`. 변동성 스큐. |
| **positioning_skew** | OI/거래량의 `(call − put)/(call + put)`. RR과 **다른 축**. |
| **합성지수(synthetic forward)** | `S = (C − P + K·e^(−rT))·e^(qT)` — 행사가별 내재 스팟. |
| **sticky-strike / sticky-moneyness** | 스팟 이동 시 IV를 행사가에 고정 / 스마일을 스팟 따라 평행이동. 둘의 Zero Gamma 차이가 민감도 밴드. |

---

## 부호 규약 — INV-OPT-1

**딜러 콜 롱 · 풋 숏** (`+1` 콜 / `−1` 풋). GEX·DEX·VEX·Charm 전부 동일.
SqueezeMetrics / SpotGamma / FlashAlpha `$DEX` 표준.

- **⚠ KRX에서 검증 불가.** KB증권 '금융투자' 데이터는 반대(콜·풋 모두 순매수)를 시사.
  딜러 실제 포지션은 미국시장에서도 비공개(SpotGamma DDOI).
- **부호 반전에 불변**: Zero Gamma / Call Wall / Put Wall / DEX Neutral의 **위치**.
- **부호 반전에 가변**: 국면 해석("위=안정/아래=가속")과 Net 익스포저의 **부호·크기**.
- `SIGN_CONVENTION_CAVEAT` 문자열을 리포트/프롬프트에 병기.

---

## 단위

- 그릭스: `vega`·`vanna`는 IV **1%p** 변화당(`/100`). `theta`·`charm`은 **하루**당(`/365`).
- IV: 코드 내부는 소수(0.20), 체인 컬럼·표시는 % (20.0).
- Net DEX/VEX/Charm: 통화 명목가치(원). 리포트는 억/조 단위로 축약.
- `CONTRACT_MULTIPLIER = 250_000` (KOSPI200 옵션). 개별주식은 종목명에서 파싱(현재 10).

---

## exit code

| 심볼 | 값 | 의미 |
|---|---|---|
| `EXIT_OK` | 0 | 완결 생성 또는 멱등 종료 |
| `EXIT_NO_PRICE` | 2 | anchor 시세 없음 |
| `EXIT_OPTIONS_PENDING` | 3 | 옵션 EOD 미게시 (정상 흐름, run_daily가 0으로 매핑) |

---

## 파일·경로

| 이름 | 내용 |
|---|---|
| `reports/<anchor>.html` | 운영 통합 리포트(탭 4개) |
| `reports/<anchor>.meta.json` | 완결 사이드카(멱등 가드가 `options_complete` 확인) |
| `reports/<anchor>.pending.json` | 게이트 미통과 시도 기록 |
| `reports/options-<date>.html` / `stock-options-<date>.html` | 단독 실행 산출물 |
| `cache/*.csv` | 일별 시세·지표 raw 캐시(증분) |
| `uploads/*.xlsx` | KB증권 수동 다운로드(투자자별 순매수) |
| `_backup_YYYYMMDD/` | 주요 변경 전 스냅샷 |
