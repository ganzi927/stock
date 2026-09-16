"""게이지 차트 및 추이 차트를 그려서 base64 PNG 문자열로 반환.

미니멀·에디토리얼 톤(웜 모노크롬 + 채도 낮춘 파스텔)으로 통일한다.
"""

from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = "Malgun Gothic"  # Windows 기본 한글 폰트
plt.rcParams["axes.unicode_minus"] = False

INK = "#2F3437"
MUTED = "#8A8580"
CANVAS = "#FBFBFA"
BORDER = "#EAEAEA"

# 5단계 존 색상 — 채도를 낮춘 웜 모노크롬 파스텔 계열 (report.py의 ZONES와 1:1 대응)
ZONE_COLORS = [
    (0, 25, "#D9A9A6"),   # 극도 공포
    (25, 45, "#DCC08F"),  # 공포
    (45, 55, "#DED9B8"),  # 중립
    (55, 75, "#B7C79E"),  # 탐욕
    (75, 100, "#8FAE84"), # 극도 탐욕
]
ZONE_LABELS = {0: "극도 공포", 25: "공포", 45: "중립", 55: "탐욕", 75: "극도 탐욕"}


def _style_axes(ax) -> None:
    ax.set_facecolor(CANVAS)
    for spine in ax.spines.values():
        spine.set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.title.set_color(INK)
    ax.grid(alpha=0.5, color=BORDER, linewidth=0.8)


def _fig_to_base64(fig) -> str:
    fig.patch.set_facecolor(CANVAS)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=CANVAS)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def zone_label(score: float | None) -> str:
    if score is None:
        return "N/A"
    for lo, hi, _ in ZONE_COLORS:
        if lo <= score < hi or (hi == 100 and score == 100):
            return ZONE_LABELS[lo]
    return "N/A"


def zone_colors_css(score: float | None) -> tuple[str, str]:
    """배지용 (배경, 텍스트) 색상. report.py의 CSS 배지에 그대로 사용."""
    text_colors = {0: "#8A4A47", 25: "#8A6B33", 45: "#7A7350", 55: "#4F6B38", 75: "#3D5C36"}
    if score is None:
        return "#EFEFED", MUTED
    for lo, hi, bg in ZONE_COLORS:
        if lo <= score < hi or (hi == 100 and score == 100):
            return bg, text_colors[lo]
    return "#EFEFED", MUTED


def gauge_chart(value: float | None, title: str) -> str:
    fig, ax = plt.subplots(figsize=(4, 2.4), subplot_kw={"aspect": "equal"})
    ax.set_xlim(-1.15, 1.15)
    ax.set_ylim(0, 1.15)
    ax.axis("off")

    for lo, hi, color in ZONE_COLORS:
        theta1 = 180 - (lo / 100 * 180)
        theta2 = 180 - (hi / 100 * 180)
        wedge = mpatches.Wedge((0, 0), 1.0, theta2, theta1, width=0.24, facecolor=color, edgecolor=CANVAS, linewidth=2)
        ax.add_patch(wedge)

    if value is not None:
        angle = np.deg2rad(180 - (value / 100 * 180))
        x, y = np.cos(angle) * 0.66, np.sin(angle) * 0.66
        ax.plot([0, x], [0, y], color=INK, linewidth=2.2, solid_capstyle="round")
        ax.scatter([0], [0], color=INK, s=24, zorder=5)
        label = f"{value:.1f}"
    else:
        label = "N/A"

    ax.text(0, -0.08, label, ha="center", va="center", fontsize=22, color=INK)
    ax.text(0, 1.08, title, ha="center", va="center", fontsize=11, color=MUTED)
    return _fig_to_base64(fig)


def trend_chart(dates: pd.Series, raw: pd.Series, score: pd.Series, title: str) -> str:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 4.2), sharex=True)
    ax1.plot(dates, raw, color="#6B7A8F", linewidth=1.3)
    ax1.set_title(f"{title} — Raw Value", fontsize=10, loc="left")
    _style_axes(ax1)

    ax2.plot(dates, score, color=INK, linewidth=1.4)
    for lo, hi, color in ZONE_COLORS:
        ax2.axhspan(lo, hi, color=color, alpha=0.35, linewidth=0)
    ax2.set_ylim(0, 100)
    ax2.set_title("Score (0-100)", fontsize=10, loc="left")
    _style_axes(ax2)

    fig.autofmt_xdate()
    fig.tight_layout()
    return _fig_to_base64(fig)


def total_trend_chart(dates: pd.Series, total_scores: pd.Series) -> str:
    fig, ax = plt.subplots(figsize=(7, 2.6))
    ax.plot(dates, total_scores, color=INK, linewidth=1.8)
    for lo, hi, color in ZONE_COLORS:
        ax.axhspan(lo, hi, color=color, alpha=0.35, linewidth=0)
    ax.set_ylim(0, 100)
    ax.set_title("TOTAL KFGI 추이 (최근 60거래일)", fontsize=11, loc="left", color=INK)
    _style_axes(ax)
    fig.autofmt_xdate()
    fig.tight_layout()
    return _fig_to_base64(fig)
