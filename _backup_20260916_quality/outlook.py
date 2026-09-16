"""4번째 탭: 세 섹션(공포탐욕지수 / 코스피200 옵션 / 삼성전자·SK하이닉스)의 핵심 수치를
한데 모아 Claude가 '종합 판단 + 내일 시나리오'를 작성한다.

투자 조언·방향 확언 금지 규약(ai_commentary.SYSTEM_PROMPT)은 그대로 적용된다 — 시나리오는
"레벨 X 이탈 시 딜러 헤지 구조상 Y 방향으로 가속" 식의 구조 설명이지 예측이 아니다.
ANTHROPIC_API_KEY 가 없으면 이 탭은 생성되지 않는다(combined_main이 건너뜀).
"""

from __future__ import annotations

import html as _html
import re as _re
from datetime import date

from ai_commentary import generate_commentary
from dealer_positioning import Levels

# 레벨/가격 규모(≥100)의 숫자 토큰. 문장수·소수 퍼센트(예: +2.3%)는 제외된다.
_OUTLOOK_NUM_RE = _re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?")


def _level_numbers(text: str) -> set[float]:
    out: set[float] = set()
    for m in _OUTLOOK_NUM_RE.finditer(text):
        try:
            v = float(m.group().replace(",", ""))
        except ValueError:
            continue
        if v >= 100:
            out.add(round(v, 1))
    return out


def _unverified_numbers(prose: str, prompt: str) -> list[float]:
    """산문에 나오는데 프롬프트(=계산으로 넘긴 값)에 근거가 없는 레벨 숫자.
    전사 오류(예: 1,046 → 1,064)·환각을 잡는다. ±0.5% 또는 ±1.0 허용."""
    allowed = _level_numbers(prompt)
    bad = []
    for v in sorted(_level_numbers(prose)):
        if any(abs(v - a) <= max(1.0, a * 0.005) for a in allowed):
            continue
        bad.append(v)
    return bad


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
        _lvl("MaxPain (부분 체인·비표준)", levels.max_pain, "max_pain"),
        _lvl("MaxPain (전 행사가·계약)", levels.max_pain_full),
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
    trend, sentiment, total = fgi.get("trend"), fgi.get("sentiment"), fgi.get("total")
    detail = "  세부: " + ", ".join(f"{k} {v:.0f}" for k, v in fgi.get("indicators", {}).items())
    if trend is None or sentiment is None or total is None:
        return "공포탐욕: 서브지수 계산 불가(데이터 부족).\n" + detail
    lines = [
        f"공포탐욕: 추세지수 {trend:.0f} / 투심지수 {sentiment:.0f}  "
        f"(참고용 CNN식 TOTAL {total:.0f}, 6개 등가중 — 순행·역행 상쇄값이라 단독 판단 금지)",
        "  (추세=Momentum + (Strength·Breadth) 순행 / 투심=Volatility·Put-Call 역행: 투심 낮음=평활 변동성·풋콜 거래량비 높음(공포 측), "
        "높음=평활 변동성·풋콜 거래량비 낮음(탐욕 측). 이 방향성의 예측력은 백테스트 미입증 — VALIDATION.md. Credit Spread는 매크로 배경으로 합성 미포함)",
        detail,
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
        "현재 상태와 상단·하단 관찰 레벨을 설명하라. OI는 롱/숏 소유자를 식별하지 못한다. "
        "Wall 위치만으로 헤지 방향·지지·저항·돌파 후 가속을 추론하지 말라. "
        "Zero Gamma의 전역 부호 반전 불변성은 계약별 부호 변경에는 성립하지 않는다. "
        "MaxPain은 최소 내재가치 계산이지 수렴 예측이 아니다. "
        "PoT는 해당 옵션 만기까지 상수 IV GBM 모형의 위험중립 터치확률이다. "
        "익일 확률이나 서로 배타적인 시나리오 확률로 바꾸거나 합산하지 말라. "
        "숫자는 제공된 값을 그대로 사용하고 투자 조언·미래 방향 예측은 하지 말라. "
        "한국어 존댓말 12~18문장, 이모지·마크다운 금지."

    )
    return "\n".join(parts)


def build_outlook_section(as_of: date, fgi: dict | None, opt_facts: list[dict]) -> str | None:
    if fgi is None or not opt_facts:
        return None
    prompt = build_outlook_prompt(as_of, fgi, opt_facts)
    # max_tokens: 한국어 12~18문장이면 ~2,000+ 토큰이라 1,600에선 자주 잘렸다.
    # 잘린 응답은 generate_commentary가 stop_reason으로 걸러 None을 준다(탭 생략).
    text = generate_commentary(prompt, max_tokens=2600)
    if not text:
        return None

    # 게시 전 검증: 산문 속 레벨 숫자가 실제 계산으로 넘긴 값과 일치하는지 대조한다.
    # LLM이 지어냈거나 잘못 옮겨 적은 레벨(예: 1,046 → 1,064)을 잡는다.
    unverified = _unverified_numbers(text, prompt)
    if unverified:
        return None  # 확인된 숫자 오류가 있는 해설은 게시하지 않는다.
    warn_html = ""

    body = _html.escape(text).replace("\n\n", "</p><p>").replace("\n", "<br/>")
    return f"""
    <div class="section-block">
      <h2>종합 전망 — 내일 시나리오</h2>
      <div class="info-banner">아래는 위 3개 탭의 수치를 Claude가 종합한 것입니다. 레벨 이탈 시
      딜러 헤지 구조가 어느 방향으로 작동하는지에 대한 <b>구조 설명</b>이며 방향 예측·투자 조언이
      아닙니다. 기준일 {as_of.isoformat()} 마감 데이터.</div>
      {warn_html}
      <div class="ai-note" style="font-size:14px;line-height:1.85"><p>{body}</p></div>
    </div>
    """
