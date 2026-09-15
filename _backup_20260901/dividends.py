"""손으로 유지하는 배당 캘린더 (WORKPLAN2 A2). 유료 피드가 없어 **공시 기반으로 연 1회
갱신**한다. 배당은 전자공시(DART)에 공개되므로 무료.

용도: 개별주식 옵션의 배당 반영 (B1). 만기 안에 배당락일이 있으면 연속 배당수익률 q 대신
이 캘린더의 주당 현금배당액으로 PV를 구해 등가 q로 환산한다.

⚠️ 아래 금액·날짜는 근사치다(분기 정규배당 기준, 특별배당·변경 미반영). 정확한 값은
매년 초 각 사 배당 공시로 갱신할 것. 자사주 매입은 옵션 q에 들어가지 않으므로 제외.
지수(KOSPI200)는 바스켓 배당액을 무료로 못 구해 선물 내재 q(_resolve_rq)를 그대로 쓴다 —
여기 넣지 않는다.
"""

from __future__ import annotations

from datetime import date

# 종목명 -> [(배당락일, 주당 현금배당액 원), ...]  (해당 분기 배당락 직전일 근사)
STOCK_DIVIDENDS: dict[str, list[tuple[date, float]]] = {
    "삼성전자": [
        (date(2025, 3, 28), 361.0),
        (date(2025, 6, 27), 361.0),
        (date(2025, 9, 29), 361.0),
        (date(2025, 12, 29), 361.0),
        (date(2026, 3, 30), 365.0),
        (date(2026, 6, 29), 365.0),
        (date(2026, 9, 29), 365.0),
        (date(2026, 12, 29), 365.0),
        (date(2027, 3, 30), 365.0),
    ],
    "SK하이닉스": [
        (date(2025, 3, 28), 300.0),
        (date(2025, 6, 27), 300.0),
        (date(2025, 9, 29), 300.0),
        (date(2025, 12, 29), 300.0),
        (date(2026, 3, 30), 375.0),
        (date(2026, 6, 29), 375.0),
        (date(2026, 9, 29), 375.0),
        (date(2026, 12, 29), 375.0),
        (date(2027, 3, 30), 375.0),
    ],
}


def dividends_in_window(name: str, start: date, end: date) -> list[tuple[date, float]]:
    """(start, end] 구간에 배당락일이 들어오는 (배당락일, 금액) 목록. start 당일은 제외
    (이미 배당락 반영), end 당일 포함."""
    out = [(d, amt) for d, amt in STOCK_DIVIDENDS.get(name, []) if start < d <= end]
    return sorted(out)
