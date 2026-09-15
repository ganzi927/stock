"""4번째 탭: 세 섹션(공포탐욕지수 / 코스피200 옵션 / 삼성전자·SK하이닉스)의 핵심 수치를
한데 모아 Claude가 '종합 판단 + 내일 시나리오'를 작성한다.

투자 조언·방향 확언 금지 규약(ai_commentary.SYSTEM_PROMPT)은 그대로 적용된다 — 시나리오는
"레벨 X 이탈 시 딜러 헤지 구조상 Y 방향으로 가속" 식의 구조 설명이지 예측이 아니다.
ANTHROPIC_API_KEY 가 없으면 이 탭은 생성되지 않는다(combined_main이 건너뜀).
"""

from __future__ import annotations

from datetime import date

from ai_commentary import generate_commentary
from dealer_positioning import Levels


def section_facts(
    title: str,
    expiry_label: str,
    spot: float,
    levels: Levels,
    scenarios: list[dict],
    net_dex: float,
    net_vex: float,
    net_charm: float,
    risk_reversal,
    skew: dict | None,
    pot: dict | None,
) -> dict:
    """옵션 섹션 하나의 압축 요약 (outlook 프롬프트용)."""
    pot = pot or {}

    def _lvl(name: str, v: float | None, key: str | None = None) -> str | None:
        if v is None:
            return None
        p = pot.get(key) if key else None
        pct = (v - spot) / spot * 100
        return f"{name} {v:,.1f} ({pct:+.1f}%{f', PoT {p*100:.0f}%' if p is not None else ''})"

    lvls = [
        _lvl("Call Wall", levels.call_wall, "call_wall"),
        _lvl("상단 Gamma Wall", levels.call_wall_above),
        _lvl("Zero Gamma", levels.zero_gamma, "zero_gamma"),
        _lvl("MaxPain", levels.max_pain, "max_pain"),
        _lvl("DEX Neutral", levels.dex_neutral_maxpain),
        _lvl("Put Wall", levels.put_wall, "put_wall"),
        _lvl("하단 Gamma Wall", levels.put_wall_below),
    ]
    rr_txt = ""
    if risk_reversal and risk_reversal[2] is not None:
        rr_txt = f"25D RR {risk_reversal[2]:+.2f}%p (콜IV {risk_reversal[0]:.1f} / 풋IV {risk_reversal[1]:.1f})"
    skew_txt = ""
    if skew and skew.get("oi_skew") is not None:
        skew_txt = f"포지션 쏠림도(OI) {skew['oi_skew']*100:+.0f}%"
        if skew.get("vol_skew") is not None:
            skew_txt += f" / 거래량 {skew['vol_skew']*100:+.0f}%"
    return {
        "title": title,
        "expiry_label": expiry_label,
        "spot": spot,
        "levels": [x for x in lvls if x],
        "flow": f"Net DEX {net_dex/1e8:+,.0f}억 · Vanna {net_vex/1e8:+,.1f}억 · Charm {net_charm/1e8:+,.1f}억",
        "rr": rr_txt,
        "skew": skew_txt,
        "scenarios": [
            f"{s['name']}: {s['trigger']} → {s['target']}" + (f" (무효화 {s['invalidation']})" if s.get("invalidation") else "")
            for s in scenarios
        ],
    }


def _fmt_fgi(fgi: dict) -> str:
    lines = [
        f"공포탐욕지수 TOTAL {fgi['total']:.0f} / 추세지수 {fgi['trend']:.0f} / 투심지수 {fgi['sentiment']:.0f}",
        "  (추세=Momentum·Strength·Breadth 순행 / 투심=Volatility·Put-Call·Credit 역행: 투심 낮을수록 공포=매수유리)",
        "  세부: " + ", ".join(f"{k} {v:.0f}" for k, v in fgi["indicators"].items()),
    ]
    return "\n".join(lines)


def _fmt_opt(f: dict) -> str:
    out = [f"[{f['title']}]  {f['expiry_label']}", f"  현재가 {f['spot']:,.1f}"]
    if f["levels"]:
        out.append("  레벨: " + " | ".join(f["levels"]))
    if f["rr"]:
        out.append("  " + f["rr"])
    if f["skew"]:
        out.append("  " + f["skew"])
    out.append("  " + f["flow"])
    if f["scenarios"]:
        out.append("  시나리오: " + " ; ".join(f["scenarios"]))
    return "\n".join(out)


def build_outlook_prompt(as_of: date, fgi: dict, opt_facts: list[dict]) -> str:
    parts = [
        f"기준일 {as_of.isoformat()}. 아래는 오늘 마감 기준 세 가지 분석의 핵심 수치다.",
        "",
        _fmt_fgi(fgi),
        "",
        "── 옵션 딜러 포지셔닝 (코스피200 정규/위클리 + 삼성전자 + SK하이닉스) ──",
    ]
    for f in opt_facts:
        parts.append(_fmt_opt(f))
        parts.append("")
    parts.append(
        "위를 종합해 다음을 작성하라. 투자 조언·방향 예측 확언 금지. 시나리오는 "
        "'레벨 이탈 시 딜러 헤지 구조상 어느 방향으로 가속되는가'라는 구조 설명이며, "
        "PoT(터치확률)가 있으면 그 수치를 사실로 인용하라.\n"
        "1. 한 문단: 오늘 시장 상태 종합 — 추세지수와 투심지수가 말하는 것, 지수옵션과 "
        "개별주식(삼성·하이닉스) 구조가 일치하는지 엇갈리는지.\n"
        "2. 내일(익일) 관찰 시나리오 3개 — 기본(현 구조 유지 시) / 상방 / 하방. 각각 "
        "'어느 레벨을 넘거나 이탈하면' + '그때 딜러 헤지가 어느 방향으로 작동해' + "
        "'다음 레벨은 어디' 형식으로. 레벨 숫자를 반드시 포함.\n"
        "3. 한 줄: 내일 가장 먼저 확인할 레벨 하나와 그 이유.\n"
        "소제목 없이 자연스러운 문단으로. 한국어 존댓말, 12~18문장, 이모지·마크다운 금지."
    )
    return "\n".join(parts)


def build_outlook_section(as_of: date, fgi: dict | None, opt_facts: list[dict]) -> str | None:
    if fgi is None or not opt_facts:
        return None
    text = generate_commentary(build_outlook_prompt(as_of, fgi, opt_facts), max_tokens=1600)
    if not text:
        return None
    body = text.replace("\n\n", "</p><p>").replace("\n", "<br/>")
    return f"""
    <div class="section-block">
      <h2>종합 전망 — 내일 시나리오</h2>
      <div class="info-banner">아래는 위 3개 탭의 수치를 Claude가 종합한 것입니다. 레벨 이탈 시
      딜러 헤지 구조가 어느 방향으로 작동하는지에 대한 <b>구조 설명</b>이며 방향 예측·투자 조언이
      아닙니다. 기준일 {as_of.isoformat()} 마감 데이터.</div>
      <div class="ai-note" style="font-size:14px;line-height:1.85"><p>{body}</p></div>
    </div>
    """
