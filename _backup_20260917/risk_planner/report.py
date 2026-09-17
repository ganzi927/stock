"""HTML 리포트 조립 (단일 파일, 이미지 base64 내장).

minimalist-ui / redesign-existing-projects 스킬 가이드를 따라
웜 모노크롬 팔레트 + 에디토리얼 타이포그래피 + 카드형 레이아웃으로 구성한다.
"""

from __future__ import annotations

from datetime import date
import html

from charts import gauge_chart, total_trend_chart, trend_chart, zone_colors_css, zone_label
from indicators import MACRO_BACKDROP, IndicatorResult

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

.ai-note, .beginner-note {
  background: #F2F0EA; border: 1px solid var(--border); border-radius: 12px;
  padding: 16px 20px; font-size: 14px; line-height: 1.7; color: var(--ink);
  margin: 16px 0 28px;
}
.ai-note .ai-note-label, .beginner-note .beginner-note-label {
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em; color: var(--muted);
  text-transform: uppercase; margin-bottom: 8px; display: block;
}

.level-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.level-table td, .level-table th { padding: 5px 8px; border-bottom: 1px solid var(--border); }
.level-table th { color: var(--muted); font-weight: 500; text-align: right; }
.level-table td.num { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; text-align: right; }
"""


def _corr_table(corr) -> str:
    """지표 score 상관행렬 → 작은 HTML 표 (WORKPLAN Phase 2-3). 등가중이 '중립'이라는
    암묵 전제를 드러낸다 — Momentum↔Strength 처럼 높으면 사실상 중복 신호."""
    if corr is None or getattr(corr, "empty", True):
        return ""
    cols = list(corr.columns)
    short = {"Momentum": "Mom", "Volatility": "Vol", "Credit Spread": "Cred", "Strength": "Str",
             "Breadth": "Brd", "Put/Call Ratio": "P/C", "Safe Haven Demand": "SH"}
    head = "".join(f"<th>{short.get(c, c)}</th>" for c in cols)
    rows = ""
    for r in cols:
        cells = ""
        for c in cols:
            v = corr.loc[r, c]
            hi = "font-weight:600;color:#8A4A47" if (r != c and abs(v) >= 0.6) else "color:var(--muted)"
            cells += f'<td class="num" style="{hi}">{v:+.2f}</td>'
        rows += f"<tr><td>{short.get(r, r)}</td>{cells}</tr>"
    return f"""
      <details>
        <summary>지표 score 상관행렬 — 등가중의 전제 점검</summary>
        <table class="level-table" style="margin-top:12px"><tr><th></th>{head}</tr>{rows}</table>
        <div class="card-note">|상관| ≥ 0.6 은 사실상 중복 신호(빨강). Momentum·Strength가 대개 여기 걸린다 —
        추세지수는 그래서 가격추세와 저변을 1:1로 재가중한다.</div>
      </details>"""


def _beginner_fgi_explanation(
    results: list[IndicatorResult],
    included: list[str],
    total_score: float | None,
    trend_score: float | None,
    sentiment_score: float | None,
) -> str:
    """API 없이도 남는 현재 상태 설명. 점수와 원자료를 혼동하지 않게 한다."""
    by_name = {r.name: r for r in results}
    sentences = [
        "각 점수는 원자료의 절대 크기가 아니라 최근 252거래일 안에서의 상대적 위치입니다. "
        "예를 들어 20점은 원자료가 20이라는 뜻이 아니라 과거 범위의 낮은 쪽에 있다는 뜻입니다."
    ]
    if trend_score is not None and sentiment_score is not None:
        trend_state = "강한 편" if trend_score >= 60 else "약한 편" if trend_score <= 40 else "중간"
        sent_state = "안심 쪽" if sentiment_score >= 60 else "공포·헤지수요 쪽" if sentiment_score <= 40 else "중간"
        sentences.append(
            f"현재 추세지수는 {trend_score:.0f}점으로 {trend_state}이고, 투심지수는 "
            f"{sentiment_score:.0f}점으로 {sent_state}입니다. 두 값이 엇갈리면 가격 흐름과 "
            "옵션시장의 긴장도가 서로 다른 상태라는 뜻이지, 다음 방향을 예측한다는 뜻은 아닙니다."
        )
    def indicator_sentence(r: IndicatorResult) -> str | None:
        if r.score is None:
            return None
        if r.name == "Momentum":
            raw = f" 현재 지수/125일 이동평균 비율은 {r.raw:.3f}배이고," if r.raw is not None else ""
            return f"Momentum은 코스피200의 중기 가격 흐름을 자기 과거와 비교합니다.{raw} 252일 백분위 점수는 {r.score:.1f}점입니다."
        if r.name == "Volatility":
            raw = f" 기준일 VKOSPI는 {r.raw:.2f}이고," if r.raw is not None else ""
            return f"Volatility는 VKOSPI 20일 평균을 거꾸로 점수화해 높을수록 변동성 긴장이 과거보다 낮았음을 뜻합니다.{raw} 점수는 {r.score:.1f}점입니다."
        if r.name == "Put/Call Ratio":
            raw = f" 기준일 정규세션 풋/콜 거래량비는 {r.raw:.2f}이고," if r.raw is not None else ""
            return f"Put/Call Ratio는 5일 평균을 거꾸로 점수화해 높을수록 풋 거래량 비율이 과거보다 낮았음을 뜻합니다.{raw} 점수는 {r.score:.1f}점입니다."
        return None
    for name in included:
        r = by_name.get(name)
        sentence = indicator_sentence(r) if r is not None else None
        if sentence:
            sentences.append(sentence)
    if total_score is not None:
        sentences.append(
            f"참고 TOTAL {total_score:.1f}점은 이번 품질 게이트를 통과한 "
            f"{', '.join(included) if included else '지표 없음'}의 단순 평균이며, 전날과 구성 항목이 다르면 숫자를 그대로 비교하면 안 됩니다."
        )
    excluded = [r.name for r in results if r.evidence and r.evidence.get("usage") == "research"]
    if excluded:
        research_scores = ", ".join(
            f"{r.name} {r.score:.1f}점" for r in results
            if r.name in excluded and r.score is not None
        )
        sentences.append(
            f"연구용 지표의 현재 점수는 {research_scores or ', '.join(excluded)}입니다. "
            "Strength는 상승·하락 종목의 규모, Breadth는 상승·하락 거래량의 폭, Credit Spread와 "
            "Safe Haven Demand는 신용·안전자산 배경을 살펴보는 값입니다. 이 지표들은 자료 또는 방법론이 충분히 검증되지 않아 "
            "TOTAL과 AI 판단에서는 제외하고 아래 연구용 영역에 따로 표시합니다."
        )
    body = " ".join(html.escape(s) for s in sentences)
    return f'<div class="beginner-note"><span class="beginner-note-label">오늘의 지표 읽기 (초보자용)</span>{body}</div>'


def build_fgi_section(
    total_score: float | None,
    results: list[IndicatorResult],
    total_trend_dates,
    total_trend_scores,
    detail_dfs: dict[str, "pd.DataFrame"],
    commentary: str | None = None,
    sentiment_score: float | None = None,
    trend_score: float | None = None,
    corr=None,
) -> str:
    """KFGI 섹션 본문만 반환 (페이지 셸은 combined_main.py/build_page_shell이 담당).

    WORKPLAN Phase 2-1: 헤드라인은 추세지수/투심지수 두 개다. 단일 TOTAL은 순행·역행
    신호가 상쇄된 값이라 트레이딩 타이밍엔 무의미 — 'CNN 비교용' 각주로만 표시한다."""
    total_trend_img = total_trend_chart(total_trend_dates, total_trend_scores)
    total_zone = zone_label(total_score)
    total_bg, total_text = zone_colors_css(total_score)
    total_str = f"{total_score:.1f}" if total_score is not None else "N/A"
    included = [r.name for r in results if r.evidence and r.evidence.get("usage") == "context"]
    beginner_html = _beginner_fgi_explanation(
        results, included, total_score, trend_score, sentiment_score
    )

    subidx_html = ""
    if sentiment_score is not None and trend_score is not None:
        s_bg, s_text = zone_colors_css(sentiment_score)
        t_bg, t_text = zone_colors_css(trend_score)
        sent_gauge = gauge_chart(sentiment_score, "투심 지수 (역행)")
        trend_gauge = gauge_chart(trend_score, "추세 지수 (순행)")
        # 추세·투심의 현재 상태를 방향 서술 없이 사실만 기술한다. 예전엔 여기서
        # "추세 高 + 투심 低 → 눌림목 매수" 식 조합 규칙을 냈으나, 근거였던 2×2
        # 수익률 표를 VALIDATION.md §4가 표본 부족(n=8)으로 폐기했고 WORKPLAN §0.1은
        # 방향 예측을 명시적으로 범위 밖으로 둔다 — 그래서 제거했다.
        def _state(v: float, hi: str, mid: str, lo: str) -> str:
            return hi if v >= 60 else lo if v <= 40 else mid

        combo = (
            f"현재 상태: 추세 {_state(trend_score, '강', '중립', '약')}({trend_score:.0f}) · "
            f"투심 {_state(sentiment_score, '안심/방심', '중립', '공포/헤지수요')}({sentiment_score:.0f})"
        )
        subidx_html = f"""
      <div class="hero" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:start">
        <div><img src="data:image/png;base64,{trend_gauge}"/>
          <div class="score-line"><span class="badge" style="background:{t_bg};color:{t_text}">{zone_label(trend_score)}</span></div>
          <div class="card-note">추세지수 · 실제 사용 구성은 데이터 상태 표 참고</div></div>
        <div><img src="data:image/png;base64,{sent_gauge}"/>
          <div class="score-line"><span class="badge" style="background:{s_bg};color:{s_text}">{zone_label(sentiment_score)}</span></div>
          <div class="card-note">Volatility·Put/Call · 역행 지표(높음 = 변동성·풋수요 낮음)</div></div>
      </div>
      <div class="card-note" style="margin:12px 0 20px">{combo}.<br/>
      <b>검증 주의</b> — 데이터 품질 조건을 충족한 지표만 합성합니다. 예측력은 별도 검증 전이며 구성은 위 상태표를 확인하세요.<br/>
      <b>참고(CNN 비교용) TOTAL {total_str}</b> — 가용한 판단용 지표의 평균(구성은 데이터 상태 표 참고).
      순행·역행이 섞여 상쇄되므로 단일 타이밍 툴로 쓰지 말 것 (VALIDATION.md).</div>"""

    cards_html = ""
    research_cards_html = ""
    for r in results:
        bg, text = zone_colors_css(r.score)
        zone = zone_label(r.score)
        score_str = f"{r.score:.1f}" if r.score is not None else "N/A"
        ci_str = f'<span style="font-size:13px;color:var(--muted)"> ±{r.score_ci:.0f}</span>' if getattr(r, "score_ci", None) else ""
        raw_str = f"{r.raw:.4f}" if r.raw is not None else "—"
        bar_pct = max(0, min(100, r.score)) if r.score is not None else 0
        proxy_tag = '<span class="proxy">추정치 (proxy)</span>' if r.is_proxy else ""
        if r.name in MACRO_BACKDROP:
            proxy_tag += '<span class="proxy">합성 제외 · 매크로 배경</span>'
        if getattr(r, "low_confidence", False):
            proxy_tag += '<span class="proxy">합성 제외 · 점수화 히스토리 &lt;1년</span>'
        since_txt = f" · 점수화 시작 {r.scored_since}" if getattr(r, "scored_since", None) else ""
        card_html = f"""
        <div class="card">
          <div class="card-top">
            <div class="card-name">{r.name}{proxy_tag}</div>
            <div class="badge" style="background:{bg};color:{text}">{zone}</div>
          </div>
          <div class="card-score" style="color:{text}">{score_str}{ci_str}</div>
          <div class="bar-track"><div class="bar-fill" style="width:{bar_pct}%;background:{text}"></div></div>
          <div class="card-raw">raw {raw_str}</div>
          <div class="card-note">{r.note}{since_txt}</div>
        </div>"""
        if r.evidence and r.evidence.get('usage') == 'research':
            research_cards_html += card_html
        else:
            cards_html += card_html


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
      {subidx_html}
      <div class="trend-wrap"><img src="data:image/png;base64,{total_trend_img}"/></div>
      {_corr_table(corr)}
      {beginner_html}
      {commentary_html}

      <h2>세부 지표</h2>
      <div class="card-grid">{cards_html}</div>

      <details class="research-panel"><summary>연구용 지표 — 기본 합성·AI에서 제외</summary><div class="card-grid">{research_cards_html}</div></details>
      <h2>지표별 상세 추이 (연구 참고)</h2>
      {detail_html}

      <div class="footer">
        이 지표군은 <b>코스피 대형주(코스피200) 포지셔닝·심리 readout</b>입니다 — 광의 시장지수·코스닥은 범위 밖.
        Strength·Breadth는 일자별 시총 상위 200, Volatility는 VKOSPI 20일 이동평균(CNN 50일에서 반응성 위해 단축).
        Credit Spread는 매트릭스 프라이싱된 매크로 신용 배경이라 TOTAL·투심 합성에서 제외하고 참고로만 표시합니다.
        점수화는 전 지표 공통 252일 롤링 백분위(커브핏 계수 없음). 추정치(proxy)는 무료 데이터로 원본을 못 구해 대체 계산한 값.<br/>
        데이터 출처: 네이버 금융(KOSPI/KOSPI200), 한국은행 ECOS(신용스프레드·국고채10년), KRX Open API(VKOSPI·옵션·전종목 시세).
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
