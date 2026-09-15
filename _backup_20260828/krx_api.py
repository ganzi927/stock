"""KRX Open API (openapi.krx.co.kr) 연동 — VKOSPI, 옵션 풋콜비율.

무료 회원가입 + API별 "이용신청"(즉시 자동승인됨)이 필요하다. 자세한 방법은 README 참고.

주의: 문서 페이지의 "샘플 테스트"는 `openapi.krx.co.kr/svc/sample/apis/...` 라는
별도의 샘플 전용 엔드포인트를 호출하며 거기서는 KRX가 제공하는 공용 데모키만 통한다.
실제 발급받은 내 인증키는 운영 엔드포인트인 `data-dbg.krx.co.kr/svc/apis/...` 에 써야 한다.
(둘을 헷갈리면 내 키가 "Unauthorized"로 보여서 잘못된 키인 줄 착각하기 쉽다.)
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
HEADERS_KEY = "AUTH_KEY"


def _get(path: str, bas_dd: str) -> dict:
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return {}
    resp = requests.get(
        f"{BASE_URL}/{path}",
        headers={HEADERS_KEY: api_key},
        params={"basDd": bas_dd},
        timeout=15,
    )
    data = resp.json()
    return data if "OutBlock_1" in data else {}


def fetch_vkospi_one_day(bas_dd: str) -> float | None:
    """코스피200 변동성지수(VKOSPI) 종가. 휴장일이면 None."""
    data = _get("idx/drvprod_dd_trd", bas_dd)
    for row in data.get("OutBlock_1", []):
        if "변동성지수" in row["IDX_NM"]:
            try:
                return float(row["CLSPRC_IDX"])
            except ValueError:
                return None
    return None


def fetch_kospi200_option_putcall_one_day(bas_dd: str) -> float | None:
    """코스피200 옵션(정규) 거래량 기준 Put/Call Ratio = PUT거래량 / CALL거래량."""
    data = _get("drv/opt_bydd_trd", bas_dd)
    rows = [r for r in data.get("OutBlock_1", []) if r["PROD_NM"] == "코스피200 옵션"]
    if not rows:
        return None
    call_vol = sum(int(r["ACC_TRDVOL"]) for r in rows if r["RGHT_TP_NM"] == "CALL")
    put_vol = sum(int(r["ACC_TRDVOL"]) for r in rows if r["RGHT_TP_NM"] == "PUT")
    if call_vol == 0:
        return None
    return put_vol / call_vol


def update_krx_cache(cache_path: Path, fetch_one_day_fn, value_col: str, min_days: int = 300) -> pd.DataFrame:
    """naver_data.update_cache와 같은 패턴: 하루 1콜씩 순차 백필/증분 갱신."""
    if not os.getenv("KRX_API_KEY"):
        return pd.DataFrame(columns=["date", value_col])

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"])
    else:
        cached = pd.DataFrame(columns=["date", value_col])

    all_days = pd.bdate_range(end=pd.Timestamp.today(), periods=min_days)
    have = set(cached["date"]) if not cached.empty else set()
    missing = [d for d in all_days if d not in have]

    rows = []
    for d in missing:
        bas_dd = d.strftime("%Y%m%d")
        value = fetch_one_day_fn(bas_dd)
        if value is not None:
            rows.append({"date": d, value_col: value})
        time.sleep(0.2)  # API 호출 제한 보호

    if rows:
        parts = [df for df in (cached, pd.DataFrame(rows)) if not df.empty]
        merged = pd.concat(parts, ignore_index=True)
        merged = merged.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
        merged.to_csv(cache_path, index=False)
        return merged
    return cached
