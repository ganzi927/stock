"""KFGI 탐색적 연관성 검증: Spearman IC와 시계열 블록 재표집.

거래일 축을 보존하고 horizon별 결측을 개별 처리한다. n/h는 블록 수 참고값이며
유효 표본수 추정치가 아니다. CI는 다중검정 미보정이며 전략 예측력의 입증이 아니다.
사용: python backtest.py [--start YYYY-MM-DD] [--no-md]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import indicators as ind
from ecos_data import fetch_credit_spread, synthetic_bond10y_index
from krx_market import compute_breadth_and_strength_raw
from main import _load_dotenv
from naver_data import fetch_index_history, update_cache

# 백테스트 표본을 위해 KOSPI200 지수 캐시를 2016년까지 딥백필(첫 실행만 느림, 이후 재사용).
INDEX_BACKFILL_DAYS = 2600

BASE_DIR = Path(__file__).parent
CACHE = BASE_DIR / "cache"
HORIZONS = [5, 10, 20, 40, 60, 120]
BOOT_HORIZONS = [20, 60, 120]
B = 1500
SEVEN = ["momentum", "volatility", "credit_spread", "strength", "breadth", "putcall", "safe_haven"]
SENTIMENT = ["volatility", "putcall", "credit_spread"]
TREND_PRICE = ["momentum"]
TREND_INTERNALS = ["strength", "breadth"]
# WORKPLAN2 C5: 실제 리포트가 출시하는 합성지표(Credit Spread 제외)도 나란히 측정한다.
# indicators.SENTIMENT_INDICATORS / total_fgi(MACRO_BACKDROP 제외)와 정확히 일치해야 한다.
SENTIMENT_PROD = ["volatility", "putcall"]
SIX = ["momentum", "volatility", "strength", "breadth", "putcall", "safe_haven"]


# ---------------------------------------------------------------- series build
def build_series() -> pd.DataFrame:
    k200 = update_cache(CACHE / "kospi200.csv", fetch_index_history, "KPI200", min_days=INDEX_BACKFILL_DAYS)
    bond = synthetic_bond10y_index()
    vk = pd.read_csv(CACHE / "vkospi.csv", parse_dates=["date"]) if (CACHE / "vkospi.csv").exists() else None
    pc = pd.read_csv(CACHE / "putcall.csv", parse_dates=["date"]) if (CACHE / "putcall.csv").exists() else None
    mk = pd.read_csv(CACHE / "market_kospi.csv", parse_dates=["date"], dtype={"ISU_CD": str})
    bs = compute_breadth_and_strength_raw(mk)
    cs = fetch_credit_spread(3000)

    subs = {
        "momentum": ind.compute_momentum(k200),
        "volatility": ind.compute_volatility_real(vk),
        "credit_spread": ind.compute_credit_spread(cs),
        "strength": ind.compute_strength_real(bs),
        "breadth": ind.compute_breadth_real(bs),
        "putcall": ind.compute_putcall_real(pc),
        "safe_haven": ind.compute_safe_haven(k200, bond) if bond is not None else None,
    }
    m = k200[["date", "close"]].rename(columns={"close": "kospi200"})
    for name, df in subs.items():
        if df is None or df.empty:
            m[name] = np.nan
            continue
        m = m.merge(df[["date", "score"]].rename(columns={"score": name}), on="date", how="left")

    if vk is not None:
        m = m.merge(vk.rename(columns={"vkospi": "vk_level"}), on="date", how="left")
    else:
        m["vk_level"] = np.nan

    m = m.sort_values("date").reset_index(drop=True)

    # 워밍업 트림: 각 score 의 첫 유효값으로부터 PCT_WINDOW 거래일 이내는 신뢰 불가 → NaN.
    w = ind.PCT_WINDOW
    for c in SEVEN:
        fv = m[c].first_valid_index()
        if fv is not None:
            m.loc[: fv + w - 1, c] = np.nan
    return m


def _group(m: pd.DataFrame, cols: list[str]) -> pd.Series:
    have = [c for c in cols if c in m.columns]
    return m[have].mean(axis=1, skipna=True) if have else pd.Series(np.nan, index=m.index)


def add_composites(m: pd.DataFrame) -> pd.DataFrame:
    m = m.copy()
    m["sentiment"] = _group(m, SENTIMENT)
    price = _group(m, TREND_PRICE)
    internals = _group(m, TREND_INTERNALS)
    m["trend"] = pd.concat([price, internals], axis=1).mean(axis=1, skipna=True)
    m["total7"] = m[SEVEN].mean(axis=1, skipna=True)
    m["n_ind"] = m[SEVEN].notna().sum(axis=1)
    # 출시 합성지표 (Credit Spread 제외) — 리포트 헤드라인과 동일한 정의
    m["sentiment_prod"] = _group(m, SENTIMENT_PROD)
    m["total6"] = m[SIX].mean(axis=1, skipna=True)
    return m


def fwd_returns(m: pd.DataFrame) -> pd.DataFrame:
    m = m.sort_values("date").reset_index(drop=True)
    lc = np.log(m["kospi200"])
    for h in HORIZONS:
        m[f"fwd{h}"] = lc.shift(-h) - lc
    return m


# ---------------------------------------------------------------- bootstrap IC
def _sb_index(n: int, L: float, rng: np.random.Generator) -> np.ndarray:
    idx = np.empty(n, dtype=np.int64)
    p = 1.0 / max(L, 1.0)
    cur = int(rng.integers(0, n))
    for i in range(n):
        idx[i] = cur
        if rng.random() < p:
            cur = int(rng.integers(0, n))
        else:
            cur = cur + 1 if cur + 1 < n else 0
    return idx


def boot_ic(x: pd.Series, y: pd.Series, horizon: int, b: int = B, seed: int = 7):
    if horizon <= 0 or b <= 0:
        raise ValueError("horizon and b must be positive")
    # 마스크를 유지한 원 거래일 축에서 블록을 뽑는다.
    d = pd.concat([x, y], axis=1).replace([np.inf, -np.inf], np.nan)
    valid = d.notna().all(axis=1)
    n = int(valid.sum())
    if n < 80:
        return None
    xv, yv = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    if np.unique(xv[valid]).size < 2 or np.unique(yv[valid]).size < 2:
        return None
    ic = float(spearmanr(xv[valid], yv[valid]).statistic)
    rng = np.random.default_rng(seed)
    L = max(horizon, 5)  # 기존 블록 길이 가정; 최적 길이라고 주장하지 않는다.
    boots = []
    for k in range(b):
        ii = _sb_index(len(d), L, rng)
        keep = np.isfinite(xv[ii]) & np.isfinite(yv[ii])
        xx, yy = xv[ii][keep], yv[ii][keep]
        if len(xx) < 2 or np.unique(xx).size < 2 or np.unique(yy).size < 2:
            continue
        value = float(spearmanr(xx, yy).statistic)
        if np.isfinite(value):
            boots.append(value)
    # 정의 불가 반복을 조용히 버리고 유의성을 주장하지 않는다.
    lo, hi = (np.percentile(boots, [5, 95]) if len(boots) == b else (np.nan, np.nan))
    crosses_zero = bool(lo <= 0 <= hi) if np.isfinite(lo) and np.isfinite(hi) else None
    return dict(ic=ic, lo=lo, hi=hi, n=n, n_blocks=n / horizon,
                bootstrap_valid=len(boots), bootstrap_requested=b, crosses_zero=crosses_zero)


# ---------------------------------------------------------------- report
def _fmt_ci(r: dict | None) -> str:
    if r is None:
        return "표본 부족"
    if r["crosses_zero"] is None:
        return f"IC {r['ic']:+.3f}; CI 산출 불가 (유효 재표집 {r['bootstrap_valid']}/{r['bootstrap_requested']}) n={r['n']}"
    tag = "  ← 0 포함" if r["crosses_zero"] else "  ← 0 미포함(탐색적·다중검정 미보정)"
    return f"IC {r['ic']:+.3f}  [90% CI {r['lo']:+.3f}, {r['hi']:+.3f}]  n={r['n']} n/h≈{r['n_blocks']:.0f}{tag}"


def run(start: str | None, write_md: bool) -> None:
    m = fwd_returns(add_composites(build_series()))
    if start:
        m = m[m["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    full = m.reset_index(drop=True)
    if full.empty:
        raise ValueError("검증할 시계열이 없습니다")

    lines: list[str] = []

    def P(s: str = "") -> None:
        print(s)
        lines.append(s)

    P(f"# KFGI 예측력 검증 (VALIDATION)")
    P()
    P(f"생성: `python backtest.py`{' --start ' + start if start else ''}  ·  부트스트랩 B={B} (stationary bootstrap)")
    P(f"구간: {full['date'].min().date()} ~ {full['date'].max().date()}  ({len(full)} 거래일)")
    P(f"평균 가용 지표 수: {full['n_ind'].mean():.1f} / 7")
    P()
    P("> IC는 Spearman. n/h는 비중첩 블록 수 참고값이며 유효 표본 크기 추정치가 아니다.")
    P("> 90% CI 가 0 을 포함하면 그 지표는 이 표본에서 **예측력이 있다고 말할 수 없다**.")
    P()

    # 1) 개별 7개 지표 — 여러 시계
    P("## 1. 개별 지표 IC + 90% 신뢰구간")
    P()
    for h in BOOT_HORIZONS:
        P(f"### +{h}일")
        P("```")
        for c in SEVEN:
            if full[c].notna().sum() < 120:
                P(f"  {c:14s} 표본 부족 ({full[c].notna().sum()})")
                continue
            P(f"  {c:14s} {_fmt_ci(boot_ic(full[c], full[f'fwd{h}'], h))}")
        P("```")
        P()

    # 2) 그룹 (투심 / 추세 / TOTAL) — 구성 일관 서브샘플
    P("## 2. 그룹 지수 IC — 전체 표본 vs 7개 모두 존재 구간")
    P()
    cc = full.where(full["n_ind"] == 7)  # 조건 밖 거래일을 삭제하지 않는다
    P(f"구성 일관(7/7) 구간: {int((full['n_ind'] == 7).sum())} 거래일"
      + (f" ({cc['date'].min().date()} ~ {cc['date'].max().date()})" if cc["date"].notna().any() else " — 없음"))
    P()
    for label, sub in [("전체 표본", full), ("7/7 구성 일관", cc)]:
        if len(sub) < 150:
            P(f"### {label}: 표본 부족 ({len(sub)})")
            P()
            continue
        P(f"### {label}")
        P("```")
        for gname, gcol in [("투심-출시 (Vol+P/C, Credit제외 — 리포트 헤드라인)", "sentiment_prod"),
                            ("투심 (Vol+P/C+Credit, 역행 기대)", "sentiment"),
                            ("추세 (Mom + [Str+Brd]/2, 순행 기대)", "trend"),
                            ("TOTAL6-출시 (Credit제외 — 리포트 참고값)", "total6"),
                            ("TOTAL7 (CNN 등가중)", "total7")]:
            for h in BOOT_HORIZONS:
                P(f"  {gname:34s} +{h:3d}일  {_fmt_ci(boot_ic(sub[gcol], sub[f'fwd{h}'], h))}")
        P("```")
        P()

    # 3) 변동성 레짐 분해 (+60일)
    P("## 3. 변동성 레짐 분해 (+60일 IC)")
    P()
    if full["vk_level"].notna().sum() > 200:
        med = full["vk_level"].median()
        P(f"VKOSPI 전체 기간 중앙값 {med:.1f} 기준 사후 고/저 분할(실시간 레짐 규칙 아님).")
        P("```")
        for gname, gcol in [("투심", "sentiment"), ("추세", "trend"), ("TOTAL7", "total7")]:
            hi = full.where(full["vk_level"] >= med)
            lo = full.where(full["vk_level"] < med)
            P(f"  {gname:8s} 고변동성  {_fmt_ci(boot_ic(hi[gcol], hi['fwd60'], 60))}")
            P(f"  {gname:8s} 저변동성  {_fmt_ci(boot_ic(lo[gcol], lo['fwd60'], 60))}")
        P("```")
    else:
        P("VKOSPI 레벨 데이터 부족 — 생략.")
    P()

    # 4) 분위 단조성 (2×2 대체)
    P("## 4. 분위 단조성 점검 (+60일) — 2×2 평균수익률 표는 표본 부족으로 폐기")
    P()
    P("```")
    for gcol, gname in [("sentiment", "투심"), ("trend", "추세"), ("total7", "TOTAL7")]:
        s = full[[gcol, "fwd60"]].dropna()
        if len(s) < 150:
            P(f"  {gname}: 표본 부족")
            continue
        try:
            q = pd.qcut(s[gcol], 5, labels=[1, 2, 3, 4, 5])
            means = s.groupby(q, observed=True)["fwd60"].mean() * 100
            rho = spearmanr(means.index.astype(int), means.values).statistic
            cells = " ".join(f"Q{i}:{means.get(i, np.nan):+.1f}%" for i in range(1, 6))
            P(f"  {gname:8s} {cells}   분위-수익률 단조성 ρ={rho:+.2f}")
        except ValueError:
            P(f"  {gname}: qcut 실패(동일값 과다)")
    P("```")
    P("> 분위 평균은 표본 내 기술통계이며, 실행 가능한 전략 수익률이나 표본외 예측력 검증이 아니다.")
    P()

    # 5) 결론
    P("## 5. 읽는 법 / 주의")
    P()
    P("- 90% CI는 탐색 결과다. 0 미포함만으로 다중검정 후 유의성·표본외 예측력을 입증하지 못한다.")
    P("- 전체 표본 합성값은 가용 지표 구성이 달라질 수 있다. 7/7 마스크 결과와 구분한다.")
    P("- stationary bootstrap은 의존성을 고려하지만 블록 길이와 정상성 가정에 민감하다.")
    P("- fwd는 당일 종가 기준 연관성 통계다. 종가 발표 후 동일 종가 체결을 가정한 전략 검증이 아니다.")
    P("- 전략 검증에는 사전 고정 규칙, 미사용 표본외 기간, 실제 데이터 공개시점 및 거래비용이 필요하다.")
    P("- 특정 지표에 대한 결론을 코드에 고정하지 않는다. 위 실행 결과와 데이터 품질을 함께 검토한다.")
    P()

    if write_md:
        (BASE_DIR / "VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n→ VALIDATION.md 갱신 ({len(lines)} 줄)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--no-md", action="store_true", help="VALIDATION.md 를 쓰지 않음")
    args = ap.parse_args()
    _load_dotenv(BASE_DIR / ".env")
    run(args.start, write_md=not args.no_md)
