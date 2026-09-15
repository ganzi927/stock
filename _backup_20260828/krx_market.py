"""KRX Open API — 유가증권시장 전종목 일별시세 (Breadth/Strength 실제 계산용)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from krx_api import BASE_URL, HEADERS_KEY

STRENGTH_WINDOW = 252  # 52주 신고가/신저가 롤링 창
# 진짜 52주(252거래일)가 다 차야 "신고가/신저가"로 인정한다. 60일·120일 같은 짧은
# 하한은 상승장 초기에 "N일 신고가"가 "52주 신고가"로 둔갑해 정규화 기준을 왜곡시킨다
# (RECONCILIATION.md K2). KRX Open API가 전종목 일별시세를 2020년까지 제공하므로
# update_market_cache가 2.5년치를 백필해 처음부터 진짜 52주로 계산한다.
STRENGTH_MIN_PERIODS = STRENGTH_WINDOW
MIN_HISTORY_FOR_STRENGTH = STRENGTH_WINDOW  # 하위호환 별칭
# Strength 신고가/신저가 집계 대상 유니버스.
#   None  → 전체 KOSPI (CNN 정본: "NYSE 전 종목" 방식 — 거래소 전체)
#   200   → 일자별 시총 상위 200 (fmkorea "코스피200" 방식 근사)
# CNN은 거래소 전체를 쓰므로 정본은 None. 필요 시 200으로 바꾸면 fmkorea에 근접.
STRENGTH_UNIVERSE_N = None

# 전종목 캐시 백필 길이. Strength는 52주 신고가(252일)를 다시 252일 백분위로 정규화하므로
# 오늘자 값에 꽉 찬 기준을 주려면 ≥504거래일이 필요하다 — 여유를 둬 2.5년(약 620일)치.
MARKET_CACHE_DAYS = 620


_COLS = ["date", "ISU_CD", "mkt", "close", "fluc_rt", "trdval", "trdvol", "mktcap"]

# 유가증권 + 코스닥. CNN "Stock Price Breadth/Strength"가 NYSE 전체를 쓰듯, 한국 시장
# 전체 = KOSPI + KOSDAQ 다. 국내 공포탐욕지수 서비스(feargreed.co.kr 등)와 ADR 관행도
# 코스닥을 포함/별도 반영한다 — 대형주(삼성전자·SK하이닉스)가 지수를 끌어올려도 중소형주
# 80%가 하락하는 "지수 왜곡"을 잡아내려면 코스닥이 필요하기 때문 (RECONCILIATION.md §5).
# ksq_bydd_trd 는 KRX Open API에서 별도 "이용신청"이 필요하다 — 승인 안 됐으면 빈 응답이
# 오고 자동으로 KOSPI만으로 폴백한다. 한 세션에서 처음 빈 응답이면 _KOSDAQ_OK=False 로
# 표시해 이후 호출을 건너뛴다(재백필 시 1,500여 번의 헛 호출 방지).
_MARKET_ENDPOINTS = [("sto/stk_bydd_trd", "KOSPI"), ("sto/ksq_bydd_trd", "KOSDAQ")]
_KOSDAQ_OK: bool | None = None  # None=미확인, True/False=확인됨


def _fetch_one_market(path: str, mkt: str, bas_dd: str, api_key: str) -> pd.DataFrame:
    try:
        resp = requests.get(f"{BASE_URL}/{path}", headers={HEADERS_KEY: api_key}, params={"basDd": bas_dd}, timeout=20)
        data = resp.json().get("OutBlock_1", [])
    except Exception:
        data = []
    if not data:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(data)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["BAS_DD"], format="%Y%m%d"),
            "ISU_CD": df["ISU_CD"],
            "mkt": mkt,
            "close": pd.to_numeric(df["TDD_CLSPRC"], errors="coerce"),
            "fluc_rt": pd.to_numeric(df["FLUC_RT"], errors="coerce"),
            "trdval": pd.to_numeric(df["ACC_TRDVAL"], errors="coerce"),
            "trdvol": pd.to_numeric(df["ACC_TRDVOL"], errors="coerce"),
            "mktcap": pd.to_numeric(df["MKTCAP"], errors="coerce"),
        }
    )


def fetch_market_one_day(bas_dd: str) -> pd.DataFrame:
    global _KOSDAQ_OK
    api_key = os.getenv("KRX_API_KEY")
    if not api_key:
        return pd.DataFrame(columns=_COLS)
    if _KOSDAQ_OK is False:
        eps = [e for e in _MARKET_ENDPOINTS if e[1] != "KOSDAQ"]
    else:
        eps = _MARKET_ENDPOINTS
    got = {}
    for path, mkt in eps:
        df = _fetch_one_market(path, mkt, bas_dd, api_key)
        if not df.empty:
            got[mkt] = df
    # KOSPI는 왔는데 KOSDAQ이 안 왔다 = 같은 거래일 캘린더인데 빈 응답 = 미승인으로 확정
    if "KOSPI" in got and "KOSDAQ" not in got and _KOSDAQ_OK is None:
        _KOSDAQ_OK = False
    elif "KOSDAQ" in got:
        _KOSDAQ_OK = True
    return pd.concat(got.values(), ignore_index=True) if got else pd.DataFrame(columns=_COLS)


def update_market_cache(cache_path: Path, min_days: int = MARKET_CACHE_DAYS) -> pd.DataFrame:
    """전종목 시세 롱포맷 캐시. 하루 1콜씩 순차 백필/증분 갱신.

    첫 실행 때 min_days치를 KRX Open API에서 순차 백필한다(약 5~15분, 이후엔 증분).
    Strength(진짜 52주 신고가 → 다시 252일 백분위)에 ≥504일, Breadth McClellan 요약지수·
    Strength 유니버스(시총 상위 200)에 mktcap 컬럼이 필요하다.

    ※ 나중에 KRX Open API에서 "코스닥 일별매매정보" 이용신청을 승인받았다면, 기존 캐시는
      KOSPI만 담겨 있으므로 `cache/market_kospi.csv` 를 한 번 지우고 재실행해야 코스닥이
      합쳐진다 (스키마는 그대로라 자동 재수집은 안 걸림).
    """
    if not os.getenv("KRX_API_KEY"):
        return pd.DataFrame(columns=_COLS)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"], dtype={"ISU_CD": str})
    else:
        cached = pd.DataFrame(columns=_COLS)

    # 구 스키마(trdvol/mktcap 없음)면 전체 재수집. mkt 컬럼은 없으면 KOSPI로 채운다
    # (코스닥 API 미승인 상태에서 만든 캐시 → 재수집 불필요, 컬럼만 보강).
    if not cached.empty and "mkt" not in cached.columns:
        cached["mkt"] = "KOSPI"
    if not cached.empty and any(c not in cached.columns or cached[c].isna().all() for c in ("trdvol", "mktcap")):
        cached = pd.DataFrame(columns=_COLS)

    all_days = pd.bdate_range(end=pd.Timestamp.today(), periods=min_days)
    have = set(cached["date"]) if not cached.empty else set()
    missing = [d for d in all_days if d not in have]

    frames = [cached] if not cached.empty else []
    for d in missing:
        day_df = fetch_market_one_day(d.strftime("%Y%m%d"))
        if not day_df.empty:
            frames.append(day_df)
        time.sleep(0.2)

    if not frames:
        return cached

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date", "ISU_CD"]).sort_values(["date", "ISU_CD"]).reset_index(drop=True)
    merged.to_csv(cache_path, index=False)
    return merged


def compute_breadth_and_strength_raw(market_df: pd.DataFrame) -> pd.DataFrame:
    """일자별 breadth_raw(= ratio-adjusted net advancing volume), strength_raw 계산.

    breadth_raw = (상승종목 거래량 − 하락종목 거래량) / (상승 + 하락 거래량).
    이 일별 비율을 indicators.compute_breadth_real 이 McClellan Volume Summation Index로
    누적한다 (CNN "Stock Price Breadth" = McClellan Volume Summation; fmkorea도 "상승/하락
    거래량의 19,39 지수이동평균"이라 명시 — RECONCILIATION.md §5).
    예전엔 signed 거래량/거래대금 합을 그대로 raw로 썼는데 그건 표준형이 아니었다.
    """
    if market_df.empty:
        return pd.DataFrame(columns=["date", "breadth_raw", "strength_raw"])

    vol_col = "trdvol" if "trdvol" in market_df.columns and not market_df["trdvol"].isna().all() else "trdval"
    # Breadth: 전체 KOSPI 상승/하락 거래량 (CNN·fmkorea 모두 시장 전체 기준)
    up = market_df[market_df["fluc_rt"] > 0].groupby("date")[vol_col].sum()
    down = market_df[market_df["fluc_rt"] < 0].groupby("date")[vol_col].sum()
    breadth = ((up - down) / (up + down)).rename("breadth_raw")

    # 52주 신고가/신저가는 전 종목의 전체 가격 히스토리로 계산해야 정확하다.
    wide = market_df.pivot_table(index="date", columns="ISU_CD", values="close")
    roll_max = wide.rolling(STRENGTH_WINDOW, min_periods=STRENGTH_MIN_PERIODS).max()
    roll_min = wide.rolling(STRENGTH_WINDOW, min_periods=STRENGTH_MIN_PERIODS).min()

    # Strength 유니버스 (STRENGTH_UNIVERSE_N: None=전체 KOSPI=CNN 정본, 정수=시총 상위 N).
    if STRENGTH_UNIVERSE_N and "mktcap" in market_df.columns and not market_df["mktcap"].isna().all():
        mcap = market_df.pivot_table(index="date", columns="ISU_CD", values="mktcap")
        member = mcap.rank(axis=1, ascending=False, method="first") <= STRENGTH_UNIVERSE_N
        member = member.reindex(columns=wide.columns, fill_value=False)
    else:
        member = pd.DataFrame(True, index=wide.index, columns=wide.columns)

    # 창이 안 찬 종목-일자는 신고가 판정 불가 → 집계에서 제외. 그런 종목만 있는 앞부분
    # 날짜는 strength_raw 자체가 NaN (예전엔 가짜 0이 찍혔음, RECONCILIATION.md K2).
    valid = roll_max.notna() & member
    at_high = (wide >= roll_max).where(valid).sum(axis=1)
    at_low = (wide <= roll_min).where(valid).sum(axis=1)
    total = valid.sum(axis=1).astype(float)
    total[total == 0] = np.nan
    strength_raw = ((at_high - at_low) / total * 100).rename("strength_raw")

    out = pd.concat([breadth, strength_raw], axis=1).reset_index()
    return out
