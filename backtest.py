"""KFGI 예측력 검증 — 정직판 (WORKPLAN Phase 3).

무엇이 바뀌었나 (예전 backtest.py 대비):
- IC를 점추정이 아니라 **stationary bootstrap 90% 신뢰구간**으로 보고한다. CI가 0을
  걸치면 "노이즈와 구별 불가"라고 명시한다.
- 중첩(overlapping) 선행수익률이라 실제 정보량은 n_days 가 아니라 **n_eff ≈ n_days /
  horizon** 다 — 이걸 병기한다.
- 7개 지표가 전부 존재하는 **구성 일관 서브샘플**에서만 합성지수 IC를 낸다.
- 각 지표 score 시계열의 **워밍업 구간(첫 PCT_WINDOW 거래일)**을 잘라낸다(초기 백분위는
  신뢰 불가).
- 변동성 레짐(고/저) 분해.
- 예전의 2×2 평균수익률 표는 표본이 8개뿐이라 폐기. 대신 IC CI + 분위 단조성만 본다.
- 튜닝된 파라미터 스윕 없음. 매매 규칙은 제안·검증하지 않는다("검증된 규칙 없음").

사용:
    venv\\Scripts\\python.exe backtest.py
    venv\\Scripts\\python.exe backtest.py --start 2021-01-01 --no-md
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
    d = pd.concat([x, y], axis=1).dropna()
    n = len(d)
    if n < 80:
        return None
    xv, yv = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
    ic = spearmanr(xv, yv).statistic
    rng = np.random.default_rng(seed)
    L = max(horizon, 5)
    boots = np.empty(b)
    for k in range(b):
        ii = _sb_index(n, L, rng)
        boots[k] = spearmanr(xv[ii], yv[ii]).statistic
    lo, hi = np.nanpercentile(boots, [5, 95])
    n_eff = n / horizon
    crosses_zero = lo <= 0 <= hi
    return dict(ic=ic, lo=lo, hi=hi, n=n, n_eff=n_eff, crosses_zero=crosses_zero)


# ---------------------------------------------------------------- report
def _fmt_ci(r: dict | None) -> str:
    if r is None:
        return "표본 부족"
    tag = "  ← 0 포함(노이즈와 구별 불가)" if r["crosses_zero"] else ""
    return f"IC {r['ic']:+.3f}  [90% CI {r['lo']:+.3f}, {r['hi']:+.3f}]  n={r['n']} n_eff≈{r['n_eff']:.0f}{tag}"


def run(start: str | None, write_md: bool) -> None:
    m = fwd_returns(add_composites(build_series()))
    if start:
        m = m[m["date"] >= pd.Timestamp(start)].reset_index(drop=True)
    full = m.dropna(subset=[f"fwd{HORIZONS[-1]}"]).reset_index(drop=True)

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
    P("> 중첩 선행수익률이라 유효 표본 n_eff ≈ n / horizon. IC 는 Spearman.")
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
    cc = full[full["n_ind"] == 7].reset_index(drop=True)
    P(f"구성 일관(7/7) 구간: {len(cc)} 거래일"
      + (f" ({cc['date'].min().date()} ~ {cc['date'].max().date()})" if len(cc) else " — 없음"))
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
        P(f"VKOSPI 중앙값 {med:.1f} 기준 고/저 분할.")
        P("```")
        for gname, gcol in [("투심", "sentiment"), ("추세", "trend"), ("TOTAL7", "total7")]:
            hi = full[full["vk_level"] >= med]
            lo = full[full["vk_level"] < med]
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
    P("> 절대 수익률은 표본이 대부분 강세장이라 전부 양수 — **분위 간 순서(단조성)만** 의미.")
    P()

    # 5) 결론
    P("## 5. 읽는 법 / 주의")
    P()
    P("- 위 CI 중 0 을 안 걸치는 항목만 '이 표본에서 방향성 있음'으로 간주한다.")
    P("- ⚠️ **credit_spread 의 강한 IC 는 과대해석 주의**: BBB−AA 는 매트릭스 프라이싱이라")
    P("  거의 계단식이고(DATA_INVENTORY.md), 2016~2026 의 넓은 스프레드 국면은 사실상 2020·2022")
    P("  두 번의 위기뿐이다. n_eff(18~35)도 그만큼 작다 — '두 위기 이후 반등'을 학습한 것에 가깝다.")
    P("- 투심 그룹의 음(-) IC 는 두 변동성 레짐·7/7 서브샘플에서 모두 유지되나, 그 대부분을")
    P("  credit_spread 가 끌고 간다. Volatility·Put/Call 단독 CI 는 대체로 0 을 걸친다.")
    P("- 추세 그룹·Momentum 은 +60/120일에서 겨우 0 을 벗어나는 수준. Strength·Breadth 는 전부 0 포함.")
    P("- TOTAL7 은 7/7 구간에서 모든 시계 CI 가 0 을 포함 — 단일 합성지수는 타이밍 신호가 아니다.")
    P("- 검증된 매매 규칙은 없다. 이 지표는 시장 맥락 readout 이다.")
    P("- 데이터가 쌓이면(분기 1회) 재실행해 CI 를 좁힌다.")
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
