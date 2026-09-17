"""기준일 일치 관측값만 사용하는 결정론적 종합 상태. 기본 LLM 호출 없음."""

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
        "observed_levels": [
            f"{s['name']}: {s['value']:,.1f}, 종가 대비 {s['distance_pct']:+.2f}% ({s['position']}); {s['definition']}; {s['limitation']}"
            for s in scenarios
        ],
    }


def _fmt_fgi(fgi: dict) -> str:
    trend, sentiment, total = fgi.get("trend"), fgi.get("sentiment"), fgi.get("total")
    detail = "  세부: " + ", ".join(f"{k} {v:.0f}" for k, v in fgi.get("indicators", {}).items())
    if trend is None or sentiment is None or total is None:
        return "공포탐욕: 서브지수 계산 불가(데이터 부족).\n" + detail
    lines = [
        f"공포탐욕: 추세지수 {trend:.0f} / 투심지수 {sentiment:.0f} / 참고 TOTAL {total:.0f}",
        "투심 낮음=평활 변동성·풋콜 거래량비 높음; 높음=그 반대. 매매 방향은 미검증.",
        "사용 구성: " + ", ".join(fgi.get("included", list(fgi.get("indicators", {})))),
        detail,
    ]
    return "\n".join(lines)


def _fmt_opt(f: dict) -> str:
    # Explicit allowlist: nested quality/research payload never reaches the model.
    if f.get('usage') != 'context':
        return ""
    out = [f"[{f['title']}] 기준일 {f['as_of']}"]
    if f.get('spot') is not None: out.append(f"기초자산 기준일 종가 {f['spot']:,.1f} {f.get('spot_unit', '포인트')}")
    labels = {'call_oi':'콜 OI','put_oi':'풋 OI','call_volume':'콜 당일 거래량','put_volume':'풋 당일 거래량'}
    for key in ('call_oi','put_oi','call_volume','put_volume'):
        value=f.get('observations',{}).get(key)
        if isinstance(value,(int,float)): out.append(f"{labels[key]}: {value:,.0f}계약")
    obs=f.get('observations',{})
    if isinstance(obs.get('call_oi'),(int,float)) and obs['call_oi']>0 and isinstance(obs.get('put_oi'),(int,float)):
        out.append(f"풋/콜 OI 비율: {obs['put_oi']/obs['call_oi']:.2f}")
    if isinstance(obs.get('call_volume'),(int,float)) and obs['call_volume']>0 and isinstance(obs.get('put_volume'),(int,float)):
        out.append(f"풋/콜 거래량 비율: {obs['put_volume']/obs['call_volume']:.2f}")
    out.append("위 수량은 방향성·딜러 순포지션을 식별하지 못한다.")
    return "\n".join(out)


def build_outlook_prompt(as_of: date, fgi: dict, opt_facts: list[dict]) -> str:
    eligible = {k:v for k,v in fgi.get('indicators',{}).items()
                if fgi.get('quality',{}).get(k,{}).get('usage') == 'context' and k in fgi.get('included', [])}
    fgi = dict(fgi, indicators=eligible, included=list(eligible))
    opt_facts = [f for f in opt_facts if f.get('usage') == 'context' and f.get('as_of') == as_of.isoformat()]
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
        "주식 초보자가 네 상품의 차이를 이해하도록 먼저 KFGI의 추세·투심 상태를 설명하고, 이어 정규월물·위클리·삼성전자·SK하이닉스를 각각 최소 한 문장씩 빠짐없이 비교하라. "
        "OI는 아직 청산되지 않은 계약 잔량, 거래량은 오늘 거래된 계약 수라고 짧게 풀어라. 제공된 현재 상태와 관측 수량만 설명하라. 연구용 옵션 레벨은 입력에 없으므로 만들지 말라. OI는 롱/숏 소유자를 식별하지 못한다. "
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
    opt_facts = [f for f in opt_facts if f.get('usage') == 'context'
                 and f.get('as_of') == as_of.isoformat()]
    if fgi is None or not opt_facts:
        return None
    eligible = {k:v for k,v in fgi.get('indicators', {}).items()
                if k in fgi.get('included', []) and fgi.get('quality', {}).get(k, {}).get('usage') == 'context'}
    paragraphs = [_fmt_fgi(dict(fgi, indicators=eligible, included=list(eligible)))]
    scores = [f"{k} {v:.1f}점" for k,v in eligible.items() if k in ('Volatility', 'Put/Call Ratio')]
    if scores:
        paragraphs.append('투심 구성별 점수: ' + ' / '.join(scores) + '. 두 지표는 각각의 평활 원자료 백분위를 역산합니다. 평균만으로 구성별 차이가 사라지지 않습니다.')
    paragraphs.append('OI는 아직 청산되지 않은 계약 잔량, 거래량은 기준일 거래된 계약 수입니다. 두 수량은 투자자의 의도·방향 또는 실제 헤지수요를 식별하지 못합니다.')
    paragraphs.extend(_fmt_opt(f) for f in opt_facts)
    paragraphs.append('활용 순서: 기준일과 실제 보유 종목의 최신 시세를 확인하고, 공포탐욕지수의 사용 구성과 개별 점수를 함께 비교하세요. 옵션 관측은 시장 맥락을 보충합니다. 개별 기업 실적·공시·보유비중과 투자기간은 이 리포트 밖에서 확인해야 합니다. 연구 패널의 관찰가격은 목표가가 아니며 개인 손실예산 계산은 실제 체결을 보장하지 않습니다.')
    body = '</p><p>'.join(_html.escape(p).replace('\n', '<br/>') for p in paragraphs)
    return f"""
    <div class="section-block">
      <h2>종합 상태 — 판단용 맥락</h2>
      <div class="info-banner">기준일 {as_of.isoformat()} 마감 관측값의 결정론적 요약입니다. 실시간 시세가 아니며 연구 모형은 각 탭의 접힌 패널에서 확인할 수 있습니다.</div>
      <div class="beginner-note" style="font-size:14px;line-height:1.85"><p>{body}</p></div>
    </div>
    """
