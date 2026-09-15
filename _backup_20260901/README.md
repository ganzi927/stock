# 오늘의 코스피 (개인용)

fmkorea "곰곰이곰곰"님이 매일 올리는 "오늘의 코스피" 시리즈(공포탐욕지수 편 / 옵션편 /
삼성전자·SK하이닉스 옵션편)를 참고해서 만든 개인용 버전. 매일 실행하면
`reports/YYYY-MM-DD.html` 파일 하나에 **탭 4개**(공포탐욕지수 / 코스피200 옵션 /
삼성전자·SK하이닉스 / 종합 전망)로 전부 담긴다 (이미지 base64 내장이라 파일 하나로
공유/보관 가능). 4번째 "종합 전망" 탭은 앞 3개 탭 수치를 모아 Claude가 내일 시나리오를
정리한다 (`ANTHROPIC_API_KEY` 없거나 `.env`에 `KFGI_AI=0` 이면 AI 코멘트·전망만 생략, 나머지
정상). 디자인은 웜 모노크롬 팔레트 + 에디토리얼 타이포그래피의 미니멀 카드 레이아웃.

**지표 방법론은 CNN Fear & Greed Index 정본에 맞춰 재구현했다** — 자세한 조사·검증·
fmkorea 대조는 [`RECONCILIATION.md`](RECONCILIATION.md).

## 빠른 시작

```bash
python -m venv venv
venv\Scripts\activate          # (bash면 source venv/Scripts/activate)
pip install -r requirements.txt
python main.py
```

실행하면 `reports/오늘날짜.html` 이 생성된다. 더블클릭해서 브라우저로 열면 됨.

매일 자동 실행하고 싶으면 Windows 작업 스케줄러에 `python main.py`를 평일 저녁
(예: 18:00) 실행하도록 등록하면 된다.

## 데이터 소스

| 데이터 | 출처 | 필요한 것 |
|---|---|---|
| KOSPI / KOSPI200 일별 시세 | 네이버 금융 (`finance.naver.com/sise/sise_index_day.naver`) | 없음 |
| 국고채10년 ETF(KOSEF, 148070) 일별 시세 | 네이버 금융 (`finance.naver.com/item/sise_day.naver`) | 없음 |
| 정크 프리미엄(회사채 BBB- − AA-) | 한국은행 ECOS Open API (`817Y002`, `010320000`/`010300000`) | `ECOS_API_KEY` (선택, 무료) |
| VKOSPI, 옵션 풋콜비율, 전종목 시세(KOSPI+코스닥) | **KRX Open API** (`openapi.krx.co.kr`) | `KRX_API_KEY` (선택, 무료) |

> `data.krx.co.kr`의 일반 통계 페이지는 최근 로그인 없이는 막혔지만, KRX가 별도로
> 운영하는 **Open API 포털**(`openapi.krx.co.kr`)은 무료 회원가입 + API별 "이용신청"
> (즉시 자동승인)만 하면 VKOSPI·옵션·전종목 시세를 그대로 받을 수 있다. 이 프로젝트는
> 그 경로로 4개 지표를 근사치에서 실제값으로 업그레이드했다.

### KRX Open API 키 받는 법 (선택, 강력 추천)
1. https://openapi.krx.co.kr 회원가입 (무료, 아이디/비번 또는 네이버·카카오 간편가입)
2. 마이페이지 > API 인증키 신청 → 인증키 발급 (마이페이지의 "샘플 테스트"는 KRX 공용
   데모키만 통하는 별도 엔드포인트(`openapi.krx.co.kr/svc/sample/apis/...`)이니 거기서
   내 키가 401이 나도 정상이다 — 내 키는 운영 엔드포인트(`data-dbg.krx.co.kr/svc/apis/...`)
   에 써야 한다.)
3. 아래 API 상세페이지에서 각각 "API 이용신청" 클릭 (기간 12M, 목적 "개인연구" 정도면
   충분, 즉시 자동승인됨):
   - 파생상품 > 옵션 일별매매정보 (주식옵션外) — `opt_bydd_trd`
   - 지수 > 파생상품지수 시세정보 — `drvprod_dd_trd`
   - 주식 > 유가증권 일별매매정보 — `stk_bydd_trd`
   - 주식 > 코스닥 일별매매정보 — `ksq_bydd_trd` *(선택 — Strength/Breadth를 코스닥까지
     포함해 계산. 미신청 시 자동으로 KOSPI만 사용)*
4. `.env.example`을 `.env`로 복사하고 `KRX_API_KEY=발급받은키` 입력 (main.py가 자동으로 읽음)

키가 없으면 Volatility/Strength/Breadth는 자동으로 근사치(proxy)로, Put/Call Ratio는
N/A로 표시될 뿐 나머지는 정상 작동한다.

### ECOS API 키 받는 법 (선택)
1. https://ecos.bok.or.kr 회원가입 (무료, 즉시 승인)
2. Open API 메뉴에서 인증키 신청
3. `.env`에 `ECOS_API_KEY=발급받은키` 입력

## 7개 지표 — CNN Fear & Greed 정본 방식 (한국 지표 치환)

**KFGI = CNN Fear & Greed Index의 한국판.** CNN의 7개 구성요소 정의 + fmkorea 원본 글의
명시 방법론 + 업계 표준(StockCharts McClellan 등)을 대조해 raw 정의를 맞췄다.
자세한 조사·검증 과정과 fmkorea 수치 대조는 **[`RECONCILIATION.md`](RECONCILIATION.md) §5** 에 있다.

| 지표 | raw 정의 (= CNN 방식) | 데이터 |
|---|---|---|
| Momentum | KOSPI200 / 125일 이동평균 이격도 | 네이버 |
| Volatility | **VKOSPI의 50일 이동평균** | KRX Open API |
| Credit Spread (Junk Bond Demand) | **회사채 BBB-(3Y) − 회사채 AA-(3Y)** 정크 프리미엄 | ECOS |
| Strength | **전체 KOSPI**(+코스닥, 승인 시) 52주 신고가−신저가 종목수 비중 | KRX Open API |
| Breadth | 상승/하락 거래량 **ratio-adjusted McClellan Volume Summation Index** | KRX Open API |
| Put/Call Ratio | 코스피200 옵션 풋/콜 거래량비의 **5일 이동평균** | KRX Open API |
| Safe Haven Demand | KOSPI200 20일 수익률 − **국고채10년 ETF(148070)** 20일 수익률 | 네이버 |

- 점수화: 각 raw를 **직전 252거래일 백분위(0~100)**로 (`indicators._rolling_percentile_score`,
  트레일링 창이라 look-ahead 없음). 점수↑ = 탐욕. fmkorea 로그에 회귀한 커브피팅 계수는 없다.
- **TOTAL** = 가용 서브스코어 등가중 평균 (CNN 방식).
- **추세지수 / 투심지수**: 백테스트(`backtest.py`)상 CNN 7개는 예측 방향이 두 갈래다 —
  파생·신용 3개(Volatility·Put/Call·Credit)는 **역행**(공포↑ → 이후 수익률↑, +60일 IC ≈ −0.3),
  가격·저변 3개(Momentum·Strength·Breadth)는 **순행**(+0.39). 리포트는 이 둘을 나눠서도
  보여준다 (`indicators.subindices`). 단일 TOTAL을 "25 미만이면 매수"식으로 쓰면 안 된다.
- KRX_API_KEY / ECOS_API_KEY 없으면 해당 지표는 proxy 또는 N/A로 폴백 (`indicators.compute_*_proxy`).

## 다음 단계 (원하면)

- **코스닥 편입**: `krx_market.py`가 `ksq_bydd_trd`(코스닥 일별매매정보)를 자동 병합하도록
  돼 있으나, KRX Open API에서 그 API를 별도 **"이용신청"**해야 활성화된다(무료·즉시승인).
  승인 후 `cache/market_kospi.csv` 한 번 지우고 재실행.
- **가중치 보정 / 실전 룰 백테스트**: `backtest.py`가 IC·분위까지 검증한다. 거래비용 포함
  워크포워드는 미실시.
- **fmkorea 로깅**: `fmkorea_log.py` 로 fmkorea "오늘의 코스피" 시리즈 수치를 `cache/fmkorea_log.csv`
  에 증분 저장(비교·재적합용). `python fmkorea_log.py --backfill --llm`.

## 옵션 딜러 포지셔닝 리포트 (`options_main.py`)

fmkorea의 "오늘의 코스피 - 옵션편"을 참고해서 만든 KOSPI200 옵션 분석. 실행하면
`reports/options-YYYY-MM-DD.html`에 정규월물 + 위클리(목요일 만기) 두 섹션이 담긴다.

```bash
python options_main.py
```

### 계산 방식
KRX Open API는 옵션의 가격·거래량·미결제약정·내재변동성(IV)만 제공하고 델타/감마 같은
그릭스는 주지 않는다. 그래서 `greeks.py`에서 **Black-Scholes 공식으로 직접 계산**한다.

무위험이자율(r)과 배당수익률(q)은 가능하면 실제 시장 데이터에서 역산하고, 안 되면
상수(r=3.0%, q=1.5%)로 대체한다 — 각 섹션 제목 옆에 어느 쪽을 썼는지 "(시장)"/"(가정)"으로
표시된다.
- **r**: KRX Open API의 `3개월무위험금리 선물`(`fut_bydd_trd`) SPOT_PRC(=100−금리)에서 계산
- **q**: 같은 API의 `코스피200 선물` 가격 F와 스팟 S, 위에서 구한 r로 F=S·e^((r−q)T)를 풀어서 역산.
  값이 ±5%를 벗어나면(유동성 부족 등으로 비정상) 상수로 폴백

### 지표 정의 — 웹 검색으로 교차 검증 (추측 없음)
[SqueezeMetrics 공식 가이드](https://squeezemetrics.com/monitor/static/guide.pdf), [SpotGamma](https://spotgamma.com/gamma-exposure-gex/),
[FlashAlpha](https://flashalpha.com/concepts/dex), [MenthorQ](https://menthorq.com/guide/what-is-delta-exposure-dex/),
[Wikipedia Greeks(finance)](https://en.wikipedia.org/wiki/Greeks_(finance)) 등 업계·학술 자료를 직접 찾아 대조한 결과:

| 항목 | 계산 방식 | 검증 상태 |
|---|---|---|
| Delta/Gamma/Vega/Theta/**Vanna**/**Charm** (BS 그릭스) | `greeks.py` | ✅ Wikipedia "Greeks (finance)" 표준 테이블과 항 단위로 완전히 일치 확인 |
| GEX | `Γ × OI × 100 × Spot² × 0.01`, 콜=+, 풋=− | ✅ 여러 출처 교차 확인, 우리 구현과 일치 |
| MaxPain | 각 행사가를 만기 결제가로 가정했을 때 콜+풋 전체 내재가치 총합이 최소가 되는 지점 | ✅ 표준 정의 |
| Zero Gamma / Gamma Flip | 가상 스팟을 스캔하며 합산 GEX가 부호를 바꾸는 지점 | ✅ 여러 출처 교차 확인 |
| **Call Wall** | 콜 GEX만 따로 봤을 때 최댓값 지점 (스팟 위/아래 무관) | ✅ SpotGamma/FlashAlpha 정의 |
| **Put Wall** | 풋 GEX만 따로 봤을 때 최댓값(절대값) 지점 (스팟 위/아래 무관) | ✅ SpotGamma/FlashAlpha 정의 |
| DEX Neutral MaxPain | 가상 스팟을 스캔하며 Net Delta가 0이 되는 지점 | 자체 정의 (표준 용어 아님, 부호 반전에 영향받지 않는 값) |
| **Net DEX** | `-Σ(OI×BS델타)` — 콜/풋 구분 없이 전체에 −1 (아래 참고) | ✅ FlashAlpha/MenthorQ 명시적 확인 |
| Vanna Flow / Charm Flow | Σ(OI×바나 또는 참) × 딜러부호(콜=+,풋=−) | ✅ GEX와 같은 부호 규약 적용 확인 (FlashAlpha) |

**"Dealer Equilibrium"은 표준 용어가 아님**: SpotGamma, MenthorQ, CheddarFlow, InsiderFinance, FlashAlpha
등 주요 업계 자료를 검색해도 나오지 않았다 — 원본(fmkorea) 작성자가 쓰는 도구의 자체 용어로 보여서
채택하지 않고 **Call Wall/Put Wall로 교체**했다 (예전엔 "스팟 위쪽 GEX 상위 3개"라는 자체 추측 로직을
썼는데, 이게 실제로 삼성전자 사례에서 원본과 방향이 틀렸던 원인이었다 — Call Wall/Put Wall은 콜/풋으로
나누지 스팟 위/아래로 나누지 않는다는 걸 알고 나니 설명이 됐다).

**DEX 부호 규약 — 재검토 후 뒤집음**: 1차 검토 때는 출처마다 표기가 갈려서("콜=+1·풋=-1을 델타에
곱한다"는 FlashAlpha 표기가 BS 델타의 기존 부호와 곱해지면 풋도 양수가 되는 모순처럼 보였음)
"추가 부호 없이 BS 델타 그대로 합산"으로 정했었다. 이번 2차 웹 검색에서 FlashAlpha 기사
원문을 직접 인용해보니 실제 의미는 "고객이 콜·풋을 모두 순매수 → 딜러는 콜·풋을 모두
순매도"였다: *"call delta contributes negatively to dealer DEX ... and put delta contributes
positively"* — 즉 콜/풋 각각 부호를 다르게 곱하는 게 아니라 **전체 합에 −1을 곱하는 것**이었다.
[MenthorQ](https://menthorq.com/guide/what-is-delta-exposure-dex/)도 "고객이 콜을 사면 딜러는
콜 숏 → Negative DEX"라고 같은 방향으로 설명해 두 출처가 일치했다. 다만 fmkorea 원본 게시글을
다시 확인해보니 애초에 "Net DEX" 원시 수치 카드 자체가 없었다(DEX는 "DEX Neutral MaxPain",
"Put/Dex Support" 같은 레벨 이름에만 등장) — 그래서 "원본과 비교"로는 판단할 수 없었고, 사용자
판단으로 **부호 반전(딜러 콜·풋 모두 숏 가정)을 채택**했다. `dex_neutral_maxpain`처럼 0교차
지점을 찾는 값은 전체 부호 반전에 영향받지 않으므로 이번 변경으로 값이 바뀌지 않는다.

### (정정됨) 옵션 행사가 997.5 상한 — "무료 API 한계"가 아니라 파싱 버그였다
한동안 "옵션 행사가 상한이 997.5로 고정되어 있어 현재가보다 위쪽 레벨을 계산할 수
없다"고 이 문서에 적어뒀고, 4월/6월/8월 여러 날짜로 재현까지 해보며 "무료 API 티어
자체의 구조적 한계"라고 결론 내렸었다. **이건 틀린 진단이었다.**

실제 원인은 `options_data.py`의 종목명 파싱 정규식(`_REGULAR_RE`, `_WEEKLY_RE`)이
`[\d.]+`로 되어 있어서, 행사가가 1,000 이상이라 천단위 콤마가 붙는 순간
("코스피200 C 202609 **1,000.0** (정규)") 정규식이 매치를 실패해 그 계약을 통째로
누락시키고 있었던 것이다. KOSPI200이 오랫동안 1,000 미만이었을 땐 콤마가 붙을 일이
없어서 안 드러나다가, 지수가 1,000을 넘으면서 상위 행사가가 전부 조용히 사라진
것 — "997.5"가 항상 딱 떨어지게 상한으로 잡혔던 것도 우연이 아니라 **1,000 미만
마지막 행사가**였기 때문이다.

원인을 찾은 계기: 사용자가 KB증권에서 다운로드한 실제 "투자자별 순매수" 엑셀에
1,597.5까지의 행사가가 버젓이 들어있는 걸 보고서야 "무료 API가 정말 여기까지만
주는 게 맞나?"를 의심하게 됐고, KRX API 원본 JSON 응답을 직접 까봤더니 1,000 이상
행사가 데이터가 처음부터 다 와 있었다 (`ISU_NM`에 "1,000.0", "1,200.0" 등으로).
정규식만 `[\d,]+(?:\.\d+)?`로 고치고 콤마를 제거한 뒤 float 변환하니 정규월물 기준
행사가 개수가 532개→1,012개로 늘고 범위도 335~997.5에서 335~1,597.5로 정상화됐다.

**교훈**: "데이터가 없다"고 결론 내리기 전에 원본 API 응답(파싱 이전 raw JSON)을
먼저 봤어야 했다 — 우리 쪽 파싱 코드의 버그를 API/데이터 자체의 한계로 오인했었다.
이제 Call Wall이 스팟 위쪽에서도 정상적으로 계산되고, 경고 배너도 실제로 행사가
범위를 벗어난 경우에만 뜬다.

### 실제 투자자별 순매수 (수동 업로드, `investor_flow.py`)
KB증권 HTS/MTS에서 "상장일 누적 옵션 투자자별 순매수" 엑셀(금액/수량 두 파일)을 직접
다운로드해서 `uploads/` 폴더에 넣으면, `combined_main.py`가 자동으로 감지해서 "코스피200
옵션" 탭 맨 아래에 참고용 카드로 표시한다. 파일이 없으면 조용히 건너뛴다.

이 기능을 추가한 이유: 실제로 파일을 열어봤더니 "합계" 행 기준 **금융투자(국내 증권사,
이 프로젝트가 GEX/DEX 계산에서 가정하는 '딜러'에 가장 가까운 분류)가 콜·풋 옵션을 모두
순매수**하고 있었다 — 이 프로젝트가 쓰는 SqueezeMetrics/FlashAlpha류 업계 표준 부호
가정(딜러가 콜은 롱·풋은 숏, 또는 콜·풋 모두 숏)과 정반대다. 이 표준 가정은 미국 리테일
옵션시장(개인이 콜/풋을 직접 사는 문화)을 전제로 하는데, 한국 KOSPI200 옵션은 실제로는
개인이 콜·풋 모두 순매도하고 금융투자·외국인이 순매수하는 반대 양상을 보였다.

**자동화는 불가능하다**: KRX Open API 공식 서비스 목록을 확인했지만 파생상품 카테고리엔
"일별매매정보"만 있고 투자자유형별 데이터는 없다 — data.krx.co.kr의 유료/회원용 통계를
KB증권이 재가공해서 보여주는 화면이라 수동 다운로드로만 가져올 수 있다.

**이 데이터로 GEX/DEX 부호 가정을 "검증"하려던 시도는 재검토 후 기각했다**: 처음엔 "금융투자가
실제로 콜·풋 다 순매수하니 우리 부호 가정이 틀렸다"고 판단할 뻔했는데, 추가 조사 결과 이 비교
자체가 성립하지 않는다는 걸 확인했다.
- [SpotGamma의 DDOI(딜러 방향 미결제약정) 설명](https://support.spotgamma.com/hc/en-us/articles/15246735925395-DDOI-Dealer-Directional-Positioning)에 따르면 "DDOI 정보는 공개되지도 상업적으로
  구매 가능하지도 않으며 모델링으로 추정할 수밖에 없다 — 어떤 마켓메이커도 전 세계 모든 북에
  대한 이 정보를 갖고 있지 않다." 즉 **딜러의 실제 방향성 포지션은 미국 시장에서조차 구조적으로
  관측 불가능**하다 — 한국 데이터가 부족해서가 아니라 전 세계 어느 옵션시장에서나 그렇다.
- [SqueezeMetrics 가이드](https://squeezemetrics.com/monitor/static/guide.pdf) 역시 "GEX는 딜러 포지션을 가정할 수밖에 없다 — 미결제약정은
  계약 수만 알려줄 뿐 누가 어느 쪽을 들고 있는지는 알려주지 않는다"고 명시한다.
- KB증권의 '금융투자' 분류는 마켓메이킹 데스크만이 아니라 ELS/구조화상품 헤지, 자기매매,
  랩어카운트 운용까지 다 섞인 광범위한 집계라, 애초에 "딜러 인벤토리"의 대용치로 쓰기에
  적절하지 않다.

결론: GEX/Vanna/Charm/DEX 부호 가정은 "검증된 사실"이 아니라 (미국 시장 포함) 어디서도
검증이 불가능한, 업계가 합의한 모델링 관행이다.

### 행사가별 실제 부호 반영 — 만들었지만 기본적으로 꺼둠
사용자가 "완벽한 딜러 인벤토리가 아니어도 금융투자 데이터로 계산해달라"고 요청해서
`investor_flow.build_strike_sign_overrides()`를 만들었다. KB증권 파일에서 **행사가별**
금융투자 콜/풋 순매수 부호를 뽑아(금액·수량 두 파일의 부호가 일치하는 행사가만 채택),
`dealer_positioning.py`의 GEX/VEX/Charm/DEX 계산에서 그 행사가만 실제 부호로, 나머지는
업계 표준 가정으로 대체하는 기능이다 (`with_greeks_at_spot`/`gex_profile`/
`compute_dex_neutral`의 `sign_overrides` 인자로 남아있음).

**켜봤더니 fmkorea 원본과의 일치도가 오히려 나빠져서 기본값을 끔(`options_main.py`에서
`sign_overrides=None` 고정)**: 2026-08-26 기준 정규월물 Zero Gamma가—
- 순수 업계 표준 가정: **1,049.9** (원본 1,046.4 대비 **0.3%** 차이)
- KB 행사가별 부호 반영(426/1012개 대체): **457.4** (원본 대비 **56%** 차이)

금융투자가 그 시점 콜·풋 다수 행사가에서 순매수(롱)였던 탓에 Net GEX가 넓은 구간에서
양(+)으로 쏠리면서 Zero Gamma가 스팟에서 멀리 튀어버렸다. 계산 자체가 틀린 게 아니라
(금융투자가 정말 그렇게 포지션돼 있었다면 논리적으로 나올 수 있는 결과), fmkorea
원본과 맞춰본다는 이 프로젝트의 목적에는 순수 가정 방식이 더 잘 맞았다. 코드는
남겨뒀으니 나중에 재검토하고 싶으면 `options_main.py`의 `generate_options_sections()`에서
`None` 대신 `investor_flow.build_strike_sign_overrides(BASE_DIR / "uploads")`를 다시
넣으면 된다. KB증권 업로드 파일은 계산과 무관하게 참고용 카드로는 계속 표시된다.

### 생략한 것
- **IV Rank**: 오늘부터 캐시가 쌓이기 시작해서(`cache/atm_iv_regular.csv`,
  `cache/atm_iv_weekly.csv`) 처음 며칠은 백분위 의미가 약함.

### 추가 지표 (PoT / DEX·Vanna 프로파일 / 25델타 Risk Reversal / 합성지수)
fmkorea "일북어" 님의 더 고급 분석글들을 참고해서, 그중 새 데이터 없이 무료 데이터로
바로 계산 가능한 4개를 추가했다 (`greeks.py`, `dealer_positioning.py`, `options_charts.py`):
- **PoT(Probability of Touch)**: 만기 전 특정 레벨을 한 번이라도 터치할 위험중립 확률.
  브라운 운동 first-passage 공식(반사원리) — 드리프트 0일 때 `2·N(-|b|/(σ√T))`로
  축약되는 걸로 검증함. `greeks.probability_of_touch()`.
- **DEX/Vanna 프로파일**: 기존 GEX 프로파일과 같은 방식으로, 가상 스팟마다 Net
  DEX/Vanna를 계산해 곡선으로 표시 (`dealer_positioning.dex_profile/vanna_profile`).
- **25델타 Risk Reversal**: 25델타 콜 IV − 25델타 풋 IV. 업계 표준 지표(SpotGamma
  "25D Risk Reversal" 등에서 확인).
- **풋-콜 패리티 합성지수**: `S = (C−P+K·e^(−rT))·e^(qT)`로 행사가별 내재 스팟을
  역산해서 실제 스팟과 괴리(고평가/저평가)를 보여줌.

### AI 코멘트 (Claude API, 선택 사항)
`ai_commentary.py` / `outlook.py` — `ANTHROPIC_API_KEY`가 `.env`에 있으면 생성한다
(Haiku 4.5, 하루 6콜 = 5개 섹션 코멘트 + 종합 전망, 월 $1 안팎).
`.env`에 `KFGI_AI=0` 을 넣으면 키가 있어도 LLM을 전혀 안 부른다(비용 0, AI 부분만 빠짐).
**투자 조언·방향 예측은 시스템 프롬프트에서 명시적으로 금지** — PoT/시나리오 확률을
사실로 인용하고 딜러 헤지 메커니즘만 설명하도록 제약함. 프롬프트 캐싱은 Haiku
최소 캐시 단위(2,048토큰)보다 프롬프트가 짧아 적용 안 됨(확인함).

### Call Wall/Put Wall 계산 범위 제한 (딥ITM/OTM 왜곡 방지)
2026-08-26 SK하이닉스에서 행사가 1,050,000(스팟 대비 -38%) 콜에 미결제약정
72,007계약(오늘 거래량은 3계약)이 쌓여있어 Call Wall이 스팟과 무관한 딥ITM
행사가로 잘못 끌려가는 걸 발견했다 — 파싱 오류 아니고 KRX 원본 데이터로 확인함
(오래된 잔존 포지션으로 추정). `find_walls()`에 스팟 대비 ±30% 범위 제한을
추가해서 해결(스팟 근처에서만 Call Wall/Put Wall을 찾음).

## 삼성전자 / SK하이닉스 옵션 (`stock_options_main.py`)

같은 딜러 포지셔닝 분석을 개별주식 옵션(`eqsop_bydd_trd`)에도 적용한 것. 코스피200
옵션과 달리 **행사가가 스팟을 양쪽으로 완전히 감싸고 있어서** Zero Gamma/Call Wall/
Put Wall이 전부 정상적으로 계산된다 — 실제로 삼성전자 Zero Gamma(260,420.6)가
fmkorea 원본(260,720.5)과 거의 일치했다.

```bash
python stock_options_main.py   # reports/stock-options-YYYY-MM-DD.html 단독 생성
```

계약 승수는 종목명에 표기된 값(현재 10주)을 그대로 파싱해서 쓴다. 배당수익률(q)은
개별주식 선물 데이터를 아직 연동 안 해서 상수 가정을 쓴다 (README 상단 r/q 설명 참고).

### 버그 픽스: 넓은 행사가 범위에서 생기는 가짜 0교차
SK하이닉스처럼 상장 행사가 범위가 스팟보다 훨씬 넓고(28만~380만원) 특정 행사가에
거래 없이 1계약만 걸려있는 경우, 단순 min/max로 그리드를 잡으면 스팟과 무관한
지점에서 수치적으로만 의미있는 가짜 Zero Gamma가 나올 수 있었다 (실제로 스팟
1,688,000원인데 331,000원대의 값이 나온 적 있음). `dealer_positioning.py`의
`_oi_weighted_strike_range`가 미결제약정 누적 2~98% 구간으로 그리드를 제한해서
해결했다 — 그래도 crossing이 없으면 억지로 값을 만들지 않고 N/A로 둔다.

## 파일 구조

```
naver_data.py           - 네이버 금융 스크래핑 + 로컬 CSV 캐시 (KOSPI/KOSPI200/국고채10년ETF)
ecos_data.py            - 한국은행 ECOS: 회사채 BBB-·AA- 금리 → Credit Spread (선택)
krx_api.py              - KRX Open API: VKOSPI, 옵션 풋콜비율 (선택)
krx_market.py           - KRX Open API: 전종목 시세(KOSPI+코스닥) → Breadth/Strength (선택)
indicators.py           - KFGI 7개 지표 계산 + 추세/투심 sub-index (CNN 정본 방식)
charts.py               - KFGI 게이지/추이 차트 (matplotlib → base64 PNG)
report.py               - KFGI HTML 리포트 조립 (카드 레이아웃)
main.py                 - KFGI 실행 진입점 (KRX_API_KEY 필요)
outlook.py              - 4번째 탭 "종합 전망": 세 섹션 수치를 모아 Claude가 내일 시나리오 작성
backtest.py             - KFGI의 KOSPI200 미래수익률 예측력 검증 (IC·분위·극단·그룹분해)

RECONCILIATION.md       - fmkorea 대조 + CNN 정본 방법론 조사·수정 이력 (§5가 현행 지표 사양)
fmkorea_log.py          - fmkorea "오늘의 코스피" 수치 증분 로깅 (비교·재적합용, 선택)

greeks.py               - Black-Scholes 그릭스 계산
options_data.py         - KOSPI200 옵션 체인 조회/파싱 (KRX Open API, 필수)
dealer_positioning.py   - MaxPain/Zero Gamma/Call Wall/Put Wall/DEX·VEX·Charm 계산
options_charts.py       - GEX 프로파일/변동성 스마일 차트
options_report.py       - 옵션 리포트 HTML 조립
options_main.py         - 코스피200 옵션 실행 진입점 (KRX_API_KEY 필요)

stock_options_data.py   - 개별주식(삼성전자/SK하이닉스) 옵션 체인 조회/파싱
stock_options_main.py   - 개별주식 옵션 실행 진입점 (KRX_API_KEY 필요)

investor_flow.py        - KB증권 수동 업로드 "투자자별 순매수" 엑셀 파싱 (선택, 파일 없으면 건너뜀)
ai_commentary.py        - Claude API 초보자용 코멘트 생성 (선택, ANTHROPIC_API_KEY 없으면 건너뜀)
uploads/                - KB증권 등에서 수동 다운로드한 옵션 관련 엑셀을 넣는 폴더

combined_main.py        - **매일 자동 실행되는 진입점.** 위 셋을 탭 3개로 묶어
                          reports/YYYY-MM-DD.html 하나로 생성 (run_daily.ps1이 호출)

cache/          - 일별 시세 캐시 (첫 실행시 자동 생성, 이후 증분 갱신)
reports/        - 날짜별 HTML 리포트 출력
                  (YYYY-MM-DD.html=통합, options-*.html/stock-options-*.html=단독 실행용)
```
