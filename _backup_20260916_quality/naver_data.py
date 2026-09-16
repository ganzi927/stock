"""네이버 금융에서 지수/종목 일별 시세를 무료로 스크래핑하는 모듈.

data.krx.co.kr는 최근 로그인 없이는 접근할 수 없게 막혀서(KRX_ID/KRX_PW 필요),
로그인 없이 공개적으로 접근 가능한 네이버 금융 페이지를 데이터 소스로 사용한다.
"""

from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
ROWS_PER_PAGE = 6  # 네이버 지수/종목 일별시세 페이지 1페이지당 실제 데이터 행 수


def _fetch_page(url: str, page: int) -> pd.DataFrame:
    resp = requests.get(f"{url}&page={page}", headers=HEADERS, timeout=10)
    resp.encoding = "euc-kr"
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0].dropna()
    return df


def fetch_index_history(code: str, num_days: int, sleep_sec: float = 0.15) -> pd.DataFrame:
    """네이버 금융 지수 일별시세. code 예: KOSPI, KPI200"""
    url = f"https://finance.naver.com/sise/sise_index_day.naver?code={code}"
    return _fetch_history(url, num_days, sleep_sec, kind="index")


def fetch_item_history(code: str, num_days: int, sleep_sec: float = 0.15) -> pd.DataFrame:
    """네이버 금융 개별종목/ETF 일별시세. code 예: 114260 (KODEX 국고채3년)"""
    url = f"https://finance.naver.com/item/sise_day.naver?code={code}"
    return _fetch_history(url, num_days, sleep_sec, kind="item")


def _fetch_history(url: str, num_days: int, sleep_sec: float, kind: str) -> pd.DataFrame:
    pages = max(1, -(-num_days // ROWS_PER_PAGE)) + 1  # 올림 + 여유 1페이지
    frames = []
    for page in range(1, pages + 1):
        df = _fetch_page(url, page)
        if df.empty:
            break
        frames.append(df)
        time.sleep(sleep_sec)

    raw = pd.concat(frames, ignore_index=True)
    raw.columns = [c.strip() for c in raw.columns]

    if kind == "index":
        date_col, close_col, volume_col = raw.columns[0], raw.columns[1], raw.columns[4]
    else:  # item: 날짜,종가,전일비,시가,고가,저가,거래량
        date_col, close_col, volume_col = raw.columns[0], raw.columns[1], raw.columns[6]

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(raw[date_col], format="%Y.%m.%d"),
            "close": pd.to_numeric(raw[close_col], errors="coerce"),
            "volume": pd.to_numeric(raw[volume_col], errors="coerce"),
        }
    ).dropna(subset=["date", "close"])

    out = out.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    return out.tail(num_days).reset_index(drop=True)


def update_cache(cache_path: Path, fetch_fn, code: str, min_days: int = 300) -> pd.DataFrame:
    """로컬 CSV 캐시를 읽고, 없거나 오래됐으면 새로 받아서 병합 후 저장.

    네이버 지수/종목 페이지는 "오늘" 행이 장중에는 계속 바뀌는 실시간 스냅샷이라(마감가가
    아님), 캐시에 오늘 날짜가 이미 있다고 재조회를 건너뛰면 그날 처음 실행했을 때의 장중
    값이 마감 후에도 그대로 남는다. 그래서 최근 구간은 캐시 존재 여부와 무관하게 항상
    다시 받아서, 겹치는 날짜는 새로 받은 값으로 덮어쓴다."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"])
    else:
        cached = pd.DataFrame(columns=["date", "close", "volume"])

    needs_full_backfill = len(cached) < min_days
    fresh = fetch_fn(code, min_days + 30) if needs_full_backfill else fetch_fn(code, 30)

    # fresh를 먼저 둬서 겹치는 날짜는 fresh 값이 우선하도록 한다 (keep="first").
    parts = [df for df in (fresh, cached) if not df.empty]
    merged = (
        pd.concat(parts, ignore_index=True)
        .drop_duplicates(subset="date", keep="first")
        .sort_values("date")
        .reset_index(drop=True)
    )
    merged.to_csv(cache_path, index=False)
    return merged
