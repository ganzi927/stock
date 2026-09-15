# 작업계획서 — 방법론 엄밀화 (fmkorea 재현 → 검증 가능한 지표로 전환)

작성 기준일: 2026-08-28. 대상: `indicators.py`, `greeks.py`, `dealer_positioning.py`,
`krx_market.py`, `ecos_data.py`, `options_data.py`, `backtest.py` 및 관련 리포트 모듈.

이 문서는 `RECONCILIATION.md`(fmkorea 대조 이력)의 **후속**이다. RECONCILIATION은
"블로거 수치에 얼마나 근접했나"를 다뤘고, 이 문서는 그 목표 자체를 재설정한다.

---

## 진행 상황 (2026-08-28 착수)

| Phase | 상태 | 비고 |
|---|---|---|
| 0 데이터 스파인 | ✅ 대부분 | `_backfill_sentiment.py` 로 VKOSPI·풋콜 2016~ 딥백필(진행 중), 신용스프레드·국고채10년 ECOS 2016~ 완료. `ecos_data.py` 캐시 우선 + 합성 10년 채권지수. `DATA_INVENTORY.md` 작성. KOSPI200 지수는 `backtest.py` 첫 실행이 2600일 백필 |
| 1 명백한 버그 | ✅ | Breadth = McClellan Oscillator 백분위(cumsum 폐기), Strength 선형계수 흔적 제거, 결측 IV = log-moneyness 스마일 보간(`fill_iv_smile`), `min_periods` 20→126, `_zscore_score` 삭제, doc/code 정합 |
| 2 복합지수 | ✅ | TOTAL 헤드라인 강등(참고값), 추세지수 = mean(Momentum, mean(Strength,Breadth)) 1:1 재가중, 상관행렬 리포트 병기(`subscore_correlations`) |
| 3 검증 하니스 | ✅ | `backtest.py` 전면 재작성 — stationary bootstrap 90% CI, n_eff, 7/7 구성 일관 서브샘플, 변동성 레짐 분해, 2×2 표 폐기. `VALIDATION.md` 생성 완료 (2016~2026, 2510 거래일). **결과**: 투심 그룹만 CI가 0을 벗어남(그나마 credit_spread=매트릭스 프라이싱 계단 series가 견인, 실질 2020·2022 두 위기). Momentum 겨우 유의. Strength·Breadth·Put/Call·Safe Haven·TOTAL7은 전부 CI가 0 포함 = 예측력 입증 실패 |
| 4 옵션 범위 축소 | ✅ | `SIGN_CONVENTION_CAVEAT` 배너(리포트·AI 프롬프트), Zero Gamma 모델오차 밴드(`analyze`가 r/q/IV 흔들어 산출), MaxPain 약한 근거 명시, PoT 위험중립 재라벨, `build_scenarios` 인과 서사 조건부화 |
| 5 fmkorea → 부록 | ⏳ | `fmkorea_log.py` 는 그대로(수동 수집기). RECONCILIATION.md 는 이력으로 보존 |

착수 전 파일 스냅샷: `_backup_20260828/`.

---

## 0. 전략적 방향 재설정

프로젝트가 상충하는 두 목표를 한 코드베이스에 담고 있다.

| | 목표 A: fmkorea 수치 재현 | 목표 B: 의사결정에 쓸 수 있는 지표 |
|---|---|---|
| 보상 구조 | 블로거 로그에 커브핏 | out-of-sample 검증 |
| 성공 기준 | 오차 ±4p | IC 신뢰구간이 0을 안 걸침 |
| 리스크 | 블로거가 양식 바꾸면 무한 추격 | 표본 부족으로 결론 유보 |

**결정: 목표 B를 주(主)로, 목표 A를 부록으로 강등한다.**

- fmkorea는 ground truth가 아니라 CNN 비공개 공식의 또 다른 근사치다.
- 작성자가 리포트 양식을 거의 매일 바꾼다(RECONCILIATION §4에 기록됨) → 추격은 트레드밀.
- 앞으로의 유일한 판단 기준: **"이 지표는 내부적으로 일관되며, 미래수익률에 대한
  정보를 담고 있는가, 그 불확실성을 정직하게 표기했는가."**

아래 모든 Phase는 이 전제로 짜여 있다.

---

## Phase 0 — 데이터 스파인 확보 (병목, 최우선)

현재 모든 하류 문제(백분위 창이 히스토리보다 김, 백테스트 유의성 없음)의 뿌리는
**파생·신용·안전자산 series가 1.5~2년치뿐**이라는 것. 방법론을 건드리기 전에 해결한다.

### 작업

| # | 대상 | 내용 |
|---|---|---|
| 0-1 | `krx_api.py` (VKOSPI/풋콜) | `krx_market.update_market_cache` 식 일별 백필 루프 구현. KRX Open API 파생 엔드포인트가 주는 최과거일까지(최소 2020) 1회 대량 수집. `cache/vkospi.csv`·`putcall.csv`를 forward-only → backfill 가능하게 |
| 0-2 | `ecos_data.py` (Credit Spread) | `fetch_credit_spread`의 `num_days` 520 → 2500+. ECOS 817Y002의 BBB-·AA- 3년은 2000년대까지 존재. **BBB- series는 매트릭스 프라이싱(호가 기반·실거래 희박)이라 계단식** — 없앨 수 없는 한계이므로 문서화하고, A-등급을 대안 leg으로 병렬 계산해 민감도 확인 |
| 0-3 | `main.py` / `naver_data.py` (Safe Haven) | 어린 ETF(148070, 2025-01~) 대신 **10년 국고채 금리 series(ECOS, 장기)로 합성 채권수익률**: `bond_return ≈ −duration·Δyield + carry/252`, duration 상수 ≈ 8.5. ETF는 참고용으로만 |
| 0-4 | `krx_market.py` (Strength) | 6년(1560일) 백필 코드 이미 있음. non-NaN `strength_raw`가 ≥504일 되는지 확인, 부족하면 백필 길이 추가 확대 |

### 완료 기준

7개 지표 전부 최소 4년(1000거래일) 연속 히스토리 확보.
`DATA_INVENTORY.md` 산출: series별 (시작일 / 결측 구간 / 소스 / 갱신 방식 / 알려진 품질 한계).

---

## Phase 1 — 명백한 방법론 버그 수정 (fmkorea 무관, 무조건 옳음)

| # | 대상 | 변경 |
|---|---|---|
| 1-1 | `indicators.compute_breadth_real` | cumsum 백분위 폐기. **표준화된 McClellan Oscillator**(EMA19−EMA39를 자기 롤링 mean/std로 z-score → 0~100) 또는 주석대로 `summation − MA252(summation)`. 하나로 확정하고 **코드와 docstring을 같은 커밋에서** 일치 |
| 1-2 | `indicators.compute_strength_real` | `RECONCILIATION §4 옵션 B`의 선형계수 `2.30·raw+18.3` 완전 제거. 순수 5일 평활 + 252일 백분위. 52주 신고가는 종목별 252일 창이 다 찬 경우만 인정 |
| 1-3 | `dealer_positioning.with_greeks_at_spot` 외 | 결측 IV `fillna(median)` 폐기. **log-moneyness 축 선형보간**(또는 total-variance 축), 양끝은 마지막 관측 IV로 flat 연장. 보간 불가 행사가는 그릭스에서 제외 |
| 1-4 | `indicators._rolling_percentile_score` | `min_periods` 20 → `window // 2`(126). 그 전 구간 점수는 내되 `low_confidence=True` 플래그 → **백테스트에서 제외** |
| 1-5 | 전 지표 | doc/code **단일 진실원**: 7개 각각 "raw 정의 / 평활 / 정규화 / invert"를 코드에서 추출해 표로. 문서가 아니라 코드가 기준. 불일치는 전부 한 방향으로 수정하고 **어느 쪽을 택했는지 커밋 메시지에 명기** |

### 완료 기준

`grep`으로 docstring의 수치·수식과 실제 코드가 1:1 대응. 커브핏 상수 0개.

---

## Phase 2 — 복합지수 재구성

| # | 내용 |
|---|---|
| 2-1 | **TOTAL 강등.** 헤드라인을 추세지수 / 투심지수 2개로. TOTAL은 "CNN 비교용" 각주. `report.py`·`outlook.py`의 "25 미만 매수" 류 서술 전부 제거 |
| 2-2 | **중복 신호 처리.** Momentum(close/MA125)과 Strength(252일 레인지 위치)는 상관 ~0.8+ → 사실상 동일 신호. **권장: Strength를 추세지수에서 빼고 시장내부지표(Breadth) 쪽으로 재분류** (신고가-신저가는 원래 NYSE High-Low Index 계열). 대안: 상관 기반 가중(equal-risk / 1-PC 제거), 또는 "추세지수 = 실질 1.5개 신호"라고 명시 |
| 2-3 | **가중 방식 정당화.** 등가중 유지하려면 "구성요소 상관 X 수준이라 등가중 합리적" 근거를 대거나 상관 조정. "중립적"이라고 암묵 전제 금지 |

### 완료 기준

리포트 최상단에 단일 숫자 없음. 두 서브인덱스 각각 옆에 "역행/순행" 성격 + 구성요소 상관행렬.

---

## Phase 3 — 정직한 검증 하니스 (프로젝트의 실질 가치)

현재 `backtest.py`를 폐기 수준으로 다시 쓴다.

| # | 내용 |
|---|---|
| 3-1 | **IC에 신뢰구간.** stationary bootstrap(Politis-Romano, 기대 블록길이 ≈ 예측시계 60일, 5000회) → IC의 5/95 백분위. 또는 최소한 rank correlation에 Newey-West(lag=horizon) 조정 t-stat. **점추정 금지**: "IC −0.30" 대신 "IC −0.30 [90% CI −0.55, +0.05] → 노이즈와 구별 불가" |
| 3-2 | **구성 일관 서브샘플.** 7개 지표 전부 존재하는 구간에서만 IC. `n_days`가 아니라 **유효 독립 관측수(≈ n_days / horizon)** 병기 |
| 3-3 | **레짐 분해.** 최소 고변동성/저변동성 2분할. "표본이 대부분 강세장이라 절대수익률 무의미, 상대순서만"을 결과 표 안에 반복 명시 |
| 3-4 | **튜닝 파라미터 워크포워드.** 백분위 창(252)·EMA span(19/39)·평활일수 중 값을 "고른" 게 있으면 확장 윈도우 워크포워드로 안정성 확인. 안 버티면 **문헌 표준값으로 하드코딩하고 튜닝 종료**(252=1년, 19/39=McClellan 원본) |
| 3-5 | **2×2 수익률 표 폐기.** 표본 8개를 4칸에 나눈 건 복구 불가. 대체 → KFGI vs 선행수익률 산점도 + LOESS + 3-1의 IC CI |
| 3-6 | **거래규칙 검증.** 실제로 규칙을 제안할 때만 거래비용 포함 테스트. 아니면 "검증된 매매 규칙 없음"이라고 명시하고 넘어감 |

### 완료 기준

`VALIDATION.md` 산출: 지표별·그룹별 IC와 CI, 유효 관측수, 레짐별 분해.
데이터 축적 시(분기 1회) 갱신 절차 포함.

---

## Phase 4 — 옵션: 범위를 정직하게 축소 (Phase 0~3와 독립, 아무 때나)

| # | 내용 |
|---|---|
| 4-1 | **딜러 부호 — 인과 서사 제거.** KB증권 데이터가 금융투자 콜·풋 양매수를 시사 → US식 "딜러가 눌림목을 산다" 서사 삭제. Zero Gamma / Call Wall / Put Wall을 **"미결제약정 집중 레벨"**로 재정의(위치는 전역 부호 반전에 불변). `build_scenarios()`의 "딜러 헤지 매수가 상승 증폭", "Long→Short Gamma 전환" → "OI 집중 구간", "감마 부호 전환 후보 레벨"로 중립화. 헤드라인 Net GEX/DEX/Vanna/Charm에 **"부호 규약: US 표준(KRX 미검증), KB 데이터는 반대 시사" 배너** 고정 |
| 4-2 | **Zero Gamma 오차 밴드.** r/q·그리드 해상도·고정 IV에서 오는 모델오차를 ±로 표기. r·q·IV를 흔들어 재계산한 스프레드로 밴드 산출. **0.1 단위 단일 점 표기 금지** |
| 4-3 | **MaxPain 민감도.** ±20/30/40% 컷오프 세 값 나란히 표시. 비표준 windowed 버전임을 명시, 리포트 내 비중 최하 |
| 4-4 | **위험중립 확률 재라벨.** PoT·시나리오 확률을 코드·리포트·AI 프롬프트 전부에서 "위험중립(옵션시장 내재) 확률"로. `ai_commentary.py` 시스템 프롬프트의 "사실로 인용" 지시 → "위험중립 확률이며 실제 확률과 리스크 프리미엄만큼 다름을 명시하라"로 교체 |

### 완료 기준

옵션 리포트에서 방향성 단정 문장 0개. 모든 레벨에 오차/민감도 표기.

---

## Phase 5 — fmkorea 대조 → 부록

- `fmkorea_log.py`는 수동 수집기로 유지. **옛 이미지 글 OCR/vision 파싱은 하지 말 것**
  (잘못된 목표에 배팅 증가).
- 비교 표 하나, 상단에 **"참고용 근사치, 검증 기준 아님"** 명시.
- **fmkorea 격차를 줄이려는 어떤 파라미터 조정도 금지.** 격차는 문서화하되 좁히지 않는다.

---

## 실행 순서 & 공수 (대략)

```
Phase 0 ██████████        (병목, 먼저,        ~2일) ──┐
Phase 1     ████████████   (0과 일부 병렬,     ~3일) ─┤
Phase 2               ████ (1 이후,            ~1일) ─┤
Phase 3                   ████████████████ (핵심 지적작업, ~4일)
Phase 4  ████████         (독립, 아무 때나,    ~2일)
Phase 5                              ██       (~0.5일)
```

- **Phase 0가 나머지 전부를 게이트**한다.
- Phase 3가 지적으로 가장 중요하고 오래 걸린다.
- Phase 4는 완전 독립 — Phase 0 대기 중에 진행 가능.

---

## 하지 말 것 (명시)

1. 기존 7개 지표 검증(Phase 3) 전에 **새 지표 추가 금지**.
2. 백분위 창·EMA span을 **fmkorea에 맞춰 튜닝 금지**.
3. fmkorea 옛 이미지 글 **OCR로 캘리브레이션 점 확보 금지**.
4. KOSPI200 정확한 구성종목 리스트 구축 — **Phase 3에서 유니버스가 실제로 IC를 바꾼다고
   확인되기 전엔 금지** (이미 top200이 더 나빴다는 실측 있음, RECONCILIATION §4 옵션 A).
5. 옵션 딜러 부호 override를 다시 켜서 튜닝 — **Phase 4 배너로 처리**.

---

## 기대치 조정

이 계획을 다 끝내도, **Phase 3에서 서브인덱스 IC의 90% CI가 0을 안 걸치는 결과가 나올
확률은 반반**이다 — 표본이 짧고 한 레짐에 치우쳐 있기 때문. 그 경우 정직한 결론은:

> "일별 시장 맥락 readout·학습 도구로는 유효하나, 포지션 사이징 근거로는 부족.
> 데이터 축적 후 재검증."

이 결론을 받아들일 수 있어야 이 계획이 의미가 있다. fmkorea 47.4에 맞추는 건
이 질문에 아무 답도 주지 않는다.
