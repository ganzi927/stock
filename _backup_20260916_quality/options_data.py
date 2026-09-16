"""KOSPI200 옵션 체인 조회 및 파싱 (KRX Open API).

동일 종목이 "정규"/"야간" 두 세션으로 중복 출력되므로 정규만 사용한다.
종목명에서 옵션유형/행사가/잔존만기를 파싱한다.
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta

import pandas as pd
import requests

from krx_api import BASE_URL, HEADERS_KEY

REGULAR_PROD = "코스피200 옵션"
WEEKLY_THU_PROD = "코스피200 위클리(목) 옵션"
FUTURES_PROD = "코스피200 선물"
RATE_FUTURES_PROD = "3개월무위험금리 선물"

_FUTURES_RE = re.compile(r"코스피200\s+F\s+(\d{4})(\d{2})\s+\((주간)\)")
_RATE_FUTURES_RE = re.compile(r"3개월무위험금리\s+F\s+(\d{4})(\d{2})")

_REGULAR_RE = re.compile(r"코스피200\s+([CP])\s+(\d{4})(\d{2})\s+([\d,]+(?:\.\d+)?)\s+\((정규)\)")
_WEEKLY_RE = re.compile(r"코스피위클리\s+([CP])\s+(\d{2})(\d{2})W(\d)\s+([\d,]+(?:\.\d+)?)\s+\((정규)\)")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """해당 연/월의 n번째 요일(0=월 ... 3=목)."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d += timedelta(days=offset + 7 * (n - 1))
    return d


def _parse_regular(isu_nm: str) -> tuple[str, float, date] | None:
    m = _REGULAR_RE.search(isu_nm)
    if not m:
        return None
    opt_type, yyyy, mm, strike = m.group(1), int(m.group(2)), int(m.group(3)), float(m.group(4).replace(",", ""))
    expiry = _nth_weekday(yyyy, mm, weekday=3, n=2)  # 지수옵션 표준: 해당월 2번째 목요일
    return opt_type, strike, expiry


def _parse_weekly(isu_nm: str) -> tuple[str, float, date] | None:
    m = _WEEKLY_RE.search(isu_nm)
    if not m:
        return None
    opt_type, yy, mm, week_n, strike = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), float(m.group(5).replace(",", ""))
    year = 2000 + yy
    expiry = _nth_weekday(year, mm, weekday=3, n=week_n)  # 해당월 n번째 목요일
    return opt_type, strike, expiry


PARSERS = {REGULAR_PROD: _parse_regular, WEEKLY_THU_PROD: _parse_weekly}


def fetch_option_chain(bas_dd: str, prod_nm: str) -> pd.DataFrame:
    """지정 상품/기준일의 정규세션 옵션 체인. 컬럼: type(C/P), strike, expiry, iv, oi, volume, close, prev_settle."""
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return pd.DataFrame()

    resp = requests.get(
        f"{BASE_URL}/drv/opt_bydd_trd",
        headers={HEADERS_KEY: api_key},
        params={"basDd": bas_dd},
        timeout=20,
    )
    data = resp.json().get("OutBlock_1", [])
    rows = [r for r in data if r["PROD_NM"] == prod_nm and "(정규)" in r["ISU_NM"]]
    if not rows:
        return pd.DataFrame()

    parser = PARSERS[prod_nm]
    parsed = []
    for r in rows:
        p = parser(r["ISU_NM"])
        if p is None:
            continue
        opt_type, strike, expiry = p
        parsed.append(
            {
                "type": opt_type,
                "strike": strike,
                "expiry": expiry,
                "iv": float(r["IMP_VOLT"]) if r["IMP_VOLT"] else None,
                "oi": int(r["ACC_OPNINT_QTY"] or 0),
                "volume": int(r["ACC_TRDVOL"] or 0),
                "close": float(r["TDD_CLSPRC"]) if r["TDD_CLSPRC"] else None,
                "next_settle": float(r["NXTDD_BAS_PRC"]) if r["NXTDD_BAS_PRC"] else None,
            }
        )

    df = pd.DataFrame(parsed)
    if df.empty:
        return df
    # 여러 만기가 섞여 있으면(정규월물 다음달물 포함 등) 가장 가까운 만기만 사용.
    # 단 기준일 당일(T-0) 만기이거나 이미 만료된 시리즈는 IV·그릭스가 붕괴하므로
    # 제외하고 그 다음 만기를 쓴다 — 위클리는 목요일이 만기라 목요일에 돌리면 T-0
    # 시리즈를 잡던 버그가 있었다 (RECONCILIATION.md O2).
    as_of = date(int(bas_dd[:4]), int(bas_dd[4:6]), int(bas_dd[6:8]))
    future = df[df["expiry"] > as_of]
    if future.empty:
        return df.iloc[:0].copy()
    df = future
    nearest_expiry = df["expiry"].min()
    df = df[df["expiry"] == nearest_expiry].reset_index(drop=True)
    return df


def _fetch_opt_bydd(bas_dd: str) -> list[dict]:
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return []
    resp = requests.get(
        f"{BASE_URL}/drv/opt_bydd_trd", headers={HEADERS_KEY: api_key}, params={"basDd": bas_dd}, timeout=20
    )
    return resp.json().get("OutBlock_1", [])


def _fetch_fut_bydd(bas_dd: str) -> list[dict]:
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return []
    resp = requests.get(
        f"{BASE_URL}/drv/fut_bydd_trd", headers={HEADERS_KEY: api_key}, params={"basDd": bas_dd}, timeout=20
    )
    return resp.json().get("OutBlock_1", [])


def fetch_kospi200_futures(bas_dd: str) -> pd.DataFrame:
    """코스피200 선물 주간(정규)세션. 컬럼: expiry, price, oi, volume."""
    data = _fetch_fut_bydd(bas_dd)
    rows = [r for r in data if r["PROD_NM"] == FUTURES_PROD]
    parsed = []
    for r in rows:
        m = _FUTURES_RE.search(r["ISU_NM"])
        if not m:
            continue
        yyyy, mm = int(m.group(1)), int(m.group(2))
        expiry = _nth_weekday(yyyy, mm, weekday=3, n=2)
        price_str = r["TDD_CLSPRC"] or r["SETL_PRC"]
        if not price_str:
            continue
        parsed.append(
            {
                "expiry": expiry,
                "price": float(price_str),
                "oi": int(r["ACC_OPNINT_QTY"] or 0),
                "volume": int(r["ACC_TRDVOL"] or 0),
            }
        )
    return pd.DataFrame(parsed)


def fetch_kospi200_spot(bas_dd: str) -> float | None:
    """KOSPI200 지수 종가를 KRX 선물 응답의 SPOT_PRC에서 읽는다 (WORKPLAN2 A1).
    선물 가격과 **같은 스냅샷**이라, 네이버 지수종가를 spot으로 쓸 때 생기던 basis
    (→ 내재 q) 오염이 사라진다. 실패 시 None → 호출측이 네이버 값으로 폴백."""
    data = _fetch_fut_bydd(bas_dd)
    for r in data:
        if r.get("PROD_NM") == FUTURES_PROD and r.get("SPOT_PRC"):
            try:
                v = float(r["SPOT_PRC"])
                if v > 0:
                    return v
            except ValueError:
                pass
    return None


def fetch_risk_free_rate(bas_dd: str) -> float | None:
    """3개월무위험금리 선물의 SPOT_PRC(=100-금리)로 시장 내재 무위험이자율 추정. 실패 시 None."""
    data = _fetch_fut_bydd(bas_dd)
    rows = [r for r in data if r["PROD_NM"] == RATE_FUTURES_PROD and r.get("SPOT_PRC")]
    if not rows:
        return None
    # 최근월물(만기가 가장 가까운 것) 사용
    def _month_key(r):
        m = _RATE_FUTURES_RE.search(r["ISU_NM"])
        return (int(m.group(1)), int(m.group(2))) if m else (9999, 99)

    nearest = min(rows, key=_month_key)
    try:
        spot_prc = float(nearest["SPOT_PRC"])
    except ValueError:
        return None
    rate = (100 - spot_prc) / 100
    if not (0 < rate < 0.15):  # 비정상 값 방어 (0~15% 범위 밖이면 사용 안 함)
        return None
    return rate
