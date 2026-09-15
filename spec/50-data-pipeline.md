# 50 · 데이터 파이프라인

담당 코드: `naver_data.py`, `krx_api.py`, `krx_market.py`, `ecos_data.py`,
`options_data.py`(선물·금리 부분), `dividends.py`. 상세 인벤토리는
`DATA_INVENTORY.md`(시작일·품질 한계).

---

## A. 소스 매핑

| 데이터 | 소스 | 인증 | 캐시 파일 |
|---|---|---|---|
| KOSPI / KOSPI200 일별 시세 | 네이버 금융 `sise_index_day` | 없음 | `cache/kospi.csv`, `cache/kospi200.csv` |
| 국고채10년 ETF(KOSEF 148070) | 네이버 금융 `item/sise_day` | 없음 | `cache/bond10y.csv` (참고용 cross-check) |
| VKOSPI | KRX Open API `idx/drvprod_dd_trd` ("변동성지수") | `KRX_API_KEY` | `cache/vkospi.csv` |
| 옵션 풋/콜 비율 | KRX `drv/opt_bydd_trd` ("코스피200 옵션" 거래량 PUT/CALL) | `KRX_API_KEY` | `cache/putcall.csv` |
| 전종목 시세 (KOSPI[+KOSDAQ]) | KRX `sto/stk_bydd_trd` [`sto/ksq_bydd_trd`] | `KRX_API_KEY` | `cache/market_kospi.csv` |
| 옵션/개별주식옵션 체인 | KRX `drv/opt_bydd_trd` / `drv/eqsop_bydd_trd` | `KRX_API_KEY` | (캐시 안 함 — 당일 스냅샷) |
| 코스피200 선물 / 3M 무위험금리 선물 | KRX `drv/fut_bydd_trd` | `KRX_API_KEY` | (캐시 안 함) |
| 신용스프레드 BBB-−AA- (3Y) | ECOS `817Y002` (`010320000` − `010300000`) | `ECOS_API_KEY` | `cache/credit_spread.csv` (`spread`, `spread_a`) |
| 국고채 10년 금리 | ECOS `817Y002` (`010210000`) | `ECOS_API_KEY` | `cache/bond10y_yield.csv` |
| ATM IV 히스토리 | 파생(자체 축적) | — | `cache/atm_iv_{regular,weekly,005930,000660}.csv` |
| KB증권 투자자별 순매수 | 수동 다운로드 | — | `uploads/*.xlsx` |
| fmkorea "오늘의 코스피" 로그 | 수동/LLM | — | `cache/fmkorea_log.csv` |

KRX 운영 엔드포인트: `BASE_URL = https://data-dbg.krx.co.kr/svc/apis`, 헤더 키
`AUTH_KEY`. (문서 페이지의 "샘플 테스트"는 별도 데모키 엔드포인트 — 내 키는 401이 정상.)

---

## B. 캐시 갱신 규약

**REQ-DATA-1 (네이버, `naver_data.update_cache`).** "오늘" 행은 장중 실시간 스냅샷이라,
캐시 존재 여부와 무관하게 **항상 최근 ~30일을 다시 받아 겹치는 날짜를 덮어쓴다**
(`keep="first"`, fresh 우선). 캐시가 `min_days` 미만이면 `min_days + 30` 전체 백필.
→ **운영 실행은 T일 20:00 이후 전제**(그 전엔 종가 아님).

**REQ-DATA-2 (KRX 증분, `krx_api.update_krx_cache` / `krx_market.update_market_cache`).**
하루 1콜씩 순차 백필/증분, 호출 간 `time.sleep(0.2)`. 첫 실행은 느림(전종목 5~15분),
이후 증분. 휴장일 응답은 스킵.

- `MARKET_CACHE_DAYS = 1560` (약 6년). Strength가 52주 신고가(252일)를 다시 252일
  백분위하므로 ≥504일 필요 + 백테스트 표본.
- 구 스키마(`trdvol`/`mktcap` 없음)면 전체 재수집. `mkt` 컬럼 없으면 `"KOSPI"`로 채움.

**REQ-DATA-3 (KOSDAQ 자동 폴백).** `_MARKET_ENDPOINTS`에 KOSPI·KOSDAQ 둘 다 있으나
`ksq_bydd_trd` 이용신청 안 됐으면 빈 응답 → 한 세션에서 처음 확인되는 순간
`_KOSDAQ_OK = False`로 고정하고 이후 KOSDAQ 호출 스킵(재백필 시 헛 호출 방지).
승인 후 KOSDAQ 편입하려면 `cache/market_kospi.csv` 삭제 후 재실행.

**REQ-DATA-4 (ECOS, `ecos_data`).**
- `fetch_credit_spread`: `cache/credit_spread.csv` 우선 → 마지막 날짜가 7일 이상
  오래됐으면 최근분만 라이브 증분 → 파일 없으면 전체 라이브. 반환 `tail(num_days=2000)`.
- `synthetic_bond10y_index`: 국고채 10년 금리 → 합성 총수익 지수
  `close = 100·cumprod(1 + carry − D·Δy/100)`, `carry = y_{t-1}/252/100`,
  `D = BOND10Y_DURATION = 8.5`.
- 두 함수 모두 `ECOS_API_KEY` 없으면 `None`.

**REQ-DATA-5 (선물/금리, `options_data`).** `drv/fut_bydd_trd` 응답에서:
- `fetch_kospi200_spot`: `PROD_NM == "코스피200 선물"` 행의 `SPOT_PRC` (>0).
- `fetch_kospi200_futures`: `expiry, price(=TDD_CLSPRC or SETL_PRC), oi, volume`.
- `fetch_risk_free_rate`: `PROD_NM == "3개월무위험금리 선물"` 최근월물 `SPOT_PRC` →
  `r = (100 − SPOT_PRC)/100`, `0 < r < 0.15` 아니면 `None`.

---

## C. 지표별 raw 계산 위치 (`krx_market.compute_breadth_and_strength_raw`)

- `vol_col` = `trdvol` 있으면 그것, 없으면 `trdval`.
- 유니버스 마스크: `mktcap` 있으면 일자별 상위 `STRENGTH_UNIVERSE_N = 200`
  (`rank(ascending=False, method="first")`), 없으면 전체.
- `breadth_raw` = `(상승종목 vol − 하락종목 vol) / (상승 + 하락 vol)` (유니버스 내,
  `fluc_rt > 0` / `< 0`).
- `strength_raw` = `(at_high − at_low) / valid_count · 100`:
  - `wide` = 종목×일자 종가 피벗, `roll_max/min` = `rolling(STRENGTH_WINDOW=252,
    min_periods=252)`.
  - `valid` = `roll_max.notna() & member`(유니버스). 창 미충족 종목-일자는 제외 →
    그런 종목만 있는 앞부분 날짜는 `strength_raw` 자체가 `NaN`(가짜 0 금지).

---

## D. as_of 트렁케이션 — INV-DATA-1

`main._truncate_asof(df, as_of)` — `as_of` 주어지면 `df[date <= as_of]`. **롤링 통계
계산 이후**에만 적용해 트레일링 창을 정확히 쓰고 look-ahead를 만들지 않는다.
`combined_main`이 과거 거래일 리포트를 재생성할 때 캐시에 그 이후 데이터가 있어도
"그 날 마감 시점"만 보이도록 하는 장치.

---

## E. 수용 기준

- **AC-DATA-1.** `KRX_API_KEY` 없이 `main.py` → Volatility/Strength/Breadth는
  `is_proxy=True`, Put/Call은 N/A, 나머지 정상.
- **AC-DATA-2.** `cache/market_kospi.csv`에 `mktcap` 컬럼이 있고 전부 NaN이 아니면
  Strength/Breadth 유니버스가 상위 200으로 제한된다.
- **AC-DATA-3.** `strength_raw`의 첫 유효값은 전종목 캐시 시작 + 252거래일 이후이며,
  그 전 구간은 0이 아니라 NaN.
- **AC-DATA-4 (⚠ 미검증).** 네이버 스크래핑 HTML 구조 변경 감지 없음 — `_fetch_history`
  가 컬럼 인덱스 하드코딩(`raw.columns[0/1/4/6]`). 소스 변경 시 조용히 깨질 수 있음.

---

## F. 하지 말 것 (WORKPLAN2 §"하지 말 것")

1. 전종목 시세 2020년 이전 백필 시도(무료 한계·스크래핑 리스크).
2. 일별 투자자 flow 자동화(무료 소스 없음). KB 수동 유지, override off.
3. 과거 옵션 체인 백테스트(무료 히스토리 없음).
4. fmkorea 수치 추격(재적합).
