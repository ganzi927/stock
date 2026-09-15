"""한국은행 ECOS Open API 금리 데이터 (선택 사항).

ECOS API 키는 https://ecos.bok.or.kr 에서 무료로 즉시 발급. 환경변수 ECOS_API_KEY 가
없으면 신용스프레드 지표는 N/A 처리한다.

Credit Spread = CNN "Junk Bond Demand" 대응: 하이일드(정크) − 투자등급 수익률 스프레드.
**회사채(BBB-, 3년) − 회사채(AA-, 3년)** (ECOS 817Y002, item 010320000 − 010300000).

WORKPLAN Phase 0-2: 이 파일은 이제 `cache/credit_spread.csv`(딥 백필, `_backfill_sentiment.py`가
2016년부터 생성)를 우선 읽고, 마지막 날짜가 오래됐으면 최근분만 라이브로 증분한다.
백필 파일이 없으면 예전처럼 라이브 fetch 로 폴백한다. `spread_a`(BBB- − A-)도 함께
제공한다 — 정규화 창·leg 선택 민감도 확인용.

WORKPLAN Phase 0-3: `synthetic_bond10y_index()` — 국고채 10년 금리(item 010210000)로
합성 총수익 지수를 만든다. 어린 KOSEF 10년 ETF(148070, 2025-01~) 대신 이걸 Safe Haven
지표의 채권 레그로 쓴다(히스토리 2016+).

과거 이 파일이 썼던 잘못된 코드들:
- 722Y001/0102000/0101000 → "예금은행 수신금리 − 기준금리" (완전 무관, 음수 스프레드 버그)
- 817Y002/010300000−010200000 → "AA- − 국고채" (= 0.69%p, IG−정부채라 CNN 정의와 다름)
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import requests

STAT_CODE = "817Y002"          # 시장금리 (일별)
JUNK_BOND_ITEM = "010320000"   # 회사채(3년, BBB-) — 정크 근사
IG_BOND_ITEM = "010300000"     # 회사채(3년, AA-) — 투자등급
A_BOND_ITEM = "010310000"      # 회사채(3년, A-) — 대안 leg (민감도용)
GOV_BOND_ITEM = "010200000"    # 국고채(3년) — 참고용
GOV_BOND_10Y_ITEM = "010210000"  # 국고채(10년) — Safe Haven 채권 레그

BASE_DIR = Path(__file__).parent
CACHE = BASE_DIR / "cache"
BOND10Y_DURATION = 8.5  # 국고채 10년 근사 수정듀레이션 (합성 총수익 지수용)


def _fetch_series(api_key: str, item_code: str, start: str, end: str) -> pd.DataFrame:
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/100000/"
        f"{STAT_CODE}/D/{start}/{end}/{item_code}"
    )
    try:
        rows = requests.get(url, timeout=20).json().get("StatisticSearch", {}).get("row", [])
    except Exception:
        rows = []
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "date": pd.to_datetime(df["TIME"], format="%Y%m%d"),
        "value": pd.to_numeric(df["DATA_VALUE"], errors="coerce"),
    }).dropna()


def _live_credit_spread(api_key: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    s, e = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
    bbb = _fetch_series(api_key, JUNK_BOND_ITEM, s, e)
    aa = _fetch_series(api_key, IG_BOND_ITEM, s, e)
    a = _fetch_series(api_key, A_BOND_ITEM, s, e)
    if bbb.empty or aa.empty:
        return pd.DataFrame(columns=["date", "spread", "spread_a"])
    m = bbb.merge(aa, on="date", suffixes=("_bbb", "_aa")).merge(
        a.rename(columns={"value": "value_a"}), on="date", how="left"
    )
    m["spread"] = m["value_bbb"] - m["value_aa"]
    m["spread_a"] = m["value_bbb"] - m["value_a"]
    return m[["date", "spread", "spread_a"]]


def fetch_credit_spread(num_days: int = 2000) -> pd.DataFrame | None:
    """정크(BBB-,3년) − 투자등급(AA-,3년) 회사채 수익률 스프레드. ECOS_API_KEY 없으면 None.

    우선순위: cache/credit_spread.csv(딥 백필) → 마지막 날짜가 7일 이상 오래됐으면 최근분
    라이브 증분 → 파일 없으면 전체 라이브 fetch. 스프레드가 좁을수록 위험선호 = 탐욕.
    점수화(invert)는 indicators.compute_credit_spread 담당."""
    api_key = os.getenv("ECOS_API_KEY")
    if not api_key:
        return None

    path = CACHE / "credit_spread.csv"
    today = pd.Timestamp.today().normalize()
    cached = pd.DataFrame(columns=["date", "spread", "spread_a"])
    if path.exists():
        cached = pd.read_csv(path, parse_dates=["date"])

    if cached.empty:
        got = _live_credit_spread(api_key, today - pd.Timedelta(days=int(num_days * 1.6)), today)
        if got.empty:
            return None
        merged = got
    else:
        last = cached["date"].max()
        if (today - last).days > 7:
            got = _live_credit_spread(api_key, last - pd.Timedelta(days=10), today)
            merged = pd.concat([cached, got], ignore_index=True) if not got.empty else cached
        else:
            merged = cached

    merged = merged.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    try:
        merged.to_csv(path, index=False)
    except Exception:
        pass
    return merged.tail(num_days).reset_index(drop=True)


def synthetic_bond10y_index(num_days: int = 3000) -> pd.DataFrame | None:
    """국고채 10년 금리 → 합성 총수익 지수(=100 기준 cumprod). Safe Haven 채권 레그용.

    daily_return_t ≈ y_{t-1}/252/100  (carry)  −  D·(y_t − y_{t-1})/100  (가격 변화)
    D = BOND10Y_DURATION. 컬럼: date, close(합성지수). ECOS_API_KEY 없으면 None."""
    api_key = os.getenv("ECOS_API_KEY")
    if not api_key:
        return None

    path = CACHE / "bond10y_yield.csv"
    today = pd.Timestamp.today().normalize()
    if path.exists():
        y = pd.read_csv(path, parse_dates=["date"]).rename(columns={"ktb10_yield": "y"})
        if (today - y["date"].max()).days > 7:
            got = _fetch_series(api_key, GOV_BOND_10Y_ITEM, (y["date"].max() - pd.Timedelta(days=10)).strftime("%Y%m%d"), today.strftime("%Y%m%d"))
            if not got.empty:
                y = pd.concat([y, got.rename(columns={"value": "y"})], ignore_index=True)
    else:
        got = _fetch_series(api_key, GOV_BOND_10Y_ITEM, (today - pd.Timedelta(days=int(num_days * 1.6))).strftime("%Y%m%d"), today.strftime("%Y%m%d"))
        if got.empty:
            return None
        y = got.rename(columns={"value": "y"})

    y = y.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    try:
        y.rename(columns={"y": "ktb10_yield"}).to_csv(path, index=False)
    except Exception:
        pass

    dy = y["y"].diff()
    carry = y["y"].shift(1) / 252 / 100
    daily_ret = carry - BOND10Y_DURATION * dy / 100
    daily_ret.iloc[0] = 0.0
    idx = 100.0 * (1.0 + daily_ret.fillna(0.0)).cumprod()
    return pd.DataFrame({"date": y["date"], "close": idx}).tail(num_days).reset_index(drop=True)
