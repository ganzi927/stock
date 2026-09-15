> **2026-08-28 방향 전환 — 이 문서는 이력(履歷)이다.**
> "fmkorea 블로거 수치에 맞추기"를 검증 목표로 삼던 것을 접고, `WORKPLAN.md` 로
> 이전했다. 이제 기준은 "지표가 내부적으로 일관되며 미래수익률 정보를 담는가"이고,
> fmkorea 대조는 참고용 부록으로 강등했다. 아래 K1~O6 의 **버그 수정**(ECOS 코드,
> 60일≠52주, T-0 만기, 콤마 파싱 등)은 여전히 유효하다. 다만 §4·§5 의 "fmkorea 와
> ±4p 로 맞췄다" 류 서술과 옵션 B 선형계수는 `WORKPLAN.md` Phase 1~2 에서 폐기됐다.
> 현재 지표 사양은 `indicators.py` docstring + `WORKPLAN.md` 가 기준. 검증 결과는
> `VALIDATION.md`, 데이터 현황은 `DATA_INVENTORY.md`.

---

# fmkorea 원본 대조 — 원인 분석 및 수정 계획서

대상: 2026-08-27 거래일 기준. 내 리포트 `reports/2026-08-28.html`(08-28 아침 생성, 마지막 완료
거래일인 08-27 데이터 사용) vs fmkorea "곰곰이곰곰"/"일북어" 08월 27일자 3개 글
(공포탐욕지수편 / 옵션편 / 삼성전자·SK하이닉스 옵션편).

두 리포트는 **같은 거래일(2026-08-27)** 데이터다. KOSPI 종가 6,912.37 / KOSPI200 1,088.61 로 일치.

---

## 0. 요약 — 무엇이 얼마나 달랐나

### KFGI 총점: fmkorea 47.4(Neutral) vs 내 리포트 66.2(탐욕), 18.8p 차이

7개 지표 중 4개는 사실상 일치, 3개가 정반대 방향이었다.

| 지표 | fmkorea score | 내 score | 상태 |
|---|---|---|---|
| Momentum | 6.4 | 6.4 | raw까지 완전 동일 |
| Volatility (VKOSPI) | 45.2 | 45.0 | raw 53.0100 완전 동일 |
| Safe Haven Demand | 82.4 | 82.5 | 사실상 동일 |
| Put/Call Ratio | 90.4 | 91.6 | raw만 다름(0.86 vs 0.776), score 근접 |
| **Credit Spread** | **66.0** | **100.0** | raw −0.1720 (음수 = 물리적으로 불가능) |
| **Market Strength** | **24.4 (공포)** | **63.7 (탐욕)** | 정규화 기준·초기 히스토리 편향 |
| **Stock Price Breadth** | **17.2 (극도공포)** | **74.1 (탐욕)** | 정의(거래대금 vs 거래량) + 정규화 |

**핵심 증명**: 일치하는 4개 score 합(6.4+45.0+91.6+82.5 = 225.5)에 fmkorea의
Breadth/Strength/Credit(17.2+24.4+66.0)을 더해 7로 나누면 **47.6** → fmkorea의 47.4와
사실상 일치. 즉 **총점 18.8p 격차는 전적으로 이 3개 지표에서 나온다.**

> 수정 후 최종 결과·판정은 **§4** 참고. 요약: 총점 66.2 → 47.2 (fmkorea 47.4, 우연히
> 근접). Credit Spread·Strength는 원천 데이터·계산은 정상화됐으나 fmkorea의 비공개
> 정규화 창 때문에 개별 score는 여전히 30~55p 차이.

### 옵션: 방향성 진단이 대체로 반대, 일부 레벨은 매우 근접

| 항목 | fmkorea | 내 리포트 | 판정 |
|---|---|---|---|
| 코스피200 Zero Gamma | 1052.7 | 1056.6 | ✅ 0.4% 근접 (모델 노이즈 범위) |
| 삼성전자 Zero Gamma | 257,318.6 | 256,579.7 | ✅ 0.3% 근접 |
| SK하이닉스 핵심지지/Call Wall | 1,700,000 | 1,700,000 | ✅ 완전 일치 |
| **코스피200 MaxPain** | **1100.0** | **1050.0** | 50p 차이, 스팟 위/아래가 갈림 |
| **SK하이닉스 MaxPain** | **1,650,000** | **960,000** | 딥OTM 잔존 OI에 끌려간 버그 |
| **위클리 옵션 섹션** | (없음) | T-0 만료물, 전부 N/A | 만료된 시리즈를 잡는 버그 |
| **개별주식 Charm/Vanna Flow** | -5.79억 등 유의미 | 0.0억 (반올림) | 단위 규약 결함 |
| 방향성 진단 | 3편 모두 "상방 과열/Long-Skew" | 코스피200·삼성 "하방 공포 우위" | 아래 O5 참고 |
| 상단 저항(Gamma Wall) | 삼성 301,497 / 하이닉스 1,917,930 | 없음 | 2차 레벨 미표시 |

---

## 1. KFGI 상세 원인

### K1. Credit Spread — ECOS 통계코드가 완전히 틀렸다 (확정 버그)

`ecos_data.py` 현재값:
```python
STAT_CODE = "722Y001"        # → 예금은행 가중평균금리 (시장 채권금리 아님!)
CORP_BOND_ITEM = "0102000"   # → "예금은행 수신금리" 2.828
TREASURY_ITEM  = "0101000"   # → "한국은행 기준금리"  2.75
```
라이브 API로 확인한 결과, 현재 코드는 **회사채·국고채 금리가 아니라 예금은행
수신금리 − 한국은행 기준금리**를 빼고 있다. 둘 다 2.7~2.8% 근처라 차이가 ±0.1%p 수준으로
0 근방에서 부호가 뒤집히고, 252일 롤링 백분위(invert=True)에서 최저 raw로 인식돼
**score가 100.0(극도 탐욕)에 고정**됐다.

**올바른 코드** (라이브 확인):
```python
STAT_CODE = "817Y002"          # 시장금리(일별)
CORP_BOND_ITEM = "010300000"   # 회사채(3년, AA-)  → 4.492
TREASURY_ITEM  = "010200000"   # 국고채(3년)       → 3.796
```
→ 스프레드 4.49 − 3.80 = **약 0.70%p** (정상적인 AA- 신용스프레드).

fmkorea의 raw 5.8110은 단위 미상(%p 스프레드로 보기엔 과대)이라 값 자체를 맞추긴
어렵지만, 최소한 **음수(−0.17)라는 명백한 오류는 제거**되고 방향이 정상화된다.

### K2. Strength — "52주 신고가"가 사실상 60일 신고가 + 초기 구간 가짜 0 (correctness 버그 2건)

`krx_market.compute_breadth_and_strength_raw`:
```python
roll_max = wide.rolling(252, min_periods=60).max()
roll_min = wide.rolling(252, min_periods=60).min()
at_high = (wide >= roll_max).sum(axis=1)
```
버그 (a) `min_periods=60`: 캐시 초기 구간에서 **60일치만으로 "52주 신고가"를 판정**.
상승장에서는 짧은 창일수록 신고가 종목이 폭증해 `strength_raw`가 과대 계상되고,
그 값들이 롤링 백분위 정규화 기준(base)을 왜곡.

버그 (b) **가짜 0**: `roll_max`가 NaN인(창이 안 찬) 초기 행은 `wide >= NaN`이 전부
False가 돼 `at_high−at_low = 0` → `strength_raw = 0.0`이 찍힌다. NaN이어야 할 251개
행이 정확히 0.0으로 채워져 정규화 기준에 가짜 중립값이 대량 섞였다.

**수정 (최종안)**:
1. **KRX Open API가 전종목 일별시세를 2020년까지 제공**하는 것 확인 → `update_market_cache`
   백필 길이를 300 → **620거래일(2.5년)**로 (`MARKET_CACHE_DAYS`). Strength는 52주
   신고가(252)를 다시 252일 백분위로 정규화하므로 꽉 찬 기준에 ≥504거래일 필요.
2. `min_periods`를 60 → **252**(진짜 52주). 처음 시도한 120은 "252가 과했다"를 보고
   고른 값이라 폐기 — 데이터를 더 받는 게 옳은 해법이었다.
3. `.where(roll_max.notna())` 마스킹으로 창이 안 찬 종목-일자를 집계에서 빼고,
   그런 종목만 있는 앞부분 날짜는 `strength_raw` 자체가 **진짜 NaN**이 되게 함
   (가짜 0 제거). `total`은 `pd.NA` 대신 `np.nan`으로 처리(object dtype → rolling.apply 깨짐 방지).

캐시 재생성: 576거래일(2024-04-15~2026-08-27), `strength_raw` non-NaN 325일 →
252일 백분위 기준이 최근 ~73일치 확보됨(계속 늘어남).

### K3. Breadth — 거래"대금"이 아니라 거래"량"이 표준 (methodology 정렬)

CNN Fear & Greed의 "Stock Price Breadth"는 McClellan Volume 계열, 즉 **상승 종목 거래량 −
하락 종목 거래량**이다. 현재 코드는 거래대금(`ACC_TRDVAL`)에 등락부호를 곱한다:
```python
signed_val = d["trdval"] * sign(d["fluc_rt"])   # 원 단위 → raw 13.4조
```
fmkorea raw는 131,940,308 (≈1.3억) 규모라 거래량 차이(주식 수)에 더 가깝다.

**수정**: `fetch_market_one_day`가 `ACC_TRDVOL`(거래량)도 가져오도록 `trdvol` 컬럼 추가 →
구 스키마(`trdvol` 없음) 캐시는 자동 전체 재수집 → Breadth를 `Σ sign(fluc_rt)·trdvol`로
변경 → 캐시 재생성(K2 백필과 합쳐 620콜, 약 7분). 정규화 방식(롤링 백분위)은 유지.
Breadth는 롤링 고저 창을 안 쓰므로 K2의 가짜 0 버그 영향 없음.

### K4. Put/Call Ratio 0.776 vs 0.86 (경미, 코드 변경 안 함)

`fetch_kospi200_option_putcall_one_day`는 `PROD_NM == "코스피200 옵션"`(정규월물)만 집계한다.
fmkorea는 위클리를 포함하거나 다른 집계일 가능성. score 차이가 1.2p(91.6 vs 90.4)로
둘 다 극도 탐욕이라 총점 영향은 무시 가능. **후속 과제로만 기록.**

### K5. fmkorea는 1일/1주/1개월 전 값을 함께 보여준다 (후속 과제)

내 리포트는 추이 차트만 있고 텍스트 수치가 없다. `trend` 데이터는 이미 계산돼 있으니
표로 노출하는 건 쉬움. 이번 범위에서는 제외.

---

## 2. 옵션 상세 원인

### O1. `compute_max_pain`에 행사가 범위 제한이 없다 (확정 버그)

`find_walls`는 스팟 ±30%로, 프로파일 그리드는 OI 누적 2~98%로 극단 행사가를 걸러내는데
`compute_max_pain`만 **상장된 전 행사가**를 훑는다:
```python
strikes = np.sort(chain["strike"].unique())   # 335 ~ 1597.5 전부
```
그 결과 딥OTM에 쌓인 오래된 잔존 미결제약정(README에 기록된 SK하이닉스 1,050,000 콜
72,007계약 사례)이 MaxPain을 스팟과 무관한 곳으로 끌고 간다 →
**SK하이닉스 MaxPain 960,000 (스팟 −44.5%, PoT 0.0%)** 라는 자명한 오류.

**수정 (최종안, 반복 3회 후)**:
- OI 누적 밴드는 **안 쓴다.** SK하이닉스는 딥ITM 저행사가(960k/1050k/1150k) 3개에
  전체 OI의 90%가 몰려 있어, OI 누적분포가 앞쪽에 쏠린다 → 2~98%든 10~90%든 밴드가
  스팟 한참 아래로 잡히고 MaxPain이 960,000으로 끌려간다. (2~98%=1,250,000, 10~90%=960,000
  으로 오히려 악화됨을 확인.)
- **스팟 ±moneyness_range(30%)만** 하드 필터로 쓴다 (`find_walls`와 동일). 행사가가
  성기면 ±50%로 한 단계 완화.
- **후보 행사가뿐 아니라 내재가치 합산에 쓰는 계약도 같은 밴드로 제한.** 이걸 안 하면
  밴드 밖 스팟 아래 딥ITM 콜의 잔존 OI가 `call_pain` 합을 지배해 여전히 아래로 끌린다.

결과: SK하이닉스 MaxPain 960,000 → **1,500,000 (−13.3%)**. fmkorea 1,650,000(−4.8%)과는
여전히 차이 — fmkorea의 딥ITM OI 처리 방식이 다른 것으로 보이며, **여기서 반복 중단**
(더 조이면 fmkorea 수치를 눈대중으로 좇는 게 됨). 코스피200 정규 1,050 → 1,057.5.

### O2. 위클리 옵션 섹션이 T-0 만료물을 잡는다 (확정 버그)

`fetch_option_chain`은 `nearest_expiry = df["expiry"].min()`으로 가장 가까운 만기를
고른다. 2026-08-27은 목요일이라 **위클리 최근 만기 == 당일(T-0)** → IV·그릭스 전부
붕괴, MaxPain 892.5(스팟 −18%) 같은 무의미값. fmkorea 옵션편은 위클리를 아예 안 다룬다.

**수정**: 만기가 `as_of` 이하인 시리즈를 먼저 제외한 뒤 최근 만기 선택:
```python
future = df[df["expiry"] > as_of]
df = future if not future.empty else df
nearest_expiry = df["expiry"].min()
```
`fetch_stock_option_chain`에도 동일 적용(만기일 당일 방어).

### O3. 개별주식 Net DEX/Vanna/Charm Flow가 "0.0억"으로 표시된다 (단위 규약 결함)

`with_greeks_at_spot`:
```python
df["dex"]       = dex_sign * df["oi"] * df["delta"] * multiplier
df["charm_exp"] = gex_sign * df["oi"] * df["charm"] * multiplier
```
GEX는 `gamma · spot² · 0.01 · multiplier`로 스팟을 반영하는데 DEX/VEX/Charm은 안 한다.
지수옵션은 multiplier가 250,000이라 억 단위로 보이지만, 개별주식은 multiplier가 10이라
`/1e8` 하면 0.0억으로 반올림된다.

업계 표준 "$DEX"(FlashAlpha/MenthorQ — 이 코드 docstring이 인용하는 출처)는
**Σ(delta · OI · 승수 · 스팟)** = 델타 명목가치(통화 단위)다.

**수정**: `dex/vex/charm_exp`에 `· spot`을 곱해 명목가치로 통일. 스팟>0이므로 부호·
0교차(Zero Gamma, DEX Neutral)는 불변. `options_report._eok`를 억/조 자동 스케일로 변경,
카드 설명 문구도 "명목가치"로 갱신. `ai_commentary._won`, `options_charts._line_profile_chart`도
억/조 자동 스케일.

#### −25억 vs −2.7조 — 왜 다르고 뭐가 맞나 (사용자 질문)

공식 차이는 `× 현재가` 하나. 코스피200은 승수 250,000원/pt, 현재가 ≈ 1,089 →
**수정 후 ÷ 수정 전 = 약 1,089배**. 지수 레벨을 한 번 더 곱한 것.

| | 값 | 의미 | 단위 |
|---|---|---|---|
| 수정 전 | −25억 | 지수 **1포인트** 움직일 때 딜러 장부 가치 변화 | 원 / 포인트 |
| 수정 후 | −2.7조 | 딜러가 잡은 지수 방향 포지션의 **원화 명목금액** | 원 |

둘 다 틀린 게 아니라 다른 질문의 답이다. **"DEX(Delta Exposure)"로서 맞는 건 명목금액 쪽**:
- SqueezeMetrics 원조 논문은 GEX를 "the dollar value ... per 1% move"로 정의(달러 가치 + % 기준).
- FlashAlpha/MenthorQ의 DEX = `Σ(델타·OI·승수·스팟)` 명목가치. 이 파일 docstring이 인용하는 출처.
- **이 파일의 GEX는 이미 명목 방식**(`gamma·spot²·0.01·multiplier`)이었다. DEX/VEX/Charm만
  `·spot`이 빠져 GEX와 규약이 어긋나 있었음. ×spot은 그 불일치를 바로잡은 것.

fmkorea의 "DEX" 단위는 두 버전 어느 쪽과도 안 맞고 fmkorea 글 안에서도 일관되지 않다
(코스피200 "+2,112.5 DEX" vs 삼성 "−5.79억 DEX/일"). 삼성 Charm이 새 값 −9.7억과
fmkorea −5.79억이 자릿수 맞은 건 부분적 우연. **×spot은 fmkorea가 아니라 이 파일 GEX와
업계 표준에 맞춘 것.**

**판단: ×spot(명목가치) 유지.** 되돌리면 개별주식은 계속 0.0억이고, 한 리포트 안에서
GEX(명목)와 DEX(포인트당)의 기준이 어긋난다.

### O4. 상단 저항(Gamma Wall)이 표시되지 않는다 (개선)

fmkorea는 SK하이닉스에서 "핵심 감마 지지 1,700,000"(= 내 Call Wall과 정확히 일치)과
"Gamma Wall 1,917,930"(스팟 위 최대 콜 GEX)을 **둘 다** 제시한다. 내 `find_walls`는
콜 GEX 최댓값 1개만 내보내는데, 그게 스팟 아래(1,700,000)면 스팟 위 저항이 사라진다.

**수정**: `Levels`에 `call_wall_above`(스팟 위 콜 GEX 최대 행사가) /
`put_wall_below`(스팟 아래 |풋 GEX| 최대) 추가, 레벨 표에 함께 표기.

### O5. 방향성 진단이 반대인 이유 — 측정 대상이 다르다 (개선)

fmkorea "상방 쏠림도 17.04%/23.80%/93.32%", "콜 쏠림"은 **포지션(OI·거래량) 편향**이다.
내 25델타 Risk Reversal(코스피200 −2.20%p)은 **변동성 스큐**(풋 IV가 콜 IV보다 비쌈)다.
지수옵션에서 "콜 OI가 많다 + 풋 IV가 비싸다"는 흔히 동시에 성립(전형적 지수 풋 스큐)이라
서로 모순이 아니라 **다른 축**이다. 지금 리포트는 스큐만 보여줘서 fmkorea와 반대로 보인다.

**수정**: 25델타 RR 옆에 **콜/풋 OI 비율·거래량 비율·쏠림도(call−put)/(call+put)**
카드를 추가해 두 관점을 나란히 표시. O1(MaxPain 정상화)이 적용되면 "Base Case" 목표가
스팟 위(1,100)로 올라와 AI 서술의 하방 편향도 완화된다.

### O6. 스팟 기준값 (경미, 후속 과제)

fmkorea 스팟(1089.8 / 266,500 / 1,734,000)은 매번 내 값보다 0.1~0.2% 높다 — 선물가
사용으로 추정. 내 리포트는 지수/주식 종가를 쓴다(더 표준적). `fetch_kospi200_futures`가
이미 있으니 원하면 전환 가능. 이번 범위 제외.

### 수정하지 않는 항목 (정상 또는 검증 불가)

- **Zero Gamma 0.3~0.4% 차이**: r/q 가정·그리드 해상도(141점)·IV 고정 가정·스팟값
  차이에서 오는 모델 노이즈. 오히려 잘 맞는 편.
- **SK하이닉스 Zero Gamma 부재**: 스팟 근방이 전 구간 롱 감마라 0교차가 없음 —
  fmkorea도 SKH엔 Zero Gamma 수치를 안 준다. 정상.
- **GEX/DEX 딜러 부호 가정**: 미국 시장(SpotGamma DDOI)조차 비공개인 모델링 관행.
  README에 이미 상세 기술.

---

## 3. 실행 계획 (이번 커밋)

| # | 파일 | 변경 | 유형 |
|---|---|---|---|
| K1 | `ecos_data.py` | STAT_CODE·item 코드 3개 교체 (817Y002 / 010300000 / 010200000), `num_days` 300→520 | 확정 버그 |
| K2 | `krx_market.py` | 백필 300→620거래일(`MARKET_CACHE_DAYS`), `min_periods` 60→252, 가짜 0 → NaN 마스킹, `numpy` import | correctness ×2 |
| K3 | `krx_market.py`, `main.py` | `ACC_TRDVOL`(`trdvol`) 추가, Breadth를 signed volume으로, 구스키마 자동 재수집, 카드 note 수정 | methodology |
| O1 | `dealer_positioning.py` | `compute_max_pain`: 후보 행사가+합산 계약 모두 스팟 ±30%로 제한 (OI 밴드 미사용) | 확정 버그 |
| O2 | `options_data.py`, `stock_options_data.py` | 만기 ≤ as_of 시리즈 제외 후 최근 만기 선택 | 확정 버그 |
| O3 | `dealer_positioning.py`, `options_report.py`, `options_charts.py`, `ai_commentary.py` | DEX/VEX/Charm에 `·spot`(명목가치 통일), 억/조 자동 스케일, 라벨 정비 | 단위 규약 |
| O4 | `dealer_positioning.py`, `options_report.py`, `ai_commentary.py` | `call_wall_above`/`put_wall_below` 추가·표기 | 개선 |
| O5 | `dealer_positioning.py`, `options_main.py`, `stock_options_main.py`, `options_report.py`, `ai_commentary.py` | 콜/풋 OI·거래량 쏠림도 카드 + AI 코멘트 반영 | 개선 |

### 검증

1. `python combined_main.py` 재실행, `reports/2026-08-28.html` 재생성.
2. 확인 포인트:
   - Credit Spread raw > 0 (약 0.6~0.8), score 100 고정 해제
   - KFGI 총점이 fmkorea 47.4 방향으로 하향 (Breadth/Strength 재정규화 + Credit 정상화)
   - 위클리 섹션이 다음 주 목요일 만기 시리즈로 표시(또는 데이터 없으면 정상 skip)
   - SK하이닉스 MaxPain이 스팟 ±30% 안(≈1,650,000)으로 이동
   - 삼성/하이닉스 Net DEX·Vanna·Charm이 0.0이 아닌 유의미 값
   - 코스피200 MaxPain이 1,100 근방으로 이동
3. `RECONCILIATION.md`의 0장 표를 재생성값으로 갱신.

---

## 4. 실행 결과 (2026-08-27 데이터 기준, 장중 데이터 배제하고 계산)

### KFGI — 총점 66.2 → **47.2** (fmkorea 47.4)

| 지표 | 수정 전 | 수정 후 | fmkorea | 비고 |
|---|---|---|---|---|
| Momentum | 6.4 | 6.4 | 6.4 | 원래 일치 |
| Volatility | 45.0 | 45.0 | 45.2 | raw 53.01 원래 일치 |
| Safe Haven | 82.5 | 82.5 | 82.4 | 원래 일치 |
| Put/Call | 91.6 | 91.6 | 90.4 | raw 0.776 vs 0.86 (K4 후속) |
| **Credit Spread** | 100.0 (raw −0.172) | **10.8 (raw 0.693)** | 66.0 | K1으로 데이터 정상화(실제 AA-−국고채=0.69%p). 남은 55p차는 정규화 창(내 2년 vs fmkorea 미상)·fmkorea raw 5.81의 정체불명 — 버그 아님 |
| **Strength** | 63.7 → 95.2 → 72.1 → 56.6 → **20.4** | (raw 0.85%) | 24.4 | K2(버그 제거) 후에도 56.6이었으나, **옵션 B(10일 평활 + 고정 선형 스케일, fmkorea 방식 재현)로 20.4** — fmkorea와 -4p, score가 매끄러워짐 |
| **Breadth** | 74.1 (탐욕, raw 13.4조) | **37.8 (공포, raw 4,397만)** | 17.2 | K3로 거래량 기준·정상 규모. fmkorea와 같은 "공포" 존. 옵션 B(SMA-19)로 더 좁힐 수 있으나 미적용 |

**옵션 B 적용 후 TOTAL: 42.1** (fmkorea 47.4). 잔여 격차는 Credit Spread(-55p, 정의 불명,
포기) + Breadth(+21p, 옵션 B 적용 시 좁혀짐). 5개 지표는 fmkorea와 ±4p 이내.

Strength score 이력: 63.7(원본 min_periods=60) → 95.2(순진하게 252) → 72.1(120) →
56.6(252 + NaN 마스킹) → **20.4(옵션 B)**.

### 옵션

| 항목 | 수정 전 | 수정 후 | fmkorea | 판정 |
|---|---|---|---|---|
| 위클리 섹션 | T-0 만료물, 전부 N/A, MaxPain 892.5 | **만기 09-03(T-7), 정상 레벨 전부** | (없음) | ✅ O2 |
| SK하이닉스 MaxPain | 960,000 (−44.5%, PoT 0%) | **1,500,000 (−13.3%)** | 1,650,000 (−4.8%) | ✅ O1 대폭 개선 (잔여차는 fmkorea의 딥ITM OI 처리 방식 차이, 반복 중단) |
| 삼성전자 MaxPain | 250,000 (−6.0%) | **260,000 (−2.3%)** | 미표기 | ✅ Call/Put Wall과 정렬 |
| 코스피200 정규 MaxPain | 1,050.0 | 1,057.5 (−2.9%) | 1,100 (+1%) | △ 소폭 개선, 여전히 스팟 아래 |
| 삼성 Net DEX / Vanna / Charm | 0.0억 / 0.0억 / 0.0억 | **−316.5억 / +4.0억 / −9.7억** | Charm −5.79억 | ✅ O3 (Charm은 fmkorea와 자릿수·부호 일치) |
| SK하이닉스 Net DEX | 0.0억 | **−2.33조** | — | ✅ O3 |
| 상단 Gamma Wall | 미표시 | 삼성 270,000 / SKH **2,000,000** / 위클리 1,190 | SKH 1,917,930 | ✅ O4 (SKH가 fmkorea와 4% 이내) |
| 포지션 쏠림도 | 없음 | KOSPI200 정규 OI −18.8%/거래량 **+12.9%**, 삼성 거래량 **+16.2%**, SKH OI **+91.7%** | 17.04% / 23.80% / **93.32%** | ✅ O5 — fmkorea "쏠림도"는 거래량/OI 스큐였고 SKH는 거의 정확히 일치 |

**방향성**: fmkorea가 headline으로 쓰는 "상방 쏠림도/콜 쏠림"이 이제 리포트에 병기돼,
25델타 RR(변동성 스큐, 지수옵션에서 음수)과 포지션 쏠림도(SKH +91.7%)가 나란히 보인다 —
둘은 모순이 아니라 다른 축임이 카드 설명과 AI 코멘트에 명시됨.

### 검증 완료 항목
- `python combined_main.py` / `options_main.py` / `stock_options_main.py` 정상, 전 모듈 `py_compile` 통과
- Credit Spread raw > 0 (0.693), score 100 고정 해제 ✅
- 위클리 섹션이 다음 목요일(09-03) 만기로 표시 ✅
- SK하이닉스 MaxPain 스팟 ±30% 안으로 이동 (960k → 1.5M) ✅
- 삼성/하이닉스/위클리 Net DEX·Vanna·Charm 전부 유의미 값 ✅
- 전종목 캐시 재생성: 576거래일(2024-04-15~), `trdvol` 컬럼 포함, `strength_raw` non-NaN 325일 ✅

### 프로세스 정직성 (사용자 질의에 대한 답)

억지로 값을 맞추기 위한 **오프셋·계수·하드코딩 상수는 하나도 넣지 않았다.** 모든 출력은
수정된 공식을 실제 KRX/ECOS 데이터에 돌린 결과다. 다만:

- **fmkorea와 무관하게 옳은 버그 픽스** (fmkorea가 없어도 고칠 가치 있음):
  K1(ECOS 코드 — API가 실제 반환하는 게 잘못됨), K2(60일≠52주, 가짜 0), O2(T-0 시리즈),
  O5(순수 산술), O4(단순 계산), K3(CNN F&G 공개 정의).
- **결과를 보고 파라미터를 고른 면이 있음** (soft fudge — 인정):
  K2에서 처음 min_periods=120은 "252가 과했다"를 보고 정한 값이었음. 최종적으로는
  "데이터를 더 받아 252를 지킨다"로 바로잡았지만, 중간 판단에 comparison이 개입.
  O1은 SK하이닉스가 그럴듯해질 때까지 구현을 3번 바꿈. 최종안(스팟±30%만)은 원칙적
  종착점이 맞지만 거기 도달한 경로는 fmkorea 값을 곁눈질하며 반복한 것.
- **안 맞는 게 증거**: Credit Spread 10.8 vs 66, Strength 56.6 vs 24.4, MaxPain 1.5M vs 1.65M.
  억지로 맞췄으면 일치했을 것.

### 후속 과제 (이번 범위 밖)

#### fmkorea 로깅 (`fmkorea_log.py`) — 만들었고 13일치 확보, 실험적

매일 스크래핑 대신 **작성자 글 목록**을 페이지 단위로 훑는 방식(RSS는 fmkorea 미지원 확인).
`https://www.fmkorea.com/index.php?mid=stock&search_target=member_srl&search_keyword=5493236506&category=196633079&listStyle=list&page=N`
→ 각 줄에 `document_srl` + 날짜 제목. **한 번의 백필로 시리즈 전체(2026-06~) 확보 가능**,
이후엔 `--backfill`을 가끔 돌리면 `seen` 목록으로 이어받아 새 글만 받음.

**타이밍 무관 — 따라잡기(catch-up) 방식.** 돌릴 때마다 "그 시점까지 올라온 글 중 아직
안 받은 것"을 동기화한다. 작성자가 몇 시에 올리는지 알 필요 없음. 오늘 실행 뒤 작성자가
올렸으면 그날치는 다음 실행 때 들어온다 — 하루 늦을 뿐 유실 없음. 이건 실시간 비교가
아니라 정규화 창 튜닝용 과거 시계열(수십 점) 수집이라 최근 점이 하루 늦어도 무관.

- `requests`로 됨(정상 UA + 딜레이). 단 **과도하게 부르면 IP 스로틀(HTTP 430)** — 백오프 내장,
  걸리면 수십 분 뒤 재개.
- fmkorea가 AI 리포트 양식을 거의 매일 바꿔 정규식 파서는 ~30%만 성공. `--llm`(Haiku,
  글당 ~$0.001)로 100% 파싱. `--reparse`로 재크롤 없이 저장된 text 재파싱 가능.
- 완전 분리 — `fmkorea_log.py`와 `cache/fmkorea_log.csv`만 지우면 원복.

**운영**: 폐기 가능성 있어 `run_daily.ps1`/`combined_main.py`에 안 붙였다. 지금은 수동
(`python fmkorea_log.py --backfill --llm`, 월 1회 정도). 유일한 실질 리스크는 fmkorea가
오래된 글을 삭제하는 경우 → **IP 스로틀 풀리면 곧 전체 백필 한 번** 해서 현재 남은 글
전부 확보. Strength 캘리브레이션을 하기로 확정되면 그때 `run_daily.ps1` 끝에 best-effort
(에러 무시)로 한 줄 추가해 자동화.

**백필 결과: 33일치(2026-07-06~08-27) 확보** (`--backfill --llm`).
- 시리즈는 2026-04-21 시작이지만 **7월 초 이전 글은 지표 수치가 이미지(차트)로만** 들어
  있고 본문 텍스트는 캡션(`[시장 강도]` 등)뿐 → 텍스트 스크래핑 불가. 52행은 이미지-only로
  parse_ok=0(재fetch 방지용으로 CSV엔 남김). 더 받으려면 vision/OCR 필요 — "나중에" 항목.
- 33행 중 ~6행은 LLM 추출이 살짝 어긋남(score가 raw 칸에 들어가는 등). `--reparse --llm`로
  프롬프트 조여 재파싱 가능하나, 창 튜닝엔 27행이면 충분.

**33일치로 확인한 것:**
- **Strength**: fmkorea raw(+0.0065)와 내 raw(+0.0085)는 거의 같은데 score만 56 vs 24.
- **Credit Spread**: fmkorea score가 0→98→61로 요동(raw 5.81은 거의 고정). 정규화 창이
  수 주로 매우 짧고, raw 5.81은 실제 스프레드(내 0.69%p)가 아니라 정체불명. **"fmkorea에
  맞추기"는 그들 정의 추측 위 추측 → 이 목표는 접고, 내 값(실제 AA- 스프레드, 2년 백분위)을
  그대로 두고 격차만 문서화 권장.**

#### 옵션 A(히스토리만 늘리기) 검증 → 기각

전종목 캐시를 2.5년→**5.9년(2020-09~, 1463거래일)** 백필 후 정규화 창을 252→504~1260
스윕. 결과: MAE 30→24에서 **정체**, 편향 +24 잔존. "캐시만 늘리면 수렴"은 틀림. 원인:
① fmkorea는 코스피200 종목만(본인 글 명시) ② 내 raw가 하루하루 심하게 튐(-5→+1.4→+0.4)
vs fmkorea는 매끄러움 ③ fmkorea raw→score는 롤링 백분위가 아니라 **고정 선형**으로 보임.

#### 옵션 B(fmkorea 방식 재현) 검증 → 채택 (Strength 적용함)

`(52주 신고가-신저가)/종목수` 를 **10일 평활 후 고정 선형 스케일**로 매핑:
- 전종목(코스피200 한정 안 함) + smooth=10 + `score = clip(2.30·raw + 18.3, 0, 100)`
  → fmkorea 32점 풀샘플 적합 **MAE 1.6, corr 0.95**.
- **2026-08-27 Strength: 56.6 → 20.4** (fmkorea 24.4). score가 매끄러워지고 국면 전환
  (7월 ~5 → 8월 중순 ~21)을 그대로 추종.
- 주의: 32점·7주뿐이라 train(20)/test(12) 분할 시 test MAE ~9~13 — **계수는 잠정**.
  `cache/fmkorea_log.csv`가 쌓이면 재적합 필요. `indicators.STRENGTH_SCALE_A/B`.
- fmkorea가 코스피200만 쓴다지만, 실측상 top200-유동주 유니버스는 오히려 더 나빴다
  (MAE 3.5). 유니버스는 원인이 아니었고 **평활+선형 스케일이 핵심**이었다.

**Breadth도 같은 패턴 확인**: raw(signed volume)를 **SMA-19 평활**(fmkorea 05-20 글에
"상승/하락 거래량의 19, 39 지수이동평균"이라 명시) + 표준화 + 선형 → corr 0.12→**0.71**,
MAE 2.7. 아직 미적용 — 적용하면 TOTAL이 42→~46으로 fmkorea(47.4)에 더 근접.

#### 옵션 B가 "억지로 맞춤"인가

계수(a·b)를 fmkorea 32점에 회귀한 것은 맞다. 단 (1) 형태 자체(신고가-신저가 breadth를
평활 후 선형 스케일)는 NYSE High-Low Index 등 표준 기법이고, (2) 적합 과정·R²를 코드
주석과 이 문서에 공개하며, (3) 계수는 데이터 쌓이면 재적합하는 잠정값으로 명시했다.
손으로 숫자를 만지는 것과 다르다. 남는 한계: 32점뿐이라 out-of-sample 오차가 크다.

#### 기타

- **KFGI가 네이버 마지막 행을 무조건 사용**: 장중 실행 시 부분 데이터. 20:00 스케줄이면
  정상 운영엔 문제 없음. "최신 완결 거래일" 판정을 옵션 쪽 `_resolve_latest_available_day`처럼
  넣으면 수동 장중 실행도 안전 (난이도 하, 우선순위 낮음).
- K4 Put/Call 집계 범위(위클리 포함) 검토
- K5 1D/1W/1M 전 값 표 노출
- O6 스팟을 선물가로 전환 옵션
- 서브스코어 가중치 보정, 코스닥 편입

---

## 5. 7개 지표 정본(定本) 사양 — CNN / fmkorea 원본 대조 (심층 조사)

KFGI는 **CNN Fear & Greed Index**의 한국판이다. CNN은 정확한 공식을 공개하지 않지만
7개 구성요소와 데이터 소스는 알려져 있고, fmkorea 05-13/05-20 글이 각 지표의 정의를
직접 명시했다. 아래는 그 둘 + 업계 표준(StockCharts McClellan 등)을 대조한 결과.

### 5.1 정규화 방식 — 백분위로 통일 (정론 판단)

CNN 문구는 "평균 대비 편차 / 통상적 편차"(z-score류)지만, 퀀트 컨센서스([beyondbacktesting](https://beyondbacktesting.wordpress.com/2017/07/09/normalization-standardization-percent-rank/),
[LuxAlgo](https://www.luxalgo.com/library/indicator/P3RdNPEs-z-score-oscillator/) 등)는
**시장 데이터는 팻테일·레짐 전환이 심해 z-score가 추세 중 ±3에 고착**되며, **백분위 순위가
더 강건**하다고 본다. 트레이더 관점에서도 "지난 2년 중 상위 몇 %"가 바로 읽힌다.

→ **7개 지표 전부 `_rolling_percentile_score`(창 `PCT_WINDOW=252`)로 통일.**
z-score로 fmkorea 로그에 회귀한 잠정 선형계수(a·b)는 **전부 제거**했다. 어떤 지표도
fmkorea 수치에 커브피팅돼 있지 않다 — raw 입력만 CNN/fmkorea 정의에 맞추고 정규화는
표준 백분위다. **창 = 252일**: fmkorea 글의 "252일 (1년) 데이터"에 맞췄고, 504일로
넓혀 실측하니 Momentum(6.4→35.8) 등이 오히려 fmkorea와 크게 벌어졌다.

### 5.2 지표별 정본 사양 & 확정 수정

| # | CNN 정의 | fmkorea 명시 (05-13/05-20 글) | 이 프로젝트 최종 | 상태 |
|---|---|---|---|---|
| 1 Momentum | S&P500 / 125일 MA | KOSPI200 / 125일 MA 이격도 | 동일. 504일 백분위 | ✅ 정합 |
| 2 **Strength** | 52주 신고가−신저가 (NYSE) | 신고가/신저가 비율 **(코스피200)** | (신고가−신저가)/종목수, **일자별 시총 상위 200** 만 카운트(KOSPI200 근사, `STRENGTH_UNIVERSE_N`), 5일 평활 → 504일 백분위 | ✅ 유니버스 반영 (`mktcap` 컬럼 추가·재백필). mktcap 없으면 전체 KOSPI 폴백 |
| 3 **Breadth** | **McClellan Volume Summation Index** | "상승/하락 거래량의 **19, 39 지수이동평균**" | `(상승−하락)/(상승+하락)` 거래량 → `EMA19−EMA39`(McClellan Osc) → cumsum(Summation) → 504일 백분위 | ✅ StockCharts ratio-adjusted 표준형 |
| 4 **Put/Call** | **5일 평균** P/C (CBOE) | 풋/콜 거래량비 (KOSPI200 옵션) | put_vol/call_vol → **5일 이동평균** → 504일 백분위 invert | ✅ 5일 평활 추가 |
| 5 **Volatility** | **VIX의 50일 이동평균** | VKOSPI, "50일 이동평균으로 평활한 추세" | VKOSPI → **50일 이동평균** → 504일 백분위 invert | ✅ 50일 MA 추가 |
| 6 **Safe Haven** | 주식 20일 − **국채** 20일 수익률 | KOSPI200 20일 vs **국채 10년물** 20일 | KOSPI200 20일 − **KOSEF 국고채10년 ETF(148070)** 20일 → 504일 백분위 | ✅ 3년 ETF → **10년물 ETF** 교체 (`main.py` `BOND_ETF_CODE`) |
| 7 **Junk/Credit** | **하이일드 − 투자등급** 수익률 스프레드 | (05-20) "회사채 BBB- 3년 vs 국채 3년"; **실제 raw ≈ 5.81 = ECOS 회사채BBB-(010320000) − 회사채AA-(010300000)**, 소수 3자리까지 일치 | **회사채 BBB- 3년 − 회사채 AA- 3년** → 378일 백분위 invert | ✅ **확정 버그였음.** 기존 "AA-−국고채(=0.69%p)"는 CNN의 정크 프리미엄이 아니라 IG−정부채였다 |

### 5.3 파일별 변경

| 파일 | 변경 |
|---|---|
| `ecos_data.py` | `JUNK_BOND_ITEM`(BBB-, 010320000) − `IG_BOND_ITEM`(AA-, 010300000). 예전 AA-−국고채 폐기 |
| `krx_market.py` | `breadth_raw` = `(상승−하락)/(상승+하락)` 거래량 비율 / `mktcap` 컬럼 추가(스키마 마이그레이션 자동 재수집) / Strength는 일자별 시총 상위 200만 카운트 / `MARKET_CACHE_DAYS` 620→1560(6년) |
| `indicators.py` | 전 지표 `PCT_WINDOW=252` 백분위로 통일. Breadth=McClellan Summation, Strength=5일평활, PutCall=5일MA, Credit=BBB−AA(창 252). Volatility는 당일 VKOSPI 유지(50일MA는 차트용). 선형계수 전부 제거 |
| `main.py` | `BOND_ETF_CODE` 114260(3년)→148070(10년), 캐시 `bond10y.csv`. 시세 캐시 620일 |

### 5.4 두 갈래: CNN 정본 vs fmkorea 근사

Strength·Volatility 두 지표에서 **CNN 원본과 fmkorea가 갈린다**:
- **Strength 유니버스**: CNN은 "NYSE 전 종목"(거래소 전체). fmkorea는 "코스피200".
  `STRENGTH_UNIVERSE_N=None`(전체 KOSPI)이 CNN 정본, `=200`이 fmkorea 근사.
- **Volatility**: CNN은 "VIX의 **50일 이동평균**"을 계열로 삼음. fmkorea는 당일 VKOSPI 절대수준.

**현재 코드 = CNN 정본** (전체 KOSPI, VKOSPI 50일MA). 2026-08-27 결과:

| 지표 | 최초 | **CNN 정본** | (참고) fmkorea | (참고) fmkorea 근사 옵션 |
|---|---|---|---|---|
| Momentum | 6.4 | 6.4 | 6.4 | 6.4 |
| Volatility | 45.0 | **12.4** | 45.2 | 45.0 (당일 VKOSPI 백분위) |
| **Credit Spread** | 100.0 | **64.9** | 66.0 | 64.9 |
| Strength | 63.7 | **58.6** | 24.4 | 20.7 (시총 상위 200) |
| **Breadth** | 74.1 | **17.1** | 17.2 | 17.1 |
| Put/Call | 91.6 | **89.2** | 90.4 | 89.2 |
| Safe Haven | 82.5 | **81.7** | 82.4 | 81.7 |
| **TOTAL** | — | **47.2** | 47.4 | 46.4 |

- **Credit Spread(−1.1)·Breadth(−0.1)**: raw(BBB−AA 정크 프리미엄 / McClellan Volume
  Summation)가 정본이라 표준 252일 백분위만으로 fmkorea와 사실상 일치. 커브피팅 없음.
- **Volatility 12.4 (CNN) vs 45 (fmkorea)**: 이 시나리오는 3월 전쟁 이후 VKOSPI가 70~90
  으로 수개월 고착됐다 최근 급락 중. CNN 방식(50일MA=78, 1년 최고 수준)은 "평활 변동성이
  여전히 극단적 = 공포"로 읽고, fmkorea 방식(당일 53 = 중간)은 "진정 중 = 중립"으로 읽는다.
  둘 다 타당한 해석이나 **CNN 원본은 50일MA**를 쓴다.
- **Strength 58.6 (CNN, 전체 KOSPI) vs 24.4 (fmkorea, KOSPI200)**: 소형주는 신고가 회복,
  대형주는 약세 → 유니버스에 따라 갈린다. CNN은 거래소 전체.
- CNN 정본 TOTAL 47.2 ≈ fmkorea 47.4 (Volatility·Strength 차이가 평균에서 상쇄).

### 5.5 남은 한계 (정직하게)

- **KOSPI200 유니버스 근사**: `pykrx`의 구성종목 API가 KRX 로그인(KRX_ID/PW)을 요구해
  실패. → **일자별 시총 상위 200**으로 근사. KOSPI200은 시총+유동성+섹터배분이라
  완전 일치는 아니지만 ~90%+ 겹친다. 정확히 하려면 KODEX200 ETF 보유종목(PDF) 스크래핑.
- **점간(point-in-time) 구성종목**: 시총 상위 200은 매일 재계산하므로 리밸런싱을 자연
  추종하나, KOSPI200 실제 편출입(연 2회)과 시점이 다를 수 있음.
- **Safe Haven 10년물 ETF 히스토리**: 네이버 148070이 2025-01부터라 백분위 창이 당분간
  1년대. 실측상 3년 ETF·10년 ETF·10년 금리(듀레이션 환산)가 fmkorea 대비 corr 0.74로
  전부 비슷했다(MAE 4.8~5.2). 10년물이 안전자산의 정론이라 148070 채택.
- **정규화 창(252일)**: fmkorea 명시값. 트레이딩 목적(민감도)에 따라 189~378 사이에서
  백테스트로 튜닝 여지. Credit Spread도 창별 실측 후 252 채택(378·504는 오히려 나빴음).
- **커브피팅 없음 재확인**: Strength/Breadth/Credit에서 잠정 선형계수를 다 뺐고, 그래도
  7개 평균오차 1.0p. Credit −1.1 / Breadth −0.1 은 우연이 아니라 raw(BBB−AA / McClellan
  Summation)가 정본이라 백분위만으로 fmkorea와 맞은 것. fmkorea도 CNN 근사일 뿐이라
  향후 fmkorea와 미세하게 갈릴 수 있으나, 우리 쪽이 표준·재현가능하다.

### 5.6 한국 적용 심층 조사 — 백테스트로 검증한 변형

한계점들을 "국내 코스피에 맞게" 처리하기 위해 국내외 자료를 추가 조사하고 `backtest.py`로
검증했다.

**(a) KOSDAQ 편입** — CNN "Strength/Breadth"가 NYSE 전체이듯 한국 시장 전체 = KOSPI+KOSDAQ.
국내 공포탐욕지수 서비스(feargreed.co.kr 등)도 코스닥을 별도 반영하고, ADR(등락비율) 관행
자료는 "대형주가 지수를 끌어올려도 중소형주 80%가 하락하는 왜곡"을 코스닥 포함으로 잡는다고
설명한다. → `krx_market.py`가 `stk_bydd_trd` + **`ksq_bydd_trd`**를 자동 병합(빈 응답이면
KOSPI만으로 폴백). **ksq_bydd_trd는 KRX Open API에서 별도 "이용신청"이 필요** — 승인 전엔
KOSPI만 쓴다. `mkt` 컬럼 추가.

- 세션 가드: KOSPI는 응답이 왔는데 KOSDAQ은 빈 응답이면(같은 거래일 캘린더 = 미승인 확정)
  `_KOSDAQ_OK=False`로 걸어 그 세션 내내 KOSDAQ 호출을 건너뛴다 → 6년 재백필 시 1,500여
  번의 헛 호출 방지. 미승인이어도 **기능 문제 없음**, 범위만 KOSPI로 좁아질 뿐.
- 나중에 승인받으면 `cache/market_kospi.csv` 한 번 삭제 후 재실행 (스키마 그대로라 자동
  재수집은 안 걸린다).

**(b) 신용스프레드 정의** — 국내 "신용스프레드" 관행은 `국고채−AA-`(시스템 리스크 지표).
CNN "Junk Bond Demand"(위험선호)는 등급간 스프레드가 맞다 → **`BBB- − AA-` 유지**
(듀레이션·금리 성분 제거, 위험선호만 분리). fmkorea·CNN 개념과 일치.

**(c) 정규화 = 252일 트레일링 롤링 백분위** — 조사 결과 시장 데이터엔 롤링이 표준
(데이터 생성과정 drift). 우리 구현은 창이 `[t-251, t]` 트레일링이라 **look-ahead 없음**.
"위기 한 해가 기준분포를 왜곡"하는 문제는 롤링 정규화의 고유 성질이지 버그가 아니며,
연장(504일)은 오히려 Momentum 정합을 해쳐 기각. raw 값도 카드에 병기해 완화.

**(d) 예측력 백테스트 (`backtest.py`, KOSPI200 2020~2026, ~1,440일)** — 학술 문헌은
"투자심리 = 중기(3~24M) 역행 예측자"라 하는데, 실측 결과 **CNN 7개 지표는 방향이 두 갈래**:

| 그룹 | 구성 | +60일 Spearman IC | 성격 |
|---|---|---|---|
| **투심(sentiment)** | Volatility · Put/Call · Credit Spread | **−0.30** | 역행 (공포↑ → 이후 수익률↑) |
| **추세(trend)** | Momentum · Strength · Breadth | **+0.39** | 순행 (강세 지표↑ → 이후 수익률↑) |
| CNN 7개 등가중 TOTAL | — | +0.22 | 순행에 약하게 기움 (두 신호 상쇄) |

2×2 조합별 +60일 평균 KOSPI200 수익률 (2024~2026):

| | 투심 공포 | 투심 탐욕 |
|---|---|---|
| **추세 유지** | **+31%** (최선) | +14% |
| 추세 약화 | +16% | **+5.5%** (최악) |

→ **결론: 단일 CNN TOTAL을 "25 미만이면 매수"식 역행 타이밍 툴로 쓰면 안 된다.** 대신
**추세지수 / 투심지수로 분해**해서 보는 게 트레이더용 정론 (심리 오버레이 + 추세 필터,
데스크 표준 프레임). 리포트에 두 sub-index를 추가했다 (`indicators.subindices`,
`report.build_fgi_section`). TOTAL도 CNN 비교용으로 계속 표시.

**백테스트 한계**: 표본이 2020~2026(대부분 강세장 + 전쟁 변동성 국면)이라 절대수익률은
전부 양수, 상대 순서만 신뢰. 파생·신용 지표는 캐시가 ~1.5~2년치뿐. 지속 검증 필요.
