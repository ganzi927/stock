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
# 정규화 창: fmkorea가 본인 글에 "252일 (1년) 데이터"라고 명시했고, CNN도 대략 1년
# 기준이다. 504일(2년)로 넓혀봤더니 Momentum 등이 오히려 fmkorea와 크게 벌어졌다.
PCT_WINDOW = 252


@dataclass
class IndicatorResult:
    name: str
    raw: float | None
    score: float | None  # 0~100, None이면 데이터 없음(N/A)
    is_proxy: bool
    note: str


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
        last = w[-1]
        return (w < last).sum() / (len(w) - 1) * 100 if len(w) > 1 else 50.0

    score = series.rolling(window, min_periods=_min_periods(window)).apply(pct_rank, raw=True)
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
    (52주 스토캐스틱 %K 개념) 위치가 높을수록 탐욕."""
    df = kospi200.copy()
    roll_max = df["close"].rolling(WINDOW, min_periods=20).max()
    roll_min = df["close"].rolling(WINDOW, min_periods=20).min()
    df["raw"] = (df["close"] - roll_min) / (roll_max - roll_min) * 100
    df["score"] = df["raw"].clip(0, 100)
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


# Breadth = ratio-adjusted McClellan Oscillator (StockCharts 표준; CNN "Stock Price
# Breadth"; fmkorea "상승/하락 거래량의 19,39 지수이동평균"). 절차:
#   raw = (상승거래량 − 하락거래량) / (상승거래량 + 하락거래량)   ∈ [-1, 1]  (krx_market)
#   osc = EMA19(raw) − EMA39(raw)                                  (McClellan Oscillator)
#   score = osc 의 PCT_WINDOW 롤링 백분위
# WORKPLAN Phase 1-1: 예전엔 osc 를 cumsum(McClellan Summation Index)한 뒤 백분위를 씌웠는데,
# Summation Index는 비정상(누적)이라 캐시 시작일·국면에 따라 분포가 표류하고 롤링 백분위가
# 양극단에 달라붙었다. Oscillator 자체는 [-1,1] 유계 비율의 EMA 차라 준정상(準定常)이라
# 롤링 백분위가 안정적이다. fmkorea 로그 회귀 선형계수(a·b)는 제거했다.
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
VKOSPI_MA_DAYS = 50    # CNN: Volatility = VIX 대비 50일 이동평균


def compute_volatility_real(vkospi_df: pd.DataFrame | None) -> pd.DataFrame | None:
    """CNN 정본: "VIX의 50일 이동평균"을 계열로 삼아 PCT_WINDOW 롤링 백분위, invert.
    CNN 문구 그대로 — 평활한 변동성 수준이 자기 과거 대비 높으면 공포, 낮으면 탐욕.
    raw 컬럼은 표시용 당일 VKOSPI. (예전엔 당일 절대수준 백분위였음.)"""
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


CREDIT_SPREAD_WINDOW = 252  # fmkorea 로그 대비 MAE 최소 (378·504는 오히려 나빴음)


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
    last = df.dropna(subset=["score"]).iloc[-1]
    return IndicatorResult(name, float(last["raw"]), float(last["score"]), is_proxy, note)


def total_fgi(results: list[IndicatorResult]) -> float | None:
    scores = [r.score for r in results if r.score is not None]
    if not scores:
        return None
    return float(np.mean(scores))


# 백테스트(backtest.py)에서 확인: CNN 7개 지표는 예측 방향이 두 갈래로 갈린다.
# 파생·신용 3개(Volatility/Put-Call/Credit Spread)는 역행(공포↑ → 이후 수익률↑),
# 가격·저변 3개(Momentum/Strength/Breadth)는 순행. 등가중 단일 TOTAL은 두 신호가 상쇄돼
# 트레이딩 타이밍 툴로는 거의 무의미하다 — 그래서 WORKPLAN Phase 2-1: TOTAL은 "CNN
# 비교용" 참고값으로 강등하고, 리포트 헤드라인은 아래 두 서브인덱스로 낸다.
#
# WORKPLAN Phase 2-2 (중복 신호): Momentum(지수/MA125)과 Strength(252일 레인지 내 위치)는
# 사실상 같은 것을 잰다(과거 상관 ~0.8+). 추세지수는 "가격추세(Momentum) + 시장저변
# (Strength·Breadth)"이며 실질 독립 신호는 ~2개다. 이 한계는 리포트에 상관행렬로 병기한다
# (indicators.subscore_correlations / report). IC가 유니버스·구성에 민감하다고 Phase 3에서
# 확인되기 전엔 가중치를 더 손대지 않는다.
SENTIMENT_INDICATORS = {"Volatility", "Put/Call Ratio", "Credit Spread"}
TREND_INDICATORS = {"Momentum", "Strength", "Breadth"}
# 추세지수 내부 구분(표시용): 가격추세 vs 시장저변.
TREND_PRICE = {"Momentum"}
TREND_INTERNALS = {"Strength", "Breadth"}


def subindices(results: list[IndicatorResult]) -> tuple[float | None, float | None]:
    """(심리지수, 추세지수). 심리=파생·신용(낮을수록 매수 유리, 역행), 추세=가격·저변(순행).

    추세지수는 Momentum(가격)과 Strength·Breadth(저변)를 동일가중하면 Momentum의 거의-중복
    신호인 Strength 때문에 가격추세가 2/3 비중이 된다. 그래서 추세지수 =
    mean(Momentum, mean(Strength, Breadth)) 로 가격:저변 = 1:1 가중한다(가용한 것만)."""
    def _mean(names: set[str]) -> float | None:
        s = [r.score for r in results if r.name in names and r.score is not None]
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
