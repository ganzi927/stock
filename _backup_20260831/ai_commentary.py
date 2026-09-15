"""Claude API를 이용한 초보자용 리포트 해설 코멘트 (선택 사항).

ANTHROPIC_API_KEY 환경변수가 없거나 호출이 실패하면 조용히 건너뛴다 —
코멘트 없이 리포트가 정상적으로 나온다. 숫자를 지어내거나 투자 조언을
하지 않도록 프롬프트에서 명시적으로 제약한다: 여기서 만드는 프롬프트에는
이미 계산된 숫자만 담고, 모델이 새 숫자를 만들지 못하게 시스템 프롬프트에
못박는다.
"""

from __future__ import annotations

import os

import requests

from dealer_positioning import SIGN_CONVENTION_CAVEAT, Levels
from indicators import IndicatorResult

MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = (
    "주식 초보자에게 시장 지표를 설명하는 도우미. 사용자 메시지의 숫자·사실만 근거로 "
    "설명 — 숫자를 새로 만들거나 추측하지 말 것.\n"
    "금지: 매수·매도 추천, 방향 예측 확언('오를 것이다' 등), '외국인은 이렇게 할 것이다' "
    "식 미래 행동 예측, 투자 조언으로 읽힐 문장. 당신은 투자 자문가가 아님.\n"
    "PoT·시나리오 확률은 반드시 '위험중립 확률(옵션 가격에 내재된 값이며 실제로 그렇게 될 "
    "확률과는 리스크 프리미엄만큼 다름)'이라고 성격을 밝혀 인용할 것 — '옵션시장이 내재한 "
    "확률은 몇 %' 는 되지만 '몇 % 확률로 도달한다'는 사실 단정 금지.\n"
    "딜러 헤지 방향(매수/매도, 가속/완충)은 미국시장 기준 가정이고 한국시장에선 반대일 수 "
    "있다 — 반드시 '이 부호 가정이 맞다면' 같은 조건부로만 설명하고, 레벨의 위치 자체는 "
    "부호 가정과 무관하게 유효하다는 점을 구분해 말할 것. 실제 투자자 매매 데이터는 '오늘 "
    "실제 이랬다'로만 인용, 미래 예측 금지.\n"
    "전문용어는 짧게 풀이. 숫자 나열 대신 의미 설명. 한국어 존댓말, 5~7문장, 이모지 금지, "
    "마크다운(**, #, - 등) 금지 — 순수 텍스트만(렌더러 없이 그대로 표시됨). "
    "문장 중간에 끊기지 않게 완결된 문장으로 마무리."
)


def generate_commentary(user_content: str, max_tokens: int = 900) -> str | None:
    # 비용 하드 오프 스위치: .env 에 KFGI_AI=0 (또는 off/false) 이면 모든 LLM 호출 생략.
    if os.getenv("KFGI_AI", "1").strip().lower() in ("0", "off", "false", "no"):
        return None
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        resp = requests.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": max_tokens,
                # 한 번 실행에 5번(KFGI 1 + 코스피200 2 + 개별주식 2) 호출하는데 시스템
                # 프롬프트가 매번 동일하므로 캐싱하면 입력 토큰 비용이 크게 줄어든다
                # (캐시 적중 시 해당 부분 입력가가 정가의 10%). 5분 캐시 TTL 안에서
                # 한 실행의 호출들이 이어지므로 잘 맞는다.
                "system": [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user_content}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")
        return _strip_markdown(text.strip()) or None
    except Exception as e:
        print(f"AI 코멘트 생성 실패(건너뜀): {e}")
        return None


def _strip_markdown(text: str) -> str:
    """모델이 프롬프트 지시를 어기고 마크다운을 쓸 경우를 대비한 안전망 —
    렌더러 없이 그대로 HTML에 삽입되므로 별표/헤더 기호만 제거한다."""
    import re

    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    return text


def build_kfgi_prompt(
    total_score: float | None,
    results: list[IndicatorResult],
    sentiment_score: float | None = None,
    trend_score: float | None = None,
) -> str:
    lines = []
    if total_score is not None:
        lines.append(f"오늘 한국형 공포탐욕지수(KFGI) 총점: {total_score:.1f}점/100점 (전부 0~100, 높을수록 탐욕).")
    if sentiment_score is not None and trend_score is not None:
        lines.append(
            f"두 성격으로 나눈 값: 추세지수 {trend_score:.0f}점(Momentum·Strength·Breadth — 높으면 상승추세), "
            f"투심지수 {sentiment_score:.0f}점(Volatility·Put/Call·Credit — 이 3개는 역행 지표라 점수가 높다는 건 "
            f"변동성·풋수요·신용스프레드가 낮다 = 시장이 안심/방심하고 있다는 뜻이고, 낮으면 공포·헤지 수요가 크다는 뜻)."
        )
        lines.append(
            "과거 KOSPI에서 '추세지수 높음 + 투심지수 낮음(공포)' 조합이 이후 수익률이 가장 좋았고, "
            "'추세지수 낮음 + 투심지수 높음(방심)'이 가장 나빴다."
        )
    lines.append("세부 7개 지표:")
    for r in results:
        if r.score is None:
            continue
        proxy = " (근사치)" if r.is_proxy else ""
        lines.append(f"- {r.name}: {r.score:.1f}점{proxy} — {r.note}")
    lines.append("")
    lines.append(
        "위를 종합해 오늘 코스피 시장 상태를 초보자 눈높이로 설명해주세요. 추세지수와 투심지수가 "
        "엇갈리면 그게 무슨 의미인지, 역행 지표(변동성·풋콜·신용)의 점수 방향을 헷갈리지 말고 설명하세요."
    )
    return "\n".join(lines)


def build_options_prompt(
    title: str,
    spot: float,
    levels: Levels,
    net_dex: float,
    net_vex: float,
    net_charm: float,
    scenarios: list[dict],
    pot: dict[str, float] | None = None,
    risk_reversal: tuple[float | None, float | None, float | None] | None = None,
    investor_flow_note: str | None = None,
    positioning_skew: dict | None = None,
) -> str:
    pot = pot or {}

    def _won(v: float) -> str:
        a = abs(v)
        if a >= 1e12:
            return f"{v/1e12:+.2f}조원"
        if a >= 1e8:
            return f"{v/1e8:+.1f}억원"
        return f"{v/1e4:+.0f}만원"

    def _fmt(v: float | None, pot_key: str | None = None) -> str:
        if v is None:
            return "N/A"
        pct = (v - spot) / spot * 100
        p = pot.get(pot_key) if pot_key else None
        pot_str = f", 만기 전 터치확률(PoT) {p*100:.1f}%" if p is not None else ""
        return f"{v:,.1f} (스팟 대비 {pct:+.1f}%{pot_str})"

    zg_txt = levels.zero_gamma_band_txt or _fmt(levels.zero_gamma, "zero_gamma")
    lines = [
        f"[{title}] 현재가(Spot): {spot:,.1f}",
        f"(주의) {SIGN_CONVENTION_CAVEAT}",
        f"Call Wall(콜 옵션 미결제약정/감마가 가장 집중된 행사가 — 부호 가정이 맞다면 이 위에서 딜러 매수 헤지가 상승을 가속, 반대면 완충): {_fmt(levels.call_wall, 'call_wall')}",
        f"Put Wall(풋 옵션 미결제약정/감마가 가장 집중된 행사가 — 부호 가정이 맞다면 이 아래에서 딜러 매도 헤지가 하락을 가속, 반대면 완충): {_fmt(levels.put_wall, 'put_wall')}",
        f"Zero Gamma(합산 감마 부호가 바뀌는 경계선 — 위치는 부호 가정에 불변, 위/아래 국면 해석만 가정에 의존): {zg_txt}",
        f"MaxPain(만기일 옵션 내재가치 총합이 최소가 되는 행사가 — 수렴 경향의 통계적 근거는 약함): {_fmt(levels.max_pain, 'max_pain')}",
        f"Net DEX(딜러 델타 명목가치 — 부호는 미국식 가정 기준): {_won(net_dex)}",
        f"Net Vanna Flow(변동성 1%p 상승 시 델타 명목가치 변화 — 부호는 가정 기준): {_won(net_vex)}",
        f"Net Charm Flow(하루 경과 시 델타 명목가치 변화 — 부호는 가정 기준): {_won(net_charm)}",
    ]
    if levels.call_wall_above is not None:
        lines.append(f"상단 Gamma Wall(스팟 위 콜 감마 최대 저항): {_fmt(levels.call_wall_above)}")
    if levels.put_wall_below is not None:
        lines.append(f"하단 Gamma Wall(스팟 아래 풋 감마 최대 지지): {_fmt(levels.put_wall_below)}")
    if risk_reversal is not None and risk_reversal[2] is not None:
        call_iv, put_iv, rr = risk_reversal
        skew = "풋 프리미엄이 더 비쌈(하방 공포 우위)" if rr < 0 else "콜 프리미엄이 더 비쌈(상방 기대 우위)"
        lines.append(f"25델타 Risk Reversal(변동성 스큐): {rr:+.2f}%p (콜 IV {call_iv:.1f}% - 풋 IV {put_iv:.1f}%) — {skew}")
    if positioning_skew is not None and positioning_skew.get("oi_skew") is not None:
        oi_sk = positioning_skew["oi_skew"] * 100
        pcr = positioning_skew.get("oi_pcr")
        pcr_str = f", 풋/콜 미결제약정비율 {pcr:.2f}" if pcr is not None else ""
        tilt = "콜 포지션 우위(상방 쏠림)" if oi_sk >= 0 else "풋 포지션 우위(하방 쏠림)"
        lines.append(
            f"콜/풋 포지션 쏠림도(미결제약정 기준, 변동성 스큐와 다른 축): {oi_sk:+.1f}% — {tilt}{pcr_str}. "
            "RR(스큐)과 쏠림도가 반대로 나올 수 있으며 그건 모순이 아니라 서로 다른 것을 재는 것임."
        )
    if scenarios:
        lines.append("시나리오(PoT가 이미 각 레벨에 명시돼 있으니 그 확률을 그대로 인용하세요):")
        for sc in scenarios:
            inval = f", 무효화 레벨(이 시나리오가 깨졌을 때의 다음 구조적 레벨— 개인 손절가 아님): {sc['invalidation']}" if sc.get("invalidation") else ""
            lines.append(f"- {sc['name']}: {sc['trigger']} → {sc['target']}{inval} ({sc['note']})")
    if investor_flow_note:
        lines.append("")
        lines.append(f"실제 투자자별 매매 동향(오늘 사실, 예측 아님): {investor_flow_note}")
    lines.append("")
    lines.append(
        "위 옵션 시장 지표들이 지금 무엇을 보여주는지, 현재가가 어떤 레벨들 사이에 끼어있고 "
        "각 레벨의 PoT(위험중립 터치확률)가 몇 %인지를 초보자에게 구체적이고 직관적으로 "
        "설명해주세요. 딜러 헤지 방향은 '부호 가정이 맞다면'의 조건부로만 언급하고, PoT는 "
        "옵션 가격에 내재된 값이지 실제 도달 확률 단정이 아님을 분명히 하세요."
    )
    return "\n".join(lines)
