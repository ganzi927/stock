# 데이터 인벤토리 (WORKPLAN Phase 0 산출물)

각 시계열의 시작일 / 소스 / 갱신 경로 / 알려진 품질 한계. 마지막 갱신: 2026-08-28.

| series | 캐시 파일 | 시작 | 소스 | 갱신 | 품질 한계 |
|---|---|---|---|---|---|
| KOSPI200 지수 | `cache/kospi200.csv` | 2016 (딥백필 후) | 네이버 금융 스크래핑 | `main.py` 매일 최근 30일 덮어쓰기 / `backtest.py` 첫 실행이 2600일 백필 | 네이버 "오늘" 행은 장중 스냅샷 — 20:00 이후 실행 전제. 지수 종가 기준(선물 아님) |
| KOSPI 지수 | `cache/kospi.csv` | 2016 | 네이버 | 〃 | 〃 |
| VKOSPI | `cache/vkospi.csv` | **2016-01** (`_backfill_sentiment.py`) | KRX Open API `idx/drvprod_dd_trd` (변동성지수) | `main.py` `update_krx_cache` 증분 | KRX가 2010년까지 제공 — 더 필요하면 START 조정. 종가만 |
| 옵션 풋/콜 비율 | `cache/putcall.csv` | **2016-01** | KRX Open API `drv/opt_bydd_trd`, `PROD_NM=="코스피200 옵션"`(정규월물) 거래량 PUT/CALL | 〃 | 위클리·미니 제외. 만기 주간엔 롤 효과로 튐 → `compute_putcall_real`이 5일 MA로 평활 |
| 신용스프레드 BBB−AA | `cache/credit_spread.csv` (`spread`) | **2018-07** (2000행 tail) / 원천은 2008 | ECOS `817Y002` item `010320000`(BBB- 3Y) − `010300000`(AA- 3Y) | `ecos_data.fetch_credit_spread`가 캐시 우선, 7일+ 오래되면 라이브 증분 | ⚠️ **BBB- 3Y 수익률은 매트릭스 프라이싱(호가 기반, 실거래 희박)** — 값이 계단식. 최근 252일 중 `|Δ|>0.01`인 날이 11일뿐. 전체 2018~2026 범위는 5.74~6.46(std 0.21)로 다년 국면 변화는 잡지만 단기 백분위는 노이즈 증폭 가능. `spread_a`(BBB−A-, std 0.36) 병행 저장 — leg 민감도 확인용 |
| 국고채 10년 금리 | `cache/bond10y_yield.csv` | **2016-01** / 원천 2008 | ECOS `817Y002` item `010210000` | `ecos_data.synthetic_bond10y_index`가 캐시 우선, 증분 | Safe Haven 채권 레그로 사용. `close` = `100·cumprod(1 + carry − D·Δy/100)`, D=8.5 근사 수정듀레이션 |
| 국고채 10년 ETF | `cache/bond10y.csv` (148070) | 2023-12 (네이버 tail), 상장 2025-01 | 네이버 | `main.py` | **참고용 cross-check로만.** 실제 Safe Haven 레그는 위 합성지수. ETF는 히스토리가 짧아 폐기 |
| 전종목 시세 (KOSPI) | `cache/market_kospi.csv` | **2020-09-07** (1463 거래일) | KRX Open API `sto/stk_bydd_trd` (+ `ksq_bydd_trd` 승인 시 KOSDAQ) | `krx_market.update_market_cache` 증분, `MARKET_CACHE_DAYS=1560` | Breadth·Strength 원천. KOSDAQ API 미승인 → 현재 KOSPI만. **7개 지표 전부 존재하는 구간의 하한이 여기(2020-09)** |

## 7개 지표가 전부 존재하는 구간

`market_kospi.csv` 시작(2020-09) + 각 지표 워밍업(첫 유효값 + PCT_WINDOW=252 거래일) 이후.
`backtest.py` 가 `n_ind==7` 서브샘플로 자동 산출한다. 대략 **2021-09 ~ 현재 (~1200 거래일,
+60일 기준 유효 표본 n_eff ≈ 20)**.

파생·신용(투심) 3개만 필요한 분석은 2016(vkospi/putcall) ~ 현재로 더 길다.

## 더 늘리려면

- VKOSPI/풋콜: `_backfill_sentiment.py` 의 `START` 를 `"2010-01-01"` 로. KRX가 준다(확인함).
- 전종목(Breadth/Strength): KRX Open API가 2020-09까지만 → 그 이전은 불가(무료 티어 한계).
  KOSDAQ 편입은 `ksq_bydd_trd` 이용신청(무료) 후 `cache/market_kospi.csv` 삭제·재실행.
- 신용스프레드: BBB- 매트릭스 프라이싱 한계는 소스 문제라 못 고침. 대안은 AA−국고채(변동
  실질적) 를 별도 트랙으로 보되 "정크 프리미엄"이 아니라 "IG 스프레드"임을 명시.
