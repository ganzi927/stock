"""KOSPI200 옵션 딜러 포지셔닝 리포트 HTML 조립 (report.py와 같은 디자인 시스템 재사용)."""

from __future__ import annotations

from datetime import date

from charts import gauge_chart, zone_colors_css, zone_label
from dealer_positioning import SIGN_CONVENTION_CAVEAT, Levels
from options_charts import dex_profile_chart, gex_profile_chart, synthetic_index_chart, vanna_profile_chart, vol_smile_chart
from report import STYLE

EXTRA_STYLE = """
.level-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.level-table td, .level-table th { padding: 8px 10px; font-size: 13px; border-bottom: 1px solid var(--border); }
.level-table th { text-align: left; color: var(--muted); font-weight: 500; font-size: 12px; }
.level-table td.num { font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; text-align: right; }
.level-table tr.spot-row td { font-weight: 600; background: #F7F6F3; }

.scenario-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; }
.scenario-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 20px 22px;
}
.scenario-name { font-weight: 500; font-size: 14px; margin-bottom: 10px; }
.scenario-row { font-size: 12px; color: var(--muted); margin-top: 6px; }
.scenario-row b { color: var(--ink); font-family: 'JetBrains Mono', monospace; }

.warn-banner {
  background: #FBF3DB; border: 1px solid #E8D9A0; color: #7A5A1E;
  border-radius: 10px; padding: 14px 18px; font-size: 13px; margin-bottom: 20px; line-height: 1.6;
}

.info-banner {
  background: #EEF2ED; border: 1px solid #C9D6C5; color: #3D5C36;
  border-radius: 10px; padding: 14px 18px; font-size: 13px; margin-bottom: 20px; line-height: 1.6;
}

/* 차트 클릭 확대 모달 — JS 없이 순수 CSS(체크박스+label) 방식, 탭과 같은 패턴 */
.modal-toggle { display: none; }
.chart-zoom-trigger { cursor: zoom-in; display: block; position: relative; }
.chart-zoom-trigger .zoom-hint {
  font-size: 12px; color: var(--muted); text-align: center; margin-top: 6px;
}
.modal-overlay {
  display: none; position: fixed; inset: 0; background: rgba(30, 28, 24, 0.7);
  z-index: 1000; align-items: center; justify-content: center; padding: 24px;
}
.modal-toggle:checked ~ .modal-overlay { display: flex; }
.modal-backdrop { position: absolute; inset: 0; cursor: zoom-out; }
.modal-content {
  position: relative; background: var(--surface); border-radius: 14px; padding: 24px;
  max-width: 94vw; max-height: 90vh; overflow: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.35);
}
.modal-content img { max-width: 100%; height: auto; display: block; }
.modal-close {
  position: absolute; top: 10px; right: 14px; cursor: zoom-out; font-size: 20px;
  color: var(--muted); line-height: 1;
}
.modal-close:hover { color: var(--ink); }

.key-points { list-style: none; padding: 0; margin: 14px 0 0; }
.key-points li {
  font-size: 13px; color: var(--ink); padding: 8px 0 8px 16px; position: relative;
  border-bottom: 1px solid var(--border);
}
.key-points li::before { content: "—"; position: absolute; left: 0; color: var(--muted); }

.summary-callout {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px;
  margin-bottom: 20px;
}
.summary-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px;
}
.summary-card .summary-name { font-size: 12px; color: var(--muted); font-weight: 500; margin-bottom: 6px; }
.summary-card .summary-line { font-size: 14px; font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
.summary-card .summary-line b { font-weight: 600; }
.summary-card .summary-target { color: #3D5C36; }
.summary-card .summary-invalid { color: #8A4A47; }
"""


def _level_row(name: str, value: float | None, spot: float, is_spot: bool = False, pot: float | None = None) -> str:
    if value is None:
        return ""
    diff_pct = (value - spot) / spot * 100
    cls = ' class="spot-row"' if is_spot else ""
    pot_cell = f"<td class='num'>{pot*100:.1f}%</td>" if pot is not None else "<td class='num'>—</td>"
    return f"<tr{cls}><td>{name}</td><td class='num'>{value:,.1f}</td><td class='num'>{diff_pct:+.2f}%</td>{pot_cell}</tr>"


def build_section_html(
    title: str,
    expiry_label: str,
    spot: float,
    levels: Levels,
    profile,
    chain_with_greeks,
    scenarios: list[dict],
    net_dex: float,
    net_vex: float,
    net_charm: float,
    iv_rank: float | None,
    override_note: str | None = None,
    commentary: str | None = None,
    dex_profile=None,
    vanna_profile=None,
    pot: dict[str, float] | None = None,
    risk_reversal: tuple[float | None, float | None, float | None] | None = None,
    synth_df=None,
    positioning_skew: dict | None = None,
) -> str:
    level_marks = {
        "call_wall": levels.call_wall,
        "spot": levels.spot,
        "zero_gamma": levels.zero_gamma,
        "max_pain": levels.max_pain,
        "dex_neutral_maxpain": levels.dex_neutral_maxpain,
        "put_wall": levels.put_wall,
    }
    gex_img = gex_profile_chart(profile, level_marks)
    smile_img = vol_smile_chart(chain_with_greeks, spot)
    pot = pot or {}

    # 위/아래 순서로 정렬해 표시 (call_wall/put_wall이 스팟 어느 쪽에 있을지 모르므로
    # 값 기준으로 정렬하고, 스팟 행만 별도 표시). Call Wall과 Put Wall이 같은 행사가로
    # 겹칠 수 있어(OI 집중이 한 지점) 값이 아니라 (라벨, 값) 쌍으로 다뤄야 라벨이 안 섞인다.
    named = [
        ("Call Wall", levels.call_wall, "call_wall"),
        ("Put Wall", levels.put_wall, "put_wall"),
        ("상단 Gamma Wall", levels.call_wall_above, "call_wall_above"),
        ("하단 Gamma Wall", levels.put_wall_below, "put_wall_below"),
    ]
    above = sorted((n, v, k) for n, v, k in named if v is not None and v > spot)
    above.sort(key=lambda nv: nv[1], reverse=True)
    below = sorted((n, v, k) for n, v, k in named if v is not None and v < spot)
    below.sort(key=lambda nv: nv[1], reverse=True)
    at_spot = [(n, v, k) for n, v, k in named if v is not None and v == spot]

    level_rows = "".join(_level_row(n, v, spot, pot=pot.get(k)) for n, v, k in above)
    level_rows += _level_row("Spot (현재가)", spot, spot, is_spot=True)
    level_rows += "".join(_level_row(n, v, spot, pot=pot.get(k)) for n, v, k in at_spot)
    level_rows += "".join(_level_row(n, v, spot, pot=pot.get(k)) for n, v, k in below)
    zg_name = "Zero Gamma"
    if levels.zero_gamma_lo is not None and levels.zero_gamma_hi is not None:
        zg_name = f"Zero Gamma (민감도 {levels.zero_gamma_lo:,.1f}~{levels.zero_gamma_hi:,.1f})"
    level_rows += _level_row(zg_name, levels.zero_gamma, spot, pot=pot.get("zero_gamma"))
    mp_name = "MaxPain (±30% windowed·비표준)"
    if levels.max_pain_20 is not None and levels.max_pain_40 is not None:
        mp_name += f" · ±20%:{levels.max_pain_20:,.0f} ±40%:{levels.max_pain_40:,.0f}"
    level_rows += _level_row(mp_name, levels.max_pain, spot, pot=pot.get("max_pain"))
    level_rows += _level_row("DEX Neutral MaxPain", levels.dex_neutral_maxpain, spot)

    scenario_html = ""
    for sc in scenarios:
        invalidation_row = (
            f'<div class="scenario-row" style="color:#8A4A47">무효화 레벨: <b style="color:#8A4A47">{sc["invalidation"]}</b></div>'
            if sc.get("invalidation")
            else ""
        )
        scenario_html += f"""
        <div class="scenario-card">
          <div class="scenario-name">{sc['name']}</div>
          <div class="scenario-row">Trigger: <b>{sc['trigger']}</b></div>
          <div class="scenario-row">Target: <b>{sc['target']}</b></div>
          {invalidation_row}
          <div class="scenario-row" style="margin-top:10px">{sc['note']}</div>
        </div>"""

    summary_html = ""
    if scenarios:
        cards = ""
        for sc in scenarios:
            invalid_line = (
                f'<div class="summary-line summary-invalid">무효화 {sc["invalidation"]}</div>'
                if sc.get("invalidation")
                else ""
            )
            cards += f"""
        <div class="summary-card">
          <div class="summary-name">{sc['name']}</div>
          <div class="summary-line summary-target">목표 <b>{sc['target']}</b></div>
          {invalid_line}
        </div>"""
        summary_html = f'<div class="summary-callout">{cards}</div>'

    sign_html = f'<div class="warn-banner">⚠ {SIGN_CONVENTION_CAVEAT}</div>'

    warn_html = ""
    if levels.spot_above_range or levels.spot_below_range:
        direction = "위" if levels.spot_above_range else "아래"
        warn_html = (
            f'<div class="warn-banner">⚠ 현재가({spot:,.1f})가 상장된 행사가 범위'
            f'({levels.strike_min:,.1f}~{levels.strike_max:,.1f})보다 {direction}에 있습니다. '
            f"현재가 {direction}쪽에 행사가가 없어 그쪽 Call Wall/Put Wall은 "
            f"계산되지 않았을 수 있습니다.</div>"
        )

    override_html = ""
    if override_note:
        override_html = (
            f'<div class="info-banner">✓ {override_note} — 딜러 방향을 임의로 가정하는 대신, '
            f"KB증권 실제 매매동향(uploads/)에서 확인된 행사가는 그 실제 부호를 썼습니다. "
            f'단 "금융투자"는 마켓메이킹 외 활동도 섞인 분류라 실제 딜러 인벤토리와 정확히 '
            f"같다고 볼 수는 없습니다.</div>"
        )

    commentary_html = ""
    if commentary:
        commentary_html = f'<div class="ai-note"><span class="ai-note-label">AI 요약 (초보자용)</span>{commentary}</div>'

    iv_gauge_html = ""
    if iv_rank is not None:
        img = gauge_chart(iv_rank, "IV Rank")
        iv_gauge_html = f'<div style="text-align:center;max-width:280px;margin:20px auto 0"><img src="data:image/png;base64,{img}"/></div>'

    def _eok(v: float) -> str:
        """원 단위 명목가치를 조/억 자동 스케일로 표기."""
        a = abs(v)
        if a >= 1e12:
            return f"{v / 1e12:+,.2f}조"
        if a >= 1e8:
            return f"{v / 1e8:+,.1f}억"
        if a >= 1e4:
            return f"{v / 1e4:+,.0f}만"
        return f"{v:+,.0f}"

    flow_cards = f"""
    <div class="card-grid" style="margin-top:14px">
      <div class="card"><div class="card-name">Net DEX</div><div class="card-score" style="color:{'#3D5C36' if net_dex>=0 else '#8A4A47'}">{_eok(net_dex)}</div><div class="card-note">딜러 순델타 명목가치(원, delta×OI×승수×스팟). <b>부호는 미국식 가정</b>(딜러 콜·풋 순매도) 기준 — KRX에선 반대일 수 있음</div></div>
      <div class="card"><div class="card-name">Vanna Flow</div><div class="card-score" style="color:{'#3D5C36' if net_vex>=0 else '#8A4A47'}">{_eok(net_vex)}</div><div class="card-note">IV 1%p 상승 시 델타 명목가치 변화(원). 부호는 가정 기준</div></div>
      <div class="card"><div class="card-name">Charm Flow</div><div class="card-score" style="color:{'#3D5C36' if net_charm>=0 else '#8A4A47'}">{_eok(net_charm)}</div><div class="card-note">하루 경과 시 델타 명목가치 변화(원) — 시간가치 소멸. 부호는 가정 기준</div></div>
    </div>"""

    profile_charts_html = ""
    if dex_profile is not None and vanna_profile is not None:
        dex_img = dex_profile_chart(dex_profile, level_marks)
        vanna_img = vanna_profile_chart(vanna_profile, level_marks)
        profile_charts_html = f"""
      <div class="hero" style="display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start">
        <img src="data:image/png;base64,{dex_img}" style="width:100%"/>
        <img src="data:image/png;base64,{vanna_img}" style="width:100%"/>
      </div>"""

    rr_html = ""
    if risk_reversal is not None and risk_reversal[2] is not None:
        call_iv, put_iv, rr = risk_reversal
        rr_color = "#8A4A47" if rr < 0 else "#3D5C36"
        skew_card = ""
        if positioning_skew is not None and positioning_skew.get("oi_skew") is not None:
            oi_sk = positioning_skew["oi_skew"] * 100
            vol_sk = positioning_skew["vol_skew"] * 100 if positioning_skew.get("vol_skew") is not None else None
            sk_color = "#3D5C36" if oi_sk >= 0 else "#8A4A47"
            vol_line = f" · 거래량 {vol_sk:+.1f}%" if vol_sk is not None else ""
            skew_card = f"""
      <div class="card"><div class="card-name">콜/풋 포지션 쏠림도</div><div class="card-score" style="color:{sk_color}">{oi_sk:+.1f}%</div><div class="card-note">미결제약정 (콜−풋)/(콜+풋){vol_line}. 양수면 콜 포지션 우위 — fmkorea "콜 쏠림/상방 쏠림도"와 같은 개념. RR(변동성 스큐)과 다른 축이라 둘이 반대로 나올 수 있음</div></div>"""
        rr_html = f"""
    <div class="card-grid" style="margin-top:14px">
      <div class="card"><div class="card-name">25델타 Risk Reversal</div><div class="card-score" style="color:{rr_color}">{rr:+.2f}%p</div><div class="card-note">25델타 콜 IV({call_iv:.1f}%) − 25델타 풋 IV({put_iv:.1f}%) — 음수면 풋 프리미엄이 더 비쌈(하방 공포 우위), 업계 표준 지표</div></div>{skew_card}
    </div>"""

    synth_html = ""
    if synth_df is not None and not synth_df.empty:
        synth_img = synthetic_index_chart(synth_df, spot)
        deviations = (synth_df["implied_spot"] - spot) / spot * 100
        max_idx = deviations.abs().idxmax()
        worst_strike = synth_df.loc[max_idx, "strike"]
        worst_dev = deviations.loc[max_idx]
        direction = "고평가" if worst_dev > 0 else "저평가"
        synth_html = f"""
      <h2>풋-콜 패리티 합성지수</h2>
      <div class="hero"><img src="data:image/png;base64,{synth_img}"/></div>
      <div class="scenario-row" style="margin-bottom:20px">행사가 {worst_strike:,.1f} 부근 옵션 가격이 내재하는 지수는 실제 스팟 대비 {worst_dev:+.1f}% {direction}되어 있습니다
      (풋-콜 패리티 기준 — C−P+K·e^(−rT)를 스팟으로 환산. 유동성 낮은 행사가는 호가 왜곡이 클 수 있어 참고용입니다).</div>"""

    return f"""
    <div class="section-block">
      <h2>{title} <span style="color:var(--muted);font-weight:400;font-size:14px">— {expiry_label}</span></h2>
      {summary_html}
      {sign_html}
      {warn_html}
      {override_html}
      <div class="hero">
        <img src="data:image/png;base64,{gex_img}"/>
        {iv_gauge_html}
      </div>

      <h2>핵심 레벨</h2>
      <table class="level-table">
        <tr><th>레벨</th><th>가격</th><th>스팟 대비</th><th>PoT(만기 전 터치, 위험중립확률)</th></tr>
        {level_rows}
      </table>
      <div class="card-note" style="margin-top:6px">PoT는 옵션 가격에 내재된 <b>위험중립</b> 확률로, 실제 도달 확률과는 리스크 프리미엄만큼 다릅니다. 각 레벨의 PoT는 ATM IV 하나로 계산돼 스큐를 반영하지 않습니다.</div>
      {commentary_html}

      <h2>딜러 플로우</h2>
      {flow_cards}
      {profile_charts_html}

      <h2>변동성 스마일</h2>
      <div class="hero"><img src="data:image/png;base64,{smile_img}"/></div>
      {rr_html}
      {synth_html}

      <h2>시나리오</h2>
      <div class="scenario-grid">{scenario_html}</div>
    </div>
    """


def build_html(report_date: date, sections_html: list[str]) -> str:
    body = "\n".join(sections_html)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>오늘의 코스피 옵션 - {report_date.isoformat()}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" as="style" crossorigin href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css">
<style>{STYLE}{EXTRA_STYLE}</style></head><body>

<header>
  <h1>코스피200 옵션 딜러 포지셔닝</h1>
  <div class="stat-row"><span>{report_date.isoformat()}</span></div>
</header>

{body}

<div class="footer">
  Black-Scholes 모델 기반 자체 계산. r/q는 각 섹션 제목 옆에 표시 — "(시장)"은 KOSPI200 선물/3개월무위험금리
  선물에서 실시간 역산한 값, "(가정)"은 데이터가 없을 때 쓰는 상수(r=3.0%, q=1.5%). 결측 IV는 log-moneyness
  스마일 보간. Zero Gamma는 r/q/IV 가정을 흔든 모델오차 밴드를 함께 표기.<br/>
  {SIGN_CONVENTION_CAVEAT}<br/>
  데이터 출처: KRX Open API (옵션 일별매매정보). 투자 조언이 아니며 참고용입니다.
</div>

</body></html>"""
