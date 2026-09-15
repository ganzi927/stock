"""KFGI 역사 시계열을 뽑아 KOSPI200 미래수익률에 대한 역행(contrarian) 예측력을 검증한다.

학술 근거: 여러 연구가 KOSPI 투자심리는 3~24개월 시계에서 수익률의 **역행 예측자**라고
보고한다 (Vuong & Suzuki 2022; Bouteska 2024 등). 즉 심리가 탐욕이면 이후 수익률이 낮고,
공포면 높다. 이 스크립트는 우리 KFGI가 실제로 그런지 확인한다.

사용:
    python backtest.py                 # 전체 요약
    python backtest.py --start 2021-01-01

한계: VKOSPI/풋콜/신용스프레드/국고채10년 캐시가 ~1.5~2년치뿐이라 7개 지표가 모두 있는
구간은 짧다. Momentum/Strength/Breadth(전종목 캐시 6년)는 길다 — 매일 '가용한 서브스코어의
평균'으로 KFGI를 만들어(라이브 코드와 동일) 가능한 전 구간을 본다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:  # Windows 콘솔(cp949)에서 em-dash 등 출력 깨짐 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import indicators as ind
from ecos_data import fetch_credit_spread
from krx_market import compute_breadth_and_strength_raw
from main import _load_dotenv
from naver_data import fetch_index_history, fetch_item_history

BASE_DIR = Path(__file__).parent
CACHE = BASE_DIR / "cache"
HORIZONS = [5, 10, 20, 40, 60, 120]


def build_kfgi_series() -> pd.DataFrame:
    """일자별 (KFGI, 가용 지표 수, 각 서브스코어) DataFrame."""
    k200 = fetch_index_history("KPI200", 1600)
    bond = fetch_item_history("148070", 1600)
    vk = pd.read_csv(CACHE / "vkospi.csv", parse_dates=["date"]) if (CACHE / "vkospi.csv").exists() else None
    pc = pd.read_csv(CACHE / "putcall.csv", parse_dates=["date"]) if (CACHE / "putcall.csv").exists() else None
    mk = pd.read_csv(CACHE / "market_kospi.csv", parse_dates=["date"], dtype={"ISU_CD": str})
    bs = compute_breadth_and_strength_raw(mk)
    cs = fetch_credit_spread(900)

    subs = {
        "momentum": ind.compute_momentum(k200),
        "volatility": ind.compute_volatility_real(vk),
        "credit_spread": ind.compute_credit_spread(cs),
        "strength": ind.compute_strength_real(bs),
        "breadth": ind.compute_breadth_real(bs),
        "putcall": ind.compute_putcall_real(pc),
        "safe_haven": ind.compute_safe_haven(k200, bond),
    }
    merged = k200[["date", "close"]].rename(columns={"close": "kospi200"})
    for name, df in subs.items():
        if df is None or df.empty:
            continue
        merged = merged.merge(df[["date", "score"]].rename(columns={"score": name}), on="date", how="left")

    score_cols = [c for c in merged.columns if c not in ("date", "kospi200")]
    merged["kfgi"] = merged[score_cols].mean(axis=1, skipna=True)
    merged["n_ind"] = merged[score_cols].notna().sum(axis=1)
    return merged.dropna(subset=["kfgi"]).reset_index(drop=True)


def _fwd_returns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").reset_index(drop=True)
    for h in HORIZONS:
        df[f"fwd{h}"] = df["kospi200"].shift(-h) / df["kospi200"] - 1
    return df


def report(df: pd.DataFrame, start: str | None) -> None:
    if start:
        df = df[df["date"] >= pd.Timestamp(start)]
    df = _fwd_returns(df).dropna(subset=[f"fwd{HORIZONS[-1]}"])
    print(f"구간 {df['date'].min().date()} ~ {df['date'].max().date()}  ({len(df)}일)")
    print(f"평균 가용 지표 수: {df['n_ind'].mean():.1f} / 7\n")

    # 1) Spearman IC: KFGI[t] vs 미래수익률.  역행이면 음수여야 한다.
    print("── Spearman IC (KFGI vs 미래 KOSPI200 수익률) — 역행 예측이면 음수 ──")
    for h in HORIZONS:
        ic = df["kfgi"].corr(df[f"fwd{h}"], method="spearman")
        print(f"  +{h:3d}일: IC = {ic:+.3f}")

    # 2) KFGI 5분위별 평균 미래수익률
    print("\n── KFGI 5분위별 평균 미래수익률 (%) ──")
    q = pd.qcut(df["kfgi"], 5, labels=["Q1(공포)", "Q2", "Q3", "Q4", "Q5(탐욕)"])
    hdr = "  " + " ".join(f"+{h}일".rjust(8) for h in HORIZONS)
    print(hdr)
    for lab in ["Q1(공포)", "Q2", "Q3", "Q4", "Q5(탐욕)"]:
        row = df[q == lab]
        cells = " ".join(f"{row[f'fwd{h}'].mean()*100:+7.2f}%" for h in HORIZONS)
        print(f"  {lab:9s} {cells}")

    # 3) 극단 구간
    print("\n── 극단값 이후 평균 미래수익률 (%) ──")
    for lab, mask in [("극도 공포 (KFGI<25)", df["kfgi"] < 25), ("극도 탐욕 (KFGI>75)", df["kfgi"] > 75)]:
        sub = df[mask]
        if len(sub) < 5:
            print(f"  {lab}: 표본 {len(sub)}개 (부족)")
            continue
        cells = " ".join(f"{sub[f'fwd{h}'].mean()*100:+7.2f}%" for h in HORIZONS)
        print(f"  {lab} (n={len(sub):3d}): {cells}")

    # 4) 개별 서브스코어 IC (+60일)
    print("\n── 개별 지표 IC (+60일, 음수=역행 예측력) ──")
    for c in ["momentum", "volatility", "credit_spread", "strength", "breadth", "putcall", "safe_haven"]:
        if c in df.columns and df[c].notna().sum() > 60:
            print(f"  {c:14s} {df[c].corr(df['fwd60'], method='spearman'):+.3f}  (n={df[c].notna().sum()})")

    # 5) 두 그룹으로 분해: 심리(파생·신용, 역행) vs 추세(가격·저변, 순행)
    print("\n── 그룹 분해 IC (KFGI를 두 성격으로 나눔) ──")
    groups = {
        "심리(Vol+PutCall+Credit)": ["volatility", "putcall", "credit_spread"],
        "추세(Mom+Strength+Breadth)": ["momentum", "strength", "breadth"],
    }
    for gname, cols in groups.items():
        have = [c for c in cols if c in df.columns]
        g = df[have].mean(axis=1, skipna=True)
        for h in [20, 60, 120]:
            ic = g.corr(df[f"fwd{h}"], method="spearman")
            print(f"  {gname:26s} +{h:3d}일 IC {ic:+.3f}", end="")
        print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    args = ap.parse_args()
    _load_dotenv(BASE_DIR / ".env")
    report(build_kfgi_series(), args.start)
