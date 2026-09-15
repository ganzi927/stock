"""HTML 리포트 조립 (단일 파일, 이미지 base64 내장).

minimalist-ui / redesign-existing-projects 스킬 가이드를 따라
웜 모노크롬 팔레트 + 에디토리얼 타이포그래피 + 카드형 레이아웃으로 구성한다.
"""

from __future__ import annotations

from datetime import date

from charts import gauge_chart, total_trend_chart, trend_chart, zone_colors_css, zone_label
from indicators import IndicatorResult

STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;1,6..72,400&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {
  --ink: #2F3437;
  --muted: #8A8580;
  --canvas: #FBFBFA;
  --surface: #FFFFFF;
  --border: #EAEAEA;
}

* { box-sizing: border-box; }

body {
  font-family: 'Pretendard Variable', Pretendard, -apple-system, 'Malgun Gothic', sans-serif;
  background: var(--canvas);
  color: var(--ink);
  max-width: 880px;
  margin: 0 auto;
  padding: 56px 24px 80px;
  line-height: 1.6;
}

header { margin-bottom: 40px; }

h1 {
  font-family: 'Newsreader', serif;
  font-weight: 500;
  font-size: 32px;
  letter-spacing: -0.01em;
  margin: 0 0 10px;
}

.stat-row {
  display: flex;
  gap: 20px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 13px;
  color: var(--muted);
}
.stat-row b { color: var(--ink); font-weight: 500; }

h2 {
  font-family: 'Newsreader', serif;
  font-weight: 500;
  font-size: 20px;
  margin: 48px 0 18px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
}

.hero {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 32px;
  text-align: center;
}
.hero img { max-width: 320px; }
.hero .score-line {
  font-family: 'JetBrains Mono', monospace;
  font-variant-numeric: tabular-nums;
  font-size: 15px;
  margin-top: 4px;
}

.badge {
  display: inline-block;
  padding: 3px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.trend-wrap { margin-top: 24px; }
.trend-wrap img { max-width: 100%; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 22px 24px;
  opacity: 0;
  animation: rise 500ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
.card:nth-child(1) { animation-delay: 0ms; }
.card:nth-child(2) { animation-delay: 60ms; }
.card:nth-child(3) { animation-delay: 120ms; }
.card:nth-child(4) { animation-delay: 180ms; }
.card:nth-child(5) { animation-delay: 240ms; }
.card:nth-child(6) { animation-delay: 300ms; }
.card:nth-child(7) { animation-delay: 360ms; }
@keyframes rise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.card-name { font-size: 14px; font-weight: 500; }
.card-name .proxy { color: var(--muted); font-weight: 400; font-size: 11px; display: block; margin-top: 2px; }

.card-score {
  font-family: 'JetBrains Mono', monospace;
  font-variant-numeric: tabular-nums;
  font-size: 30px;
  font-weight: 500;
  line-height: 1;
}
.card-raw {
  font-family: 'JetBrains Mono', monospace;
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  font-size: 12px;
  margin-top: 6px;
}

.bar-track {
  width: 100%;
  height: 5px;
  border-radius: 999px;
  background: #F1F0EC;
  margin-top: 14px;
  overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 999px; }

.card-note { color: var(--muted); font-size: 12px; margin-top: 12px; }

details {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 22px;
  margin-bottom: 10px;
}
summary {
  cursor: pointer;
  font-weight: 500;
  font-size: 14px;
  outline: none;
}
details img { max-width: 100%; margin-top: 14px; }

.footer {
  color: var(--muted);
  font-size: 12px;
  margin-top: 56px;
  padding-top: 20px;
  border-top: 1px solid var(--border);
  line-height: 1.8;
}

.section-block { margin-bottom: 64px; }

.ai-note {
  background: #F2F0EA; border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 20px; font-size: 14px; line-height: 1.7; color: var(--ink);
  margin: 16px 0 28px;
}
.ai-note .ai-note-label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em; color: var(--muted);
  text-transform: uppercase; margin-bottom: 8px; display: block;
}
"""


def build_fgi_section(
    total_score: float | None,
    results: list[IndicatorResult],
    total_trend_dates,
    total_trend_scores,
    detail_dfs: dict[str, "pd.DataFrame"],
    commentary: str | None = None,
    sentiment_score: float | None = None,
    trend_score: float | None = None,
) -> str:
    """KFGI 섹션 본문만 반환 (페이지 셸은 combined_main.py/build_page_shell이 담당)."""
    total_gauge = gauge_chart(total_score, "TOTAL KFGI")
    total_trend_img = total_trend_chart(total_trend_dates, total_trend_scores)
    total_zone = zone_label(total_score)
    total_bg, total_text = zone_colors_css(total_score)

    subidx_html = ""
    if sentiment_score is not None and trend_score is not None:
        s_bg, s_text = zone_colors_css(sentiment_score)
        t_bg, t_text = zone_colors_css(trend_score)
        # 백테스트: 추세 高 + 심리 低(공포) 조합이 이후 수익률 가장 좋았고, 추세 低 + 심리
        # 高(탐욕)가 가장 나빴다 (backtest.py, KOSPI 2024~2026).
        if trend_score >= 55 and sentiment_score <= 40:
            combo = "추세 유지 + 투심 공포 — 과거 이 조합 이후 수익률이 가장 좋았음(눌림목 매수 관점)"
        elif trend_score <= 45 and sentiment_score >= 60:
            combo = "추세 약화 + 투심 탐욕 — 과거 이 조합 이후 수익률이 가장 나빴음(경계)"
        elif trend_score <= 45 and sentiment_score <= 45:
            combo = "추세 약화 + 투심 공포 — 하방은 상당 부분 반영됨(반등 시 탄력 가능)"
        else:
            combo = "추세·투심 혼조 — 뚜렷한 편향 없음"
        subidx_html = f"""
      <div class="card-grid" style="margin:8px 0 24px">
        <div class="card"><div class="card-name">추세 지수 <span class="proxy">Momentum·Strength·Breadth · 순행(높을수록 상승추세)</span></div>
          <div class="card-score" style="color:{t_text}">{trend_score:.0f}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{max(0,min(100,trend_score))}%;background:{t_text}"></div></div></div>
        <div class="card"><div class="card-name">투심 지수 <span class="proxy">Volatility·Put/Call·Credit · 역행(낮을수록 매수 유리)</span></div>
          <div class="card-score" style="color:{s_text}">{sentiment_score:.0f}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{max(0,min(100,sentiment_score))}%;background:{s_text}"></div></div></div>
      </div>
      <div class="card-note" style="margin:-16px 0 24px">{combo}. CNN식 7개 등가중 TOTAL은 두 성격이 섞여
      있어(백테스트상 순행에 약하게 기움), 트레이딩엔 이 둘을 나눠 보는 게 유효하다 — RECONCILIATION.md §5.6.</div>"""

    cards_html = ""
    for r in results:
        bg, text = zone_colors_css(r.score)
        zone = zone_label(r.score)
        score_str = f"{r.score:.1f}" if r.score is not None else "N/A"
        raw_str = f"{r.raw:.4f}" if r.raw is not None else "—"
        bar_pct = max(0, min(100, r.score)) if r.score is not None else 0
        proxy_tag = '<span class="proxy">추정치 (proxy)</span>' if r.is_proxy else ""
        cards_html += f"""
        <div class="card">
          <div class="card-top">
            <div class="card-name">{r.name}{proxy_tag}</div>
            <div class="badge" style="background:{bg};color:{text}">{zone}</div>
          </div>
          <div class="card-score" style="color:{text}">{score_str}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{bar_pct}%;background:{text}"></div></div>
          <div class="card-raw">raw {raw_str}</div>
          <div class="card-note">{r.note}</div>
        </div>"""

    commentary_html = ""
    if commentary:
        commentary_html = f'<div class="ai-note"><span class="ai-note-label">AI 요약 (초보자용)</span>{commentary}</div>'

    detail_html = ""
    for name, df in detail_dfs.items():
        if df is None or df.empty:
            continue
        img = trend_chart(df["date"], df["raw"], df["score"], name)
        detail_html += f"""
        <details>
          <summary>{name} — 252일 추이</summary>
          <img src="data:image/png;base64,{img}"/>
        </details>"""

    return f"""
    <div class="section-block">
      <h2>한국형 공포탐욕지수(KFGI)</h2>
      <div class="hero">
        <img src="data:image/png;base64,{total_gauge}"/>
        <div class="score-line">
          <span class="badge" style="background:{total_bg};color:{total_text}">{total_zone}</span>
        </div>
        <div class="trend-wrap"><img src="data:image/png;base64,{total_trend_img}"/></div>
      </div>
      {subidx_html}
      {commentary_html}

      <h2>세부 7개 지표</h2>
      <div class="card-grid">{cards_html}</div>

      <h2>지표별 상세 추이</h2>
      {detail_html}

      <div class="footer">
        추정치(proxy) 표시된 지표는 무료 데이터로 구할 수 없는 원본(VKOSPI, 옵션 풋콜비율, 전종목 신고가/신저가 등)을
        대체 계산한 값입니다.<br/>
        데이터 출처: 네이버 금융(KOSPI/KOSPI200/채권ETF), 한국은행 ECOS(신용스프레드), KRX Open API(VKOSPI·옵션·전종목 시세).
      </div>
    </div>
    """


TAB_STYLE = """
.tabs input[type="radio"] { display: none; }

.tab-labels {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 32px;
  flex-wrap: wrap;
}
.tab-labels label {
  padding: 10px 20px;
  cursor: pointer;
  color: var(--muted);
  font-weight: 500;
  font-size: 14px;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 150ms;
}
.tab-labels label:hover { color: var(--ink); }

.tab-panel { display: none; }
"""


def build_page_shell(
    report_date: date,
    kospi_close: float,
    kospi200_close: float,
    extra_style: str,
    tabs: list[tuple[str, str, str]],
) -> str:
    """전체 페이지 셸. tabs: [(tab_id, 탭 라벨, 탭 내용 HTML), ...] — 탭으로 구분된 단일 페이지."""
    tab_ids = [t[0] for t in tabs]

    inputs_html = "".join(
        f'<input type="radio" name="main-tabs" id="tab-{tid}"{" checked" if i == 0 else ""}>'
        for i, tid in enumerate(tab_ids)
    )
    labels_html = "".join(f'<label for="tab-{tid}">{label}</label>' for tid, label, _ in tabs)
    panels_html = "".join(f'<div class="tab-panel panel-{tid}">{content}</div>' for tid, _, content in tabs)

    visibility_rules = "\n".join(
        f'#tab-{tid}:checked ~ .tab-labels label[for="tab-{tid}"] {{ color: var(--ink); border-bottom-color: var(--ink); }}\n'
        f'#tab-{tid}:checked ~ .tab-panels .panel-{tid} {{ display: block; }}'
        for tid in tab_ids
    )

    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>오늘의 코스피 - {report_date.isoformat()}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>{STYLE}{TAB_STYLE}{extra_style}
{visibility_rules}
</style></head><body>

<header>
  <h1>오늘의 코스피</h1>
  <div class="stat-row">
    <span>{report_date.isoformat()}</span>
    <span>KOSPI <b>{kospi_close:,.2f}</b></span>
    <span>KOSPI200 <b>{kospi200_close:,.2f}</b></span>
  </div>
</header>

<div class="tabs">
  {inputs_html}
  <div class="tab-labels">{labels_html}</div>
  <div class="tab-panels">{panels_html}</div>
</div>

<div class="footer">투자 조언이 아니며 참고용입니다.</div>

</body></html>"""
