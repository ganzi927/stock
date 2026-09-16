"""옵션 딜러 포지셔닝 차트: GEX 프로파일, 변동성 스마일."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from charts import BORDER, CANVAS, INK, MUTED, _fig_to_base64, _style_axes

LEVEL_COLORS = {
    "spot": "#2F3437",
    "max_pain": "#8A6B33",
    "dex_neutral_maxpain": "#B58A4A",
    "zero_gamma": "#8A4A47",
    "call_wall": "#4F6B38",
    "put_wall": "#8A4A47",
}
LEVEL_LABELS = {
    "spot": "Spot",
    "max_pain": "MaxPain",
    "dex_neutral_maxpain": "DEX Neutral MaxPain",
    "zero_gamma": "Zero Gamma",
    "call_wall": "Call Wall",
    "put_wall": "Put Wall",
}


def gex_profile_chart(profile: pd.Series, levels: dict[str, float | None]) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = ["#8FAE84" if v >= 0 else "#D9A9A6" for v in profile.values]
    ax.bar(profile.index, profile.values / 1e8, width=(profile.index[1] - profile.index[0]) * 0.9, color=colors)
    ax.axhline(0, color=INK, linewidth=0.8)

    for key, value in levels.items():
        if value is None:
            continue
        ax.axvline(value, color=LEVEL_COLORS.get(key, MUTED), linestyle="--", linewidth=1, alpha=0.8)
        ax.text(
            value,
            ax.get_ylim()[1] * 0.95,
            LEVEL_LABELS.get(key, key),
            rotation=90,
            fontsize=8,
            color=LEVEL_COLORS.get(key, MUTED),
            va="top",
            ha="right",
        )

    ax.set_title("Net GEX 프로파일 (억원, 스팟 가정별)", fontsize=11, loc="left", color=INK)
    ax.set_xlabel("KOSPI200 지수", fontsize=9, color=MUTED)
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_base64(fig)


def _line_profile_chart(profile: pd.Series, levels: dict[str, float | None], title: str, color_pos: str, color_neg: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    xs = profile.index.to_numpy()
    # DEX/Vanna는 명목가치(원)라 지수옵션에선 조 단위 — 값 크기에 맞춰 억/조 자동 스케일
    unit_div, unit = (1e12, "조원") if float(pd.Series(profile.values).abs().max() or 0) >= 1e12 else (1e8, "억원")
    title = title.replace("억원", unit)
    ys = profile.values / unit_div
    ax.plot(xs, ys, color=INK, linewidth=1.3)
    ax.fill_between(xs, ys, 0, where=(ys >= 0), color=color_pos, alpha=0.5)
    ax.fill_between(xs, ys, 0, where=(ys < 0), color=color_neg, alpha=0.5)
    ax.axhline(0, color=INK, linewidth=0.8)

    for key, value in levels.items():
        if value is None:
            continue
        ax.axvline(value, color=LEVEL_COLORS.get(key, MUTED), linestyle="--", linewidth=1, alpha=0.8)
        ax.text(
            value,
            ax.get_ylim()[1] * 0.95,
            LEVEL_LABELS.get(key, key),
            rotation=90,
            fontsize=8,
            color=LEVEL_COLORS.get(key, MUTED),
            va="top",
            ha="right",
        )

    ax.set_title(title, fontsize=11, loc="left", color=INK)
    ax.set_xlabel("KOSPI200 지수", fontsize=9, color=MUTED)
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_base64(fig)


def dex_profile_chart(profile: pd.Series, levels: dict[str, float | None]) -> str:
    return _line_profile_chart(profile, levels, "Net DEX 프로파일 (억원, 스팟 가정별)", "#8FAE84", "#D9A9A6")


def vanna_profile_chart(profile: pd.Series, levels: dict[str, float | None]) -> str:
    return _line_profile_chart(profile, levels, "Net Vanna 프로파일 (억원, 스팟 가정별)", "#8FA8AE", "#D9C1A9")


def synthetic_index_chart(synth_df: pd.DataFrame, spot: float) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(synth_df["strike"], synth_df["implied_spot"], marker="o", markersize=3, linewidth=1.2, color="#6B7A8F")
    ax.axhline(spot, color=INK, linestyle="--", linewidth=1, alpha=0.7)
    ax.text(synth_df["strike"].iloc[-1], spot, f" 실제 Spot {spot:,.1f}", fontsize=8, color=MUTED, va="center", ha="left")
    ax.set_title("풋-콜 패리티 내재 스팟 (행사가별)", fontsize=11, loc="left", color=INK)
    ax.set_xlabel("행사가", fontsize=9, color=MUTED)
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_base64(fig)


def vol_smile_chart(chain: pd.DataFrame, spot: float) -> str:
    fig, ax = plt.subplots(figsize=(8, 3.6))
    for opt_type, color, label in [("C", "#6B7A8F", "Call"), ("P", "#B58A4A", "Put")]:
        sub = chain[(chain["type"] == opt_type) & chain["iv"].notna() & (chain["iv"] > 0)].sort_values("strike")
        ax.plot(sub["strike"], sub["iv"], marker="o", markersize=3, linewidth=1.2, color=color, label=label)

    ax.axvline(spot, color=INK, linestyle="--", linewidth=1, alpha=0.6)
    ax.text(spot, ax.get_ylim()[1] if ax.get_ylim()[1] else 1, "Spot", fontsize=8, color=MUTED, ha="center", va="bottom")
    ax.set_title("Volatility Smile (IV vs 행사가)", fontsize=11, loc="left", color=INK)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    _style_axes(ax)
    fig.tight_layout()
    return _fig_to_base64(fig)
