"""개별주식 옵션 체인 조회/파싱 (KRX Open API, 유가증권 주식옵션).

지수옵션과 달리 "(정규)/(야간)" 세션 구분이 없고, 종목명에 계약승수가 붙는다.
예: "삼성전자   C 202609    68,000(  10)" -> 콜, 만기 202609, 행사가 68,000, 승수 10.
"""

from __future__ import annotations

import os
import re
from datetime import date

import pandas as pd
import requests

from krx_api import BASE_URL, HEADERS_KEY
from options_data import _nth_weekday

STOCK_UNDERLYINGS = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
}

# 개별주식 배당수익률 가정 — **현금배당 기준**(자사주 매입은 옵션 q에 안 들어감).
# 예전엔 지수(KOSPI200)의 1.5%를 그대로 상속해 삼성 ~2배·하이닉스 ~8배 과대였다.
# 개별주식 체인이 얇아 풋콜패리티 내재 q 추정은 노이즈가 커서 종목별 상수로 둔다
# (2026 기준 근사치 — 삼성 배당수익률 ~0.8~1.0%, 하이닉스 ~0.2~0.3%).
STOCK_DIV_YIELD = {
    "삼성전자": 0.010,
    "SK하이닉스": 0.003,
}

# 월물(YYYYMM) 형식만 매칭한다. 개별주식 위클리옵션(2026-06 상장)은 만기 표기·PROD_NM이
# 달라 이 정규식에 안 걸리고, fetch_stock_option_chain 이 PROD_NM에 "위클리"가 들어간 행을
# 명시 제외한다 — 위클리 만기 로직(_nth_weekday n=2)이 다르기 때문. 통합은 별도 작업.
_STOCK_OPT_RE = re.compile(r"([CP])\s+(\d{4})(\d{2})\s+([\d,]+)\(\s*(\d+)\s*\)")


def _parse_stock_option_name(isu_nm: str) -> tuple[str, float, date, float] | None:
    m = _STOCK_OPT_RE.search(isu_nm)
    if not m:
        return None
    opt_type = m.group(1)
    yyyy, mm = int(m.group(2)), int(m.group(3))
    strike = float(m.group(4).replace(",", ""))
    multiplier = float(m.group(5))
    expiry = _nth_weekday(yyyy, mm, weekday=3, n=2)  # 개별주식옵션도 지수옵션과 동일하게 해당월 2번째 목요일
    return opt_type, strike, expiry, multiplier


def fetch_stock_option_chain(bas_dd: str, underlying_name: str) -> pd.DataFrame:
    """지정 종목의 옵션 체인. 컬럼: type, strike, expiry, multiplier, iv, oi, volume, close."""
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return pd.DataFrame()

    resp = requests.get(
        f"{BASE_URL}/drv/eqsop_bydd_trd",
        headers={HEADERS_KEY: api_key},
        params={"basDd": bas_dd},
        timeout=20,
    )
    data = resp.json().get("OutBlock_1", [])
    prod_nm = f"{underlying_name} 옵션"
    rows = [r for r in data if r.get("PROD_NM") == prod_nm and "위클리" not in r.get("ISU_NM", "")]
    if not rows:
        return pd.DataFrame()

    parsed = []
    for r in rows:
        p = _parse_stock_option_name(r["ISU_NM"])
        if p is None:
            continue
        opt_type, strike, expiry, multiplier = p
        parsed.append(
            {
                "type": opt_type,
                "strike": strike,
                "expiry": expiry,
                "multiplier": multiplier,
                "iv": float(r["IMP_VOLT"]) if r["IMP_VOLT"] else None,
                "oi": int(r["ACC_OPNINT_QTY"] or 0),
                "volume": int(r["ACC_TRDVOL"] or 0),
                "close": float(r["TDD_CLSPRC"]) if r["TDD_CLSPRC"] else None,
            }
        )

    df = pd.DataFrame(parsed)
    if df.empty:
        return df
    # 기준일 당일(T-0)/만료 시리즈는 제외하고 다음 만기 사용 (RECONCILIATION.md O2)
    as_of = date(int(bas_dd[:4]), int(bas_dd[4:6]), int(bas_dd[6:8]))
    future = df[df["expiry"] > as_of]
    if future.empty:
        return df.iloc[:0].copy()
    df = future
    nearest_expiry = df["expiry"].min()
    df = df[df["expiry"] == nearest_expiry].reset_index(drop=True)
    return df
