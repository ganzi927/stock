# 30 · 삼성전자 · SK하이닉스 개별주식 옵션

담당 코드: `stock_options_data.py`(체인), `stock_options_main.py`(조립),
`dividends.py`(배당). **[20-kospi200-options.md](20-kospi200-options.md)와 동일한 딜러
포지셔닝 분석**을 개별주식 옵션에 적용한 것이며, 여기서는 **차이점만** 규정한다.

---

## A. 대상 종목

`STOCK_UNDERLYINGS = {"삼성전자": "005930", "SK하이닉스": "000660"}`.

개별주식 옵션은 행사가가 스팟을 양쪽으로 완전히 감싸므로 Zero Gamma / Call Wall /
Put Wall이 정상 계산된다(코스피200 옵션과 달리). 검증 참조: 삼성전자 Zero Gamma
260,420.6 vs fmkorea 원본 260,720.5 (거의 일치).

---

## B. 체인 조회 (`fetch_stock_option_chain`)

- 엔드포인트 `GET {BASE_URL}/drv/eqsop_bydd_trd?basDd=YYYYMMDD` (유가증권 주식옵션).
- 상품명 필터 `PROD_NM == "<종목명> 옵션"`.
- **REQ-STK-1.** `ISU_NM`에 `"위클리"`가 들어간 행은 **명시 제외** — 개별주식
  위클리옵션(2026-06 상장)은 만기 표기·PROD_NM이 달라 만기 로직이 다르다. 통합은
  별도 작업.
- **REQ-STK-2 (파싱 정규식).** `([CP])\s+(\d{4})(\d{2})\s+([\d,]+)\(\s*(\d+)\s*\)` —
  종목명 끝의 `(승수)`를 파싱한다. 예: `"삼성전자   C 202609    68,000(  10)"` →
  콜 / 만기 202609 / 행사가 68,000 / **승수 10**.
- 만기 = `_nth_weekday(y, m, weekday=3, n=2)` (해당월 2번째 목요일 — 지수옵션과 동일).
- **REQ-STK-3.** T-0·만료 시리즈 제외 후 최근접 만기(20-옵션 REQ-OPT-3과 동일).
- 출력 컬럼: `type, strike, expiry, multiplier, iv, oi, volume, close`. **`next_settle`
  없음.**

---

## C. spot

**REQ-STK-4.** `_resolve_stock_spot` = `krx_market.fetch_market_one_day(bas_dd)`에서
`ISU_CD` 매칭 행의 `close`. (선물 SPOT_PRC 경로 없음.)

---

## D. r / q

### r
20-옵션과 동일 — `fetch_risk_free_rate`(3개월무위험금리 선물). `None`이면
`RISK_FREE_RATE = 0.030`. 라벨 `(시장)` / `(가정)`.

### q — 개별주식 전용 (`build_stock_option_section`)
**REQ-STK-5.** 지수의 1.5% 상속 폐기. 다음으로 결정:
- 기본 `q_base = STOCK_DIV_YIELD[name]` — **삼성전자 0.010, SK하이닉스 0.003**
  (2026 기준 근사, 현금배당만; 자사주 매입 제외).
- **만기 내 배당락이 있으면**(`dividends.dividends_in_window(name, as_of, expiry)`,
  구간 `(as_of, expiry]`, as_of 당일 제외):
  `pv_div = Σ amt · e^(−r · max((d−as_of).days,0)/365)`,
  `q = −ln( max(1 − pv_div/spot, 1e-6) ) / T` — 잔존기간 등가 연속수익률.
  q_note에 "만기 내 배당락 N건, 주당합 …원 PV환산" 표기.
- **REQ-STK-6.** 개별주식 체인이 얇아 풋-콜 패리티 내재 q 추정은 노이즈가 커서
  **사용하지 않는다**(20-옵션 REQ-OPT-6의 1·2단계 없음).

### 배당 캘린더 (`dividends.STOCK_DIVIDENDS`)
- 손으로 유지, **공시(DART) 기반 연 1회 갱신**. `종목명 → [(배당락일, 주당 현금배당액
  원), ...]`.
- ⚠ 근사치 — 분기 정규배당 기준, 특별배당·변경 미반영. 매년 초 갱신 필요.

---

## E. 잔존만기

`t_years = max(days_left, 0.25) / 365` (`days_left = (expiry − as_of).days`).
20-옵션 `_time_to_expiry`와 동일 규약.

---

## F. 승수·넓은 행사가 범위

- **REQ-STK-7.** `multiplier`는 종목명에 표기된 값(현재 10)을 그대로 파싱해
  `analyze(..., multiplier=multiplier)`에 넘긴다.
- SK하이닉스처럼 상장 행사가 범위가 스팟보다 훨씬 넓고(28만~380만원) 특정 행사가에
  1계약만 걸린 경우, `_oi_weighted_strike_range`(OI 누적 2~98%)가 그리드를 제한해
  가짜 0교차를 막는다. 그래도 crossing이 없으면 값을 만들지 않고 **N/A**.
- `_drop_stale_oi`(딥 ±15% 밖, `oi > 200·volume`)와 `find_walls`의 스팟 ±30% 제한도
  동일 적용.

---

## G. 나머지

GEX/DEX/VEX/Charm 부호 규약(INV-OPT-1), 그릭스, IV 스마일, PoT, 25Δ RR,
positioning_skew, 합성지수, 시나리오, IV Rank(`cache/atm_iv_<isu_cd>.csv`),
AI 코멘트는 전부 20-옵션과 동일하다.

`expiry_label` = `"기준일 <as_of> · 만기 <expiry> (T-<days>) · r=..(시장|가정) · q=..
(만기 내 배당락 N건… | 종목별 평상시 가정, 현금배당)"`.

### 초보자 판단 도구

- **REQ-STK-8 (관찰가격).** 삼성전자·SK하이닉스 연구 패널에는 현재가 위·아래에서 가장
  가까운 계산 레벨을 각각 `상단 관찰가격`·`하단 관찰가격`으로 표시한다. 후보는
  Call/Put Wall, 상·하단 Gamma Wall, Zero Gamma, MaxPain이며 레벨명과 현재가 대비
  거리를 함께 표시한다. 이는 목표가·손절가·지지·저항 추천이 아니다.
- **REQ-STK-9 (관찰·계산 분리).** 관찰가격과 개인 계산기를 서로 다른 블록으로 표시한다.
  무명 무효화 목록 및 상단거리/손실거리 비율을 생성하지 않는다.
- **REQ-STK-10 (내 손실한도 계산기).** 사용자가 매수가, 수량, 최대 허용손실액을 직접
  입력하면 롱 포지션 기준 `손실한도 가격 = 매수가 − 최대 허용손실액 / 수량`을 브라우저
  안에서 계산한다. 입력은 저장·전송하지 않는다. 수량은 양의 정수여야 하며 0 이하·비유한 입력과 손실한도가 0원
  이하가 되는 조합은 거부한다. 결과에는 매수가 대비 하락률과 계산에 사용한 매수가·수량·손실예산을 표시한다.
  input/change 이벤트마다 기존 결과를 즉시 지워 재계산을 요구한다. 수수료·세금·갭·
  슬리피지는 미반영이라고 고지하며 시스템이 손실률을 대신 정하지 않는다.

---

## H. 실행 흐름

- `generate_stock_options_sections(bas_dd, as_of)` — `combined_main`이 `anchor` 기준으로
  호출. `STOCK_UNDERLYINGS` 순회, 데이터 없는 종목은 건너뜀(전체가 없으면 빈 리스트 →
  `stock-opt` 탭 생략).
- standalone `python stock_options_main.py` — `_resolve_latest_available_day`로 최근
  옵션 데이터 있는 날 walk-back.

---

## I. 수용 기준

- **AC-STK-1.** 20-옵션의 AC-OPT-1~5(그릭스·PoT·MaxPain·합성선물 known-answer)는
  승수만 다를 뿐 동일 코드 경로라 함께 커버된다.
- **AC-STK-2.** 만기 내 배당락이 있는 날의 q_note에 배당 건수·주당합이 나타나고,
  q가 `q_base`보다 크다(배당락 반영 방향).
- **AC-STK-3.** SK하이닉스에서 Zero Gamma crossing이 없으면 레벨이 N/A로 표시되고
  억지 값이 들어가지 않는다.
- **AC-STK-4 (정성).** 삼성전자 Zero Gamma가 fmkorea 원본과 ~0.1% 이내 근접(과거 관측).
- **AC-STK-6.** 현재가 250,000원, 수량 10주, 최대 허용손실 100,000원이면 손실한도
  240,000원으로 계산된다. 개별주식 HTML에 관찰가격·입력 비저장·비추천 문구가 있고
  코스피200 옵션 HTML에는 계산기가 없다. 입력 변경 후 과거 결과가 남지 않는다.

---

## J. 미해결 / 한계

- 개별주식 위클리옵션 미통합.
- 개별주식 선물 미연동 → 배당락 없는 구간의 q는 상수 가정.
- `STOCK_DIV_YIELD` / `STOCK_DIVIDENDS`는 수동 — 갱신 누락 시 조용히 낡은 값 사용.

## 2026-09-15 근거 감사 정정
- REQ-STK-3: 미래 만기가 없으면 빈 체인 반환.
- REQ-STK-7: 거래량/OI 비율로 계약을 제거하지 않는다(REQ-OPT-10 정정).
- AC-STK-5: 만료 전용 API 응답은 계산에 전달되지 않는다.
- 배당 근사치·배당락일/지급일 및 휴장일 보정은 미검증 항목으로 유지하며 공식 데이터 연계 정책은 사용자 결정 필요.
