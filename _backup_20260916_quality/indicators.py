"""KFGI(한국형 공포탐욕지수) 세부 7개 지표 계산.

CNN Fear & Greed Index(Momentum/Strength/Breadth/Put-Call/Volatility/Safe Haven/
Junk Bond Demand, 7개 동일가중)의 한국판. 각 지표의 raw 정의는 CNN + fmkorea
05-13/05-20 원본 글 + 업계 표준(StockCharts McClellan 등)에 맞췄다 (RECONCILIATION.md §5).

점수화(0~100)는 **자기 과거 분포에서의 롤링 백분위**로 전 지표 통일한다. CNN은 "평균
대비 편차 / 통상 편차"(z-score류)라고 하지만, 시장 데이터는 팻테일이고 레짐이 바뀌어
z-score가 추세 중 ±3에 고착되기 쉽다 — 백분위가 더 강건하고 트레이더에게도 "지난 N년
중 몇 % 수준"으로 바로 읽힌다(퀀트 컨센서스). 점수가 높을수록 탐욕, 낮을수록 공포.

WORKPLAN.md Phase 1: fmkorea 로그에 회귀한 선형계수는 전부 제거했다(있던 적도 없지만
문서에 흔적이 남아 있었다). raw 입력만 CNN/fmkorea 정의에 맞추고, raw→score 변환은
표준 롤링 백분위 하나뿐이다. 커브핏 상수 0개. 각 함수의 docstring이 코드와 1:1 대응한다
(불일치 시 코드가 기준).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WINDOW = 252            # 하위호환 (options_main IV Rank 등)
# 정규화 창 = 252거래일(약 1년). CNN Fear&Greed의 "최근 1년 대비" 관행 및 롤링
# 백분위의 표준 lookback. IC 스윕이나 fmkorea 근접도로 고른 값이 아니다.
PCT_WINDOW = 252


@dataclass
class IndicatorResult:
    name: str
    raw: float | None
    score: float | None  # 0~100, None이면 데이터 없음(N/A)
    is_proxy: bool
    note: str
    low_confidence: bool = False  # 점수화 히스토리가 1년 미만 → 백분위 기준이 얇음 (합성 제외)
    scored_since: str | None = None  # 이 지표가 점수화되기 시작한 날짜(YYYY-MM-DD)
    score_ci: float | None = None  # 백분위 표본오차 95% 반폭(점). 유한 창(n)에서 오는 불확실성


# 롤링 창이 이만큼 차기 전에는 백분위 점수를 내지 않는다(N/A). 예전엔 20이었는데,
# 20개 표본에 대한 순위는 노이즈가 커서 시점 간 비교가 안 됐다 (WORKPLAN Phase 1-4).
MIN_PERIODS_FRAC = 0.5
MIN_PERIODS_FLOOR = 60


def _min_periods(window: int) -> int:
    return max(MIN_PERIODS_FLOOR, int(window * MIN_PERIODS_FRAC))


def _rolling_percentile_score(series: pd.Series, invert: bool = False, window: int = WINDOW) -> pd.Series:
    """각 시점 값이 직전 `window` 거래일 구간에서 몇 백분위인지 (0~100).
    창이 `_min_periods(window)` 만큼 차기 전 구간은 NaN (신뢰할 수 없는 초기값 배제)."""

    def pct_rank(w: np.ndarray) -> float:
        if not np.isfinite(w[-1]):
            return np.nan
        w = w[np.isfinite(w)]
        n = len(w)
        if n <= 1:
            return 50.0
        last = w[-1]
        # midrank: 동점(계단함수 Credit 등)에서 극단에 달라붙지 않도록 절반씩 나눈다.
        below = np.sum(w < last)
        equal_excl_self = np.sum(w == last) - 1
        return (below + 0.5 * equal_excl_self) / (n - 1) * 100

    score = series.replace([np.inf, -np.inf], np.nan).rolling(window, min_periods=_min_periods(window)).apply(pct_rank, raw=True)
    if invert:
        score = 100 - score
    return score


def compute_momentum(kospi200: pd.DataFrame) -> pd.DataFrame:
    """CNN "Stock Price Momentum": 지수 / 125일 이동평균 이격도 → PCT_WINDOW 롤링 백분위."""
    df = kospi200.copy()
    df["ma125"] = df["close"].rolling(125, min_periods=20).mean()
    df["raw"] = df["close"] / df["ma125"]
    df["score"] = _rolling_percentile_score(df["raw"], window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


def compute_volatility_proxy(kospi200: pd.DataFrame) -> pd.DataFrame:
    """VKOSPI(유료/등록 필요) 대신 20일 실현변동성(연율화)을 프록시로 사용.
    변동성이 높을수록 공포이므로 invert=True."""
    df = kospi200.copy()
    ret = df["close"].pct_change()
    df["raw"] = ret.rolling(20, min_periods=10).std() * np.sqrt(252) * 100
    df["score"] = _rolling_percentile_score(df["raw"], invert=True)
    return df[["date", "raw", "score"]]


def compute_strength(kospi200: pd.DataFrame) -> pd.DataFrame:
    """전종목 신고가/신저가 비율 대신, 지수 자체의 252일 고저 구간 내 위치(%)를 사용.
    (52주 스토캐스틱 %K 개념) 위치가 높을수록 탐욕.

    WORKPLAN2 C1: raw %K 를 그대로 score로 쓰던 것을 다른 지표와 동일하게 PCT_WINDOW
    롤링 백분위로 통일한다 — 상승장에서 %K가 계속 80~100에 붙어 '항상 극단 탐욕'으로
    나오던 편향 제거."""
    df = kospi200.copy()
    roll_max = df["close"].rolling(WINDOW, min_periods=20).max()
    roll_min = df["close"].rolling(WINDOW, min_periods=20).min()
    df["raw"] = (df["close"] - roll_min) / (roll_max - roll_min) * 100
    df["score"] = _rolling_percentile_score(df["raw"], window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


def compute_breadth_proxy(kospi200: pd.DataFrame) -> pd.DataFrame:
    """전종목 등락 거래대금차 대신, 지수 등락 방향에 거래량을 가중한
    누적합(단순 OBV류) 20일 변화분을 프록시로 사용."""
    df = kospi200.copy()
    ret_sign = np.sign(df["close"].diff())
    signed_vol = ret_sign * df["volume"]
    df["raw"] = signed_vol.rolling(20, min_periods=10).sum()
    df["score"] = _rolling_percentile_score(df["raw"])
    return df[["date", "raw", "score"]]


def compute_safe_haven(kospi200: pd.DataFrame, bond_etf: pd.DataFrame) -> pd.DataFrame:
    """CNN "Safe Haven Demand": 위험자산(KOSPI200) 20일 수익률 − 안전자산(국고채 10년물
    ETF) 20일 수익률 → PCT_WINDOW 롤링 백분위. 주식이 채권보다 잘 나갈수록 탐욕."""
    merged = pd.merge(kospi200[["date", "close"]], bond_etf[["date", "close"]], on="date", suffixes=("_eq", "_bond"))
    merged["ret_eq"] = merged["close_eq"].pct_change(20)
    merged["ret_bond"] = merged["close_bond"].pct_change(20)
    merged["raw"] = (merged["ret_eq"] - merged["ret_bond"]) * 100
    merged["score"] = _rolling_percentile_score(merged["raw"], window=PCT_WINDOW)
    return merged[["date", "raw", "score"]]


# Breadth = ratio-adjusted McClellan **Oscillator** (EMA19 − EMA39). 절차:
#   raw = (상승거래량 − 하락거래량) / (상승거래량 + 하락거래량)   ∈ [-1, 1]  (krx_market)
#   osc = EMA19(raw) − EMA39(raw)                                  (McClellan Oscillator)
#   score = osc 의 PCT_WINDOW 롤링 백분위
# ⚠️ CNN "Stock Price Breadth"는 이 Oscillator를 누적한 McClellan Summation Index를 쓴다.
# 여기선 Summation Index가 비정상(누적)이라 캐시 시작일·국면에 따라 분포가 표류하고 롤링
# 백분위가 양극단에 달라붙어서, 준정상인 Oscillator 자체를 백분위한다 — 의도적 이탈이며
# "CNN과 동일"이 아니다. 거래량 기반이라는 점은 CNN(volume breadth)과 같다.
BREADTH_EMA_FAST, BREADTH_EMA_SLOW = 19, 39


def compute_breadth_real(bs_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """McClellan Oscillator(EMA19 − EMA39 of ratio-adjusted net advancing volume) →
    PCT_WINDOW 롤링 백분위. Oscillator가 자기 과거 대비 높을수록(상승거래량 우위) 탐욕."""
    if bs_raw is None or bs_raw.empty or bs_raw["breadth_raw"].isna().all():
        return None
    df = bs_raw.rename(columns={"breadth_raw": "raw"}).copy().sort_values("date")
    r = df["raw"]
    osc = r.ewm(span=BREADTH_EMA_FAST, adjust=False).mean() - r.ewm(span=BREADTH_EMA_SLOW, adjust=False).mean()
    df["score"] = _rolling_percentile_score(osc, window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


# WORKPLAN Phase 1-2 / 1-5: 예전 문서(RECONCILIATION.md §4 "옵션 B")는 fmkorea 32점에
# 회귀한 고정 선형계수(score ≈ 2.30·raw + 18.3)를 "채택"이라 적어뒀지만, 실제 코드는
# 늘 롤링 백분위였다(계수는 정의된 적도 없음). 7주 32점 자기상관 표본에 대한 2모수 적합은
# out-of-sample 의미가 없어 완전히 폐기하고, docstring을 코드에 맞춘다.
STRENGTH_SMOOTH_DAYS = 5  # 신고가-신저가 카운트는 원계열이 톱니라 소폭 평활이 표준(NYSE HL Index 관행)


def compute_strength_real(bs_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """(52주 신고가 종목수 − 신저가 종목수) / 종목수 를 5일 평활한 뒤 PCT_WINDOW 롤링
    백분위. 신고가 우위가 자기 과거 대비 강할수록 탐욕.

    유니버스·52주 판정: krx_market.compute_breadth_and_strength_raw 담당 —
    STRENGTH_WINDOW=252, min_periods=252(진짜 52주 다 차야 인정), 창 미충족 종목-일자는
    집계 제외(가짜 0 아닌 NaN). STRENGTH_UNIVERSE_N=None이면 전체 KOSPI(CNN 정본),
    정수면 일자별 시총 상위 N(fmkorea "코스피200" 근사)."""
    if bs_raw is None or bs_raw.empty or bs_raw["strength_raw"].isna().all():
        return None
    df = bs_raw.rename(columns={"strength_raw": "raw"}).copy().sort_values("date")
    smoothed = df["raw"].rolling(STRENGTH_SMOOTH_DAYS, min_periods=1).mean()
    df["score"] = _rolling_percentile_score(smoothed, window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


PUTCALL_MA_DAYS = 5    # CNN: "CBOE 풋콜비의 5일 이동평균"
# CNN 원본은 VIX 대비 50일 이동평균. 이 프로젝트는 "코스피 대형주 전술 readout"이 목표라
# (WORKPLAN §0.1) 50일 평활은 스팟 변동성보다 2.5개월 뒤처져 일간 심리 읽기로는 둔하다.
# 20일(약 1개월, VIX 단기 추세의 흔한 창)로 단축 — **반응성 근거의 의도적 이탈이며
# 백테스트 IC로 고른 값이 아니다**(RECONCILIATION §5.4 재검토 결론). 창을 더 줄이면
# 하루 노이즈가 커져 20으로 절충.
VKOSPI_MA_DAYS = 20


def compute_volatility_real(vkospi_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Volatility = VKOSPI의 VKOSPI_MA_DAYS(20일) 이동평균을 계열로 PCT_WINDOW 롤링 백분위,
    invert. 평활한 변동성 수준이 자기 과거 대비 높으면 공포, 낮으면 탐욕. raw 컬럼은
    표시용 당일 VKOSPI. (CNN 원본은 50일 — 대형주 전술 목적상 반응성 위해 단축.)"""
    if vkospi_df is None or vkospi_df.empty:
        return None
    df = vkospi_df.rename(columns={"vkospi": "raw"}).copy().sort_values("date")
    ma = df["raw"].rolling(VKOSPI_MA_DAYS, min_periods=10).mean()
    df["score"] = _rolling_percentile_score(ma, invert=True, window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


def compute_putcall_real(putcall_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """코스피200 옵션 풋/콜 거래량비의 5일 이동평균(CNN 방식)을 PCT_WINDOW 롤링 백분위.
    풋 매수 우위(비율↑) = 공포이므로 invert."""
    if putcall_df is None or putcall_df.empty:
        return None
    df = putcall_df.rename(columns={"putcall": "raw"}).copy().sort_values("date")
    ma = df["raw"].rolling(PUTCALL_MA_DAYS, min_periods=1).mean()
    df["score"] = _rolling_percentile_score(ma, invert=True, window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


CREDIT_SPREAD_WINDOW = 252  # 다른 지표와 동일한 1년 롤링 백분위 창 (표준값, 튜닝 아님)


def compute_credit_spread(spread_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """정크(회사채 BBB-,3년) − 투자등급(회사채 AA-,3년) 수익률 스프레드 = CNN "Junk Bond
    Demand". 좁을수록(정크 수요↑ = 위험선호) 탐욕이므로 invert. 롤링 백분위."""
    if spread_df is None or spread_df.empty:
        return None
    df = spread_df.copy().sort_values("date")
    df["raw"] = df["spread"]
    df["score"] = _rolling_percentile_score(df["raw"], invert=True, window=CREDIT_SPREAD_WINDOW)
    return df[["date", "raw", "score"]]


def latest_result(df: pd.DataFrame | None, name: str, is_proxy: bool, note: str) -> IndicatorResult:
    if df is None or df.empty or df["score"].isna().all():
        return IndicatorResult(name, None, None, is_proxy, note + " (데이터 없음/기간 부족)")
    scored = df.dropna(subset=["score"])
    last = scored.iloc[-1]
    # WORKPLAN2 A3: 점수화 히스토리가 1년(PCT_WINDOW) 미만이면 백분위 기준 분포가 얇아
    # 시점 간·지표 간 비교가 불안정 → low_confidence (합성에서 제외, 카드엔 표기).
    n_scored = len(scored)
    since = None
    if "date" in scored.columns:
        try:
            since = str(pd.Timestamp(scored["date"].iloc[0]).date())
        except Exception:
            since = None
    # 평활·자기상관을 무시한 이항 표준오차는 검증된 점수 CI가 아니다.
    ci = None
    return IndicatorResult(
        name, float(last["raw"]), float(last["score"]), is_proxy, note,
        low_confidence=n_scored < PCT_WINDOW, scored_since=since, score_ci=ci,
    )


# 합성(TOTAL·투심·추세)에서 빼고 "매크로 배경" 지표로만 표시하는 것.
# Credit Spread(회사채 BBB- − AA-): (1) 한국 BBB- 회사채 시장이 2026년 사실상 얼어붙어
# (발행 급감·개인 소화·"돈맥경화") 호가가 매트릭스 프라이싱 지배 → 최근 252일 중 스프레드가
# 0.01 이상 움직인 날이 11일뿐인 계단함수, (2) 거시 위험선호 변수이지 코스피 대형주
# 세그먼트 심리 신호가 아님, (3) 백테스트 IC는 강하나 2020·2022 두 위기에 의존
# (VALIDATION.md). → 카드로는 계속 보여주되 TOTAL/투심/추세 산출에서는 제외한다
# (WORKPLAN §0.1 재검토, RECONCILIATION §5.4·웹 검증).
MACRO_BACKDROP = {"Credit Spread"}


def _composite_eligible(r: IndicatorResult) -> bool:
    return r.score is not None and r.name not in MACRO_BACKDROP and not r.low_confidence


def total_fgi(results: list[IndicatorResult]) -> float | None:
    scores = [r.score for r in results if _composite_eligible(r)]
    if not scores:
        return None
    return float(np.mean(scores))


# 백테스트(backtest.py)에서 확인: 지표는 예측 방향이 두 갈래로 갈린다.
# 파생 2개(Volatility/Put-Call)는 역행(공포↑ → 이후 수익률↑), 가격·저변 3개
# (Momentum/Strength/Breadth)는 순행. (Credit Spread도 역행 IC가 강했으나 2020·2022
# 두 위기 의존 + 매트릭스 프라이싱이라 MACRO_BACKDROP으로 분리.) 등가중 단일 TOTAL은
# 두 신호가 상쇄돼 트레이딩 타이밍 툴로는 거의 무의미하다 — WORKPLAN Phase 2-1: TOTAL은
# "CNN 비교용" 참고값으로 강등하고, 리포트 헤드라인은 아래 두 서브인덱스로 낸다.
#
# WORKPLAN Phase 2-2 (중복 신호): Momentum(지수/MA125)과 Strength(252일 레인지 내 위치)는
# 사실상 같은 것을 잰다(과거 상관 ~0.8+). 추세지수는 "가격추세(Momentum) + 시장저변
# (Strength·Breadth)"이며 실질 독립 신호는 ~2개다. 이 한계는 리포트에 상관행렬로 병기한다
# (indicators.subscore_correlations / report). IC가 유니버스·구성에 민감하다고 Phase 3에서
# 확인되기 전엔 가중치를 더 손대지 않는다.
# 투심 = 파생 역행 지표(변동성·풋콜). Credit Spread는 MACRO_BACKDROP으로 분리(위 참고).
SENTIMENT_INDICATORS = {"Volatility", "Put/Call Ratio"}
TREND_INDICATORS = {"Momentum", "Strength", "Breadth"}
# 추세지수 내부 구분(표시용): 가격추세 vs 시장저변.
TREND_PRICE = {"Momentum"}
TREND_INTERNALS = {"Strength", "Breadth"}


def subindices(results: list[IndicatorResult]) -> tuple[float | None, float | None]:
    """(심리지수, 추세지수). 심리=파생 역행(변동성·풋콜; 낮을수록 매수 유리), 추세=가격·저변(순행).

    추세지수는 Momentum(가격)과 Strength·Breadth(저변)를 동일가중하면 Momentum의 거의-중복
    신호인 Strength 때문에 가격추세가 2/3 비중이 된다. 그래서 추세지수 =
    mean(Momentum, mean(Strength, Breadth)) 로 가격:저변 = 1:1 가중한다(가용한 것만)."""
    def _mean(names: set[str]) -> float | None:
        s = [r.score for r in results if r.name in names and _composite_eligible(r)]
        return float(np.mean(s)) if s else None

    sentiment = _mean(SENTIMENT_INDICATORS)
    price, internals = _mean(TREND_PRICE), _mean(TREND_INTERNALS)
    parts = [x for x in (price, internals) if x is not None]
    trend = float(np.mean(parts)) if parts else None
    return sentiment, trend


def subscore_correlations(wide: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """지표 score 시계열들의 피어슨 상관행렬 (겹치는 구간, 최소 60일). 리포트 병기용 —
    등가중이 '중립적'이라는 암묵 전제를 검증 가능하게 드러낸다 (WORKPLAN Phase 2-3)."""
    cols = [c for c in names if c in wide.columns]
    sub = wide[cols].dropna()
    if len(sub) < 60:
        return pd.DataFrame()
    return sub.corr()
