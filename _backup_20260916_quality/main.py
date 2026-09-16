"""매일 실행: 데이터 갱신 -> KFGI 계산 -> HTML 리포트 생성 (단독 실행용).

사용법:
    python main.py            # 오늘자 KFGI 단독 리포트 생성 (reports/YYYY-MM-DD.html)

combined_main.py에서 generate_fgi_section()을 가져다 옵션 리포트와 한 파일로 합친다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

import indicators as ind
from ai_commentary import build_kfgi_prompt, generate_commentary
from ecos_data import fetch_credit_spread, synthetic_bond10y_index
from krx_api import fetch_kospi200_option_putcall_one_day, fetch_vkospi_one_day, update_krx_cache
from krx_market import compute_breadth_and_strength_raw, update_market_cache
from naver_data import fetch_index_history, fetch_item_history, update_cache
from report import build_fgi_section, build_page_shell

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
REPORTS_DIR = BASE_DIR / "reports"

BOND_ETF_CODE = "148070"  # KOSEF 국고채10년 ETF — 참고용 cross-check로만 캐시(2025-01~로 짧음).
                          # Safe Haven 지표의 실제 채권 레그는 synthetic_bond10y_index()
                          # (국고채 10년 금리 → 합성 총수익 지수, 2016+). WORKPLAN Phase 0-3.


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    import os

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _truncate_asof(df: "pd.DataFrame | None", as_of: "date | None") -> "pd.DataFrame | None":
    """as_of가 주어지면 df를 date <= as_of 로 자른다(트레일링 컷이라 look-ahead 없음).
    combined_main이 과거 거래일 기준으로 리포트를 재생성할 때, 캐시에 그 이후 데이터가
    이미 들어와 있어도 지표가 '그 날 마감 시점'만 보도록 한다."""
    if as_of is None or df is None or getattr(df, "empty", True) or "date" not in df.columns:
        return df
    return df[pd.to_datetime(df["date"]).dt.date <= as_of].reset_index(drop=True)


def generate_fgi_section(as_of: "date | None" = None) -> tuple[str, float, float, float | None, dict | None, "date | None"]:
    """KFGI 계산 + 섹션 HTML 생성. 반환: (section_html, kospi_close, kospi200_close, total_score, fgi_facts, fgi_as_of).

    as_of를 주면 모든 지표 시계열을 그 거래일까지로 잘라 '그 날 마감 기준' KFGI를 낸다
    (기본 None = 캐시 최신). fgi_as_of는 실제로 사용된 마지막 거래일."""
    # WORKPLAN Phase 0: PCT_WINDOW=252 백분위가 꽉 찬 기준을 갖도록 시세 캐시도 넉넉히
    # 확보(≥ 2·252 + 여유). 파생·신용·채권 시계열은 별도 딥 백필 파일에서 읽는다.
    HIST_DAYS = 900
    kospi = update_cache(CACHE_DIR / "kospi.csv", fetch_index_history, "KOSPI", min_days=HIST_DAYS)
    kospi200 = update_cache(CACHE_DIR / "kospi200.csv", fetch_index_history, "KPI200", min_days=HIST_DAYS)
    update_cache(CACHE_DIR / "bond10y.csv", fetch_item_history, BOND_ETF_CODE, min_days=HIST_DAYS)  # 참고용 cross-check

    vkospi_raw = update_krx_cache(CACHE_DIR / "vkospi.csv", fetch_vkospi_one_day, "vkospi", min_days=HIST_DAYS)
    putcall_raw = update_krx_cache(CACHE_DIR / "putcall.csv", fetch_kospi200_option_putcall_one_day, "putcall", min_days=HIST_DAYS)

    market_df = update_market_cache(CACHE_DIR / "market_kospi.csv")
    bs_raw = compute_breadth_and_strength_raw(market_df)

    bond10y = synthetic_bond10y_index()  # 국고채 10년 금리 → 합성 총수익 지수 (2016+)
    if bond10y is None:  # ECOS 키 없음 → 짧은 ETF 캐시로 폴백
        bond10y = update_cache(CACHE_DIR / "bond10y.csv", fetch_item_history, BOND_ETF_CODE, min_days=HIST_DAYS)

    momentum_df = ind.compute_momentum(kospi200)
    safe_haven_df = ind.compute_safe_haven(kospi200, bond10y)
    credit_spread_df = ind.compute_credit_spread(fetch_credit_spread())

    volatility_df = ind.compute_volatility_real(vkospi_raw)
    volatility_is_proxy = volatility_df is None
    if volatility_is_proxy:
        volatility_df = ind.compute_volatility_proxy(kospi200)

    strength_df = ind.compute_strength_real(bs_raw)
    strength_is_proxy = strength_df is None
    if strength_is_proxy:
        strength_df = ind.compute_strength(kospi200)

    breadth_df = ind.compute_breadth_real(bs_raw)
    breadth_is_proxy = breadth_df is None
    if breadth_is_proxy:
        breadth_df = ind.compute_breadth_proxy(kospi200)

    putcall_df = ind.compute_putcall_real(putcall_raw)

    # 과거 거래일 기준 재생성: 모든 지표 계열을 as_of 이하로 자른다(컷은 계산 이후라 롤링
    # 통계는 as_of 시점의 트레일링 창을 정확히 쓴다 — look-ahead 없음).
    if as_of is not None:
        kospi = _truncate_asof(kospi, as_of)
        kospi200 = _truncate_asof(kospi200, as_of)
        momentum_df = _truncate_asof(momentum_df, as_of)
        volatility_df = _truncate_asof(volatility_df, as_of)
        strength_df = _truncate_asof(strength_df, as_of)
        breadth_df = _truncate_asof(breadth_df, as_of)
        safe_haven_df = _truncate_asof(safe_haven_df, as_of)
        credit_spread_df = _truncate_asof(credit_spread_df, as_of)
        putcall_df = _truncate_asof(putcall_df, as_of)

    results = [
        ind.latest_result(momentum_df, "Momentum", False, "KOSPI200 종가 / 125일 이동평균"),
        ind.latest_result(
            volatility_df,
            "Volatility",
            volatility_is_proxy,
            "VKOSPI 대체: 20일 실현변동성(연율화)" if volatility_is_proxy else "VKOSPI (raw=당일값 / score=20일MA의 백분위·invert; CNN 50일에서 단축, KRX Open API)",
        ),
        ind.latest_result(credit_spread_df, "Credit Spread", False, "회사채 BBB-(3Y) − 회사채 AA-(3Y) — 합성(TOTAL·투심)에서 제외한 매크로 신용 배경 (ECOS_API_KEY 필요)"),
        ind.latest_result(
            strength_df,
            "Strength",
            strength_is_proxy,
            "신고가/신저가 비율 대체: 252일 고저 구간 내 위치" if strength_is_proxy else "코스피200(시총 상위 200) 52주 신고가-신저가 종목수 비중 (KRX Open API)",
        ),
        ind.latest_result(
            breadth_df,
            "Breadth",
            breadth_is_proxy,
            "breadth 대체(지수 방향×거래량 20일 합 — 횡단면 등락폭 아님)" if breadth_is_proxy else "코스피200(시총 상위 200) 상승/하락 거래량 McClellan Volume Oscillator (CNN은 Summation Index; KRX Open API)",
        ),
        ind.latest_result(putcall_df, "Put/Call Ratio", False, "코스피200 지수옵션 거래량 PUT/CALL 5일MA·invert (CNN은 개별주 P/C — 한국엔 없어 지수옵션으로 대체, 기관 헤지 지배로 신호 약함; KRX Open API)"),
        ind.latest_result(safe_haven_df, "Safe Haven Demand", False, "KOSPI200 20일 수익률 − 국고채10년 ETF 20일 수익률"),
    ]

    total_score = ind.total_fgi(results)

    # 최근 60거래일 TOTAL 추이 (일자별로 각 지표 score를 합쳐 평균)
    merged = momentum_df[["date", "score"]].rename(columns={"score": "momentum"})
    optional_series = {
        "volatility": volatility_df,
        "strength": strength_df,
        "breadth": breadth_df,
        "safe_haven": safe_haven_df,
        "credit_spread": credit_spread_df,
        "putcall": putcall_df,
    }
    for name, df in optional_series.items():
        if df is not None:
            merged = pd.merge(merged, df[["date", "score"]].rename(columns={"score": name}), on="date", how="left")
    # TOTAL 추이도 indicators.total_fgi 와 동일하게 Credit Spread(매크로 배경) 제외.
    score_cols = [c for c in merged.columns if c not in ("date", "credit_spread")]
    merged["total"] = merged[score_cols].mean(axis=1, skipna=True)
    trend = merged.dropna(subset=["total"]).tail(60)

    # WORKPLAN Phase 2-3: 지표 score 상관행렬 (등가중의 전제 점검용)
    _disp = {"momentum": "Momentum", "volatility": "Volatility", "strength": "Strength",
             "breadth": "Breadth", "safe_haven": "Safe Haven Demand",
             "credit_spread": "Credit Spread", "putcall": "Put/Call Ratio"}
    corr = ind.subscore_correlations(merged.rename(columns=_disp), list(_disp.values()))

    detail_dfs = {
        "Momentum": momentum_df.tail(ind.WINDOW),
        "Volatility" + (" (proxy)" if volatility_is_proxy else ""): volatility_df.tail(ind.WINDOW),
        "Strength" + (" (proxy)" if strength_is_proxy else ""): strength_df.tail(ind.WINDOW),
        "Breadth" + (" (proxy)" if breadth_is_proxy else ""): breadth_df.tail(ind.WINDOW),
        "Safe Haven Demand": safe_haven_df.tail(ind.WINDOW),
    }
    if credit_spread_df is not None:
        detail_dfs["Credit Spread"] = credit_spread_df.tail(ind.WINDOW)
    if putcall_df is not None:
        detail_dfs["Put/Call Ratio"] = putcall_df.tail(ind.WINDOW)

    sentiment_score, trend_score = ind.subindices(results)
    fgi_facts = {
        "total": total_score,
        "sentiment": sentiment_score,
        "trend": trend_score,
        "indicators": {r.name: r.score for r in results if r.score is not None},
    } if total_score is not None else None

    commentary = generate_commentary(build_kfgi_prompt(total_score, results, sentiment_score, trend_score))

    section_html = build_fgi_section(
        total_score=total_score,
        results=results,
        total_trend_dates=trend["date"],
        total_trend_scores=trend["total"],
        detail_dfs=detail_dfs,
        commentary=commentary,
        sentiment_score=sentiment_score,
        trend_score=trend_score,
        corr=corr,
    )

    fgi_as_of = None
    if not kospi200.empty:
        fgi_as_of = pd.Timestamp(kospi200["date"].iloc[-1]).date()

    return section_html, float(kospi["close"].iloc[-1]), float(kospi200["close"].iloc[-1]), total_score, fgi_facts, fgi_as_of


def main() -> None:
    _load_dotenv(BASE_DIR / ".env")
    section_html, kospi_close, kospi200_close, total_score, _, _ = generate_fgi_section()

    today = date.today()
    html = build_page_shell(today, kospi_close, kospi200_close, extra_style="", tabs=[("fgi", "공포탐욕지수", section_html)])

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"{today.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"리포트 생성 완료: {out_path}")
    if total_score is not None:
        print(f"TOTAL KFGI: {total_score:.1f}")


if __name__ == "__main__":
    main()
