"""KFGI(한국형 공포탐욕지수) 세부 7개 지표 계산.

CNN Fear & Greed Index(Momentum/Strength/Breadth/Put-Call/Volatility/Safe Haven/
Junk Bond Demand, 7개 동일가중)의 한국판. 각 지표의 raw 정의는 CNN + fmkorea
05-13/05-20 원본 글 + 업계 표준(StockCharts McClellan 등)에 맞췄다 (RECONCILIATION.md §5).

점수화(0~100)는 **자기 과거 분포에서의 롤링 백분위**를 쓴다. CNN은 "평균 대비 편차 /
통상 편차"(z-score류)라고 하지만, 시장 데이터는 팻테일이고 레짐이 바뀌어 z-score가
추세 중 ±3에 고착되기 쉽다 — 백분위가 더 강건하고 트레이더에게도 "지난 N년 중 몇 %
수준"으로 바로 읽힌다(퀀트 컨센서스). 점수가 높을수록 탐욕, 낮을수록 공포.
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


def _rolling_percentile_score(series: pd.Series, invert: bool = False, window: int = WINDOW) -> pd.Series:
    """각 시점 값이 직전 `window` 거래일 구간에서 몇 백분위인지 (0~100)."""

    def pct_rank(w: np.ndarray) -> float:
        last = w[-1]
        return (w < last).sum() / (len(w) - 1) * 100 if len(w) > 1 else 50.0

    score = series.rolling(window, min_periods=20).apply(pct_rank, raw=True)
    if invert:
        score = 100 - score
    return score


def _zscore_score(series: pd.Series, window: int, invert: bool = False, z_span: float = 2.5) -> pd.Series:
    """CNN Fear&Greed 방식: '최근 평균 대비 편차 / 통상적 편차'(롤링 z-score)를 0~100으로.
    z = ±z_span 이 0/100 에 대응 (z_span=2.5 → 약 ±2.5σ 클립). invert면 부호 반전."""
    mu = series.rolling(window, min_periods=max(20, window // 3)).mean()
    sd = series.rolling(window, min_periods=max(20, window // 3)).std()
    z = (series - mu) / sd
    if invert:
        z = -z
    return (50 + 50 * z / z_span).clip(0, 100)


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


# Breadth = ratio-adjusted McClellan Volume Summation Index (StockCharts 표준; CNN "Stock
# Price Breadth"; fmkorea "상승/하락 거래량의 19,39 지수이동평균"). 절차:
#   osc = EMA19(breadth_raw) − EMA39(breadth_raw)      (McClellan Oscillator)
#   summation = cumsum(osc)                            (McClellan Summation Index)
#   deviation = summation − MA252(summation)           (CNN "자기 평균 대비 편차", anchor-free)
#   score = clip(a·deviation + b, 0, 100)
# a·b 는 fmkorea 로그 33점 회귀 (풀샘플 corr 0.86, train/test 분할 test MAE 1.7). 잠정.
BREADTH_EMA_FAST, BREADTH_EMA_SLOW = 19, 39


def compute_breadth_real(bs_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """ratio-adjusted McClellan Volume Summation Index → PCT_WINDOW 롤링 백분위.
    요약지수가 자기 과거 대비 높을수록(상승거래량 누적 우위) 탐욕. summation 은
    cumsum이라 절대수준이 캐시 시작일에 의존하지만, 백분위(증가함수)는 offset 불변."""
    if bs_raw is None or bs_raw.empty or bs_raw["breadth_raw"].isna().all():
        return None
    df = bs_raw.rename(columns={"breadth_raw": "raw"}).copy().sort_values("date")
    r = df["raw"]
    osc = r.ewm(span=BREADTH_EMA_FAST).mean() - r.ewm(span=BREADTH_EMA_SLOW).mean()
    summation = osc.cumsum()
    df["score"] = _rolling_percentile_score(summation, window=PCT_WINDOW)
    return df[["date", "raw", "score"]]


# fmkorea "시장 강도" 재현 계수 (RECONCILIATION.md §4 옵션 B).
# fmkorea는 (52주 신고가-신저가)/종목수를 ~10일 평활한 뒤 고정 선형으로 0~100 매핑한다
# (롤링 백분위 아님 — 검증에서 확인). fmkorea 로그 32점(2026-07~08)에 회귀:
#   score ≈ 2.30 * raw_smoothed(×100 스케일) + 18.3   (풀샘플 적합 R²≈0.90)
# 32점·7주뿐이라 계수는 잠정. cache/fmkorea_log.csv 가 쌓이면 재적합할 것.
STRENGTH_SMOOTH_DAYS = 5  # 신고가-신저가 카운트는 원계열이 톱니라 소폭 평활이 표준


def compute_strength_real(bs_raw: pd.DataFrame | None) -> pd.DataFrame | None:
    """(52주 신고가 종목수 − 신저가 종목수) / 종목수 를 5일 평활 후 PCT_WINDOW 롤링
    백분위. 신고가 우위가 자기 과거 대비 강할수록 탐욕. 유니버스: krx_market 이 시총
    상위 ~200(KOSPI200 근사)으로 잡음, mktcap 없으면 전체 KOSPI."""
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


# 백테스트(backtest.py)에서 확인: KOSPI 2020~2026 구간에서 CNN 7개 지표는 예측 방향이
# 두 갈래로 갈린다. 파생·신용 3개(Volatility/Put-Call/Credit Spread)는 역행(공포↑ → 이후
# 수익률↑, +60일 IC ≈ -0.3), 가격·저변 3개(Momentum/Strength/Breadth)는 순행(+60일 IC ≈
# +0.39). 등가중 합성은 두 신호가 상쇄돼 순(추세) 쪽으로 약하게 기운다. 트레이더용으로는
# 이 둘을 나눠 보는 게 유용하다 — 학술 문헌(투자심리=중기 역행 예측자)과도 부합.
SENTIMENT_INDICATORS = {"Volatility", "Put/Call Ratio", "Credit Spread"}
TREND_INDICATORS = {"Momentum", "Strength", "Breadth"}


def subindices(results: list[IndicatorResult]) -> tuple[float | None, float | None]:
    """(심리지수, 추세지수). 심리=파생·신용(낮을수록 매수 유리, 역행), 추세=가격·저변."""
    def _mean(names: set[str]) -> float | None:
        s = [r.score for r in results if r.name in names and r.score is not None]
        return float(np.mean(s)) if s else None
    return _mean(SENTIMENT_INDICATORS), _mean(TREND_INDICATORS)
