"""한국은행 ECOS Open API에서 금리 데이터를 가져오는 모듈 (선택 사항).

ECOS API 키는 https://ecos.bok.or.kr 에서 무료로 즉시 발급받을 수 있다.
환경변수 ECOS_API_KEY 가 없으면 신용스프레드 지표는 계산하지 않고 N/A 처리한다.

Credit Spread = CNN Fear & Greed의 "Junk Bond Demand"에 대응. CNN은 하이일드(정크)채와
투자등급채의 '수익률 스프레드'를 본다(정부채가 아니라 IG 대비). fmkorea도 같은 개념으로
**회사채(BBB-, 3년) − 회사채(AA-, 3년)** 을 쓴다 (fmkorea 로그의 raw ≈ 5.81 이 ECOS
010320000 − 010300000 과 소수 3자리까지 일치함을 확인 — RECONCILIATION.md §5).

과거 이 파일이 썼던 것들:
- 722Y001/0102000/0101000 → "예금은행 수신금리 − 기준금리" (완전 무관, 음수 스프레드 버그)
- 817Y002/010300000−010200000 → "AA- − 국고채" (= 0.69%p, IG−정부채라 CNN 정의와 다름)
"""

from __future__ import annotations

import os

import pandas as pd
import requests

STAT_CODE = "817Y002"          # 시장금리 (일별)
JUNK_BOND_ITEM = "010320000"   # 회사채(3년, BBB-) — 정크 근사
IG_BOND_ITEM = "010300000"     # 회사채(3년, AA-) — 투자등급
GOV_BOND_ITEM = "010200000"    # 국고채(3년) — 참고용


def _fetch_series(api_key: str, item_code: str, start: str, end: str) -> pd.DataFrame:
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/10000/"
        f"{STAT_CODE}/D/{start}/{end}/{item_code}"
    )
    resp = requests.get(url, timeout=15)
    data = resp.json()
    rows = data.get("StatisticSearch", {}).get("row", [])
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.DataFrame(rows)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["TIME"], format="%Y%m%d"),
            "value": pd.to_numeric(df["DATA_VALUE"], errors="coerce"),
        }
    )


def fetch_credit_spread(num_days: int = 520) -> pd.DataFrame | None:
    """정크(BBB-,3년) − 투자등급(AA-,3년) 회사채 수익률 스프레드. API 키 없으면 None.

    스프레드가 좁을수록(정크 수요 강함) 위험선호 = 탐욕, 넓을수록 공포.
    점수화(invert)는 indicators.compute_credit_spread 가 담당.
    """
    api_key = os.getenv("ECOS_API_KEY")
    if not api_key:
        return None

    end = pd.Timestamp.today()
    start = end - pd.Timedelta(days=int(num_days * 1.6))  # 휴일 감안 여유

    junk = _fetch_series(api_key, JUNK_BOND_ITEM, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    ig = _fetch_series(api_key, IG_BOND_ITEM, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if junk.empty or ig.empty:
        return None

    merged = pd.merge(junk, ig, on="date", suffixes=("_junk", "_ig"))
    merged["spread"] = merged["value_junk"] - merged["value_ig"]
    return merged[["date", "spread"]].tail(num_days).reset_index(drop=True)
