"""One-shot deep backfill for Phase 0 of WORKPLAN.md.

Extends cache/vkospi.csv and cache/putcall.csv back to START (default 2016-01-01)
using KRX Open API, and cache/credit_spread.csv + cache/bond10y_yield.csv from ECOS.

Run once:  venv\\Scripts\\python.exe _backfill_sentiment.py
Safe to re-run (incremental; only fetches missing dates).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE_DIR = Path(__file__).parent
CACHE = BASE_DIR / "cache"
START = "2016-01-01"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _load_env() -> None:
    for line in (BASE_DIR / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


KRX_BASE = "https://data-dbg.krx.co.kr/svc/apis"


def _krx(path: str, bas_dd: str) -> list[dict]:
    key = os.environ["KRX_API_KEY"]
    r = requests.get(f"{KRX_BASE}/{path}", headers={"AUTH_KEY": key}, params={"basDd": bas_dd}, timeout=25)
    try:
        return r.json().get("OutBlock_1", []) or []
    except Exception:
        return []


def _vkospi_from_rows(rows: list[dict]) -> float | None:
    for row in rows:
        if "변동성지수" in row.get("IDX_NM", ""):
            try:
                return float(row["CLSPRC_IDX"])
            except (ValueError, KeyError, TypeError):
                return None
    return None


def _putcall_from_rows(rows: list[dict]) -> float | None:
    k = [r for r in rows if r.get("PROD_NM") == "코스피200 옵션"]
    if not k:
        return None
    call = sum(int(r["ACC_TRDVOL"]) for r in k if r["RGHT_TP_NM"] == "CALL" and r["ACC_TRDVOL"])
    put = sum(int(r["ACC_TRDVOL"]) for r in k if r["RGHT_TP_NM"] == "PUT" and r["ACC_TRDVOL"])
    return (put / call) if call else None


def backfill_krx() -> None:
    vk_path, pc_path = CACHE / "vkospi.csv", CACHE / "putcall.csv"
    vk = pd.read_csv(vk_path, parse_dates=["date"]) if vk_path.exists() else pd.DataFrame(columns=["date", "vkospi"])
    pc = pd.read_csv(pc_path, parse_dates=["date"]) if pc_path.exists() else pd.DataFrame(columns=["date", "putcall"])
    have_vk = set(vk["date"]) if not vk.empty else set()
    have_pc = set(pc["date"]) if not pc.empty else set()

    days = pd.bdate_range(START, pd.Timestamp.today())
    missing = [d for d in days if d not in have_vk or d not in have_pc]
    print(f"KRX backfill: {len(missing)} business days to fetch ({days.min().date()}..{days.max().date()})", flush=True)

    new_vk, new_pc, done = [], [], 0
    for d in missing:
        bas = d.strftime("%Y%m%d")
        if d not in have_vk:
            v = _vkospi_from_rows(_krx("idx/drvprod_dd_trd", bas))
            if v is not None:
                new_vk.append({"date": d, "vkospi": v})
            time.sleep(0.15)
        if d not in have_pc:
            p = _putcall_from_rows(_krx("drv/opt_bydd_trd", bas))
            if p is not None:
                new_pc.append({"date": d, "putcall": p})
            time.sleep(0.15)
        done += 1
        if done % 100 == 0:
            print(f"  ...{done}/{len(missing)}  (vk+{len(new_vk)} pc+{len(new_pc)})", flush=True)
            _flush(vk, new_vk, "vkospi", vk_path)
            _flush(pc, new_pc, "putcall", pc_path)

    _flush(vk, new_vk, "vkospi", vk_path)
    _flush(pc, new_pc, "putcall", pc_path)
    print(f"KRX done: vkospi +{len(new_vk)}, putcall +{len(new_pc)}", flush=True)


def _flush(base: pd.DataFrame, new_rows: list[dict], col: str, path: Path) -> None:
    if not new_rows:
        return
    out = pd.concat([base, pd.DataFrame(new_rows)], ignore_index=True)
    out = out.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    out.to_csv(path, index=False)


def _ecos_series(item: str, start: str, end: str) -> pd.DataFrame:
    key = os.environ["ECOS_API_KEY"]
    url = f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/100000/817Y002/D/{start}/{end}/{item}"
    rows = requests.get(url, timeout=30).json().get("StatisticSearch", {}).get("row", [])
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "date": pd.to_datetime(df["TIME"], format="%Y%m%d"),
        "value": pd.to_numeric(df["DATA_VALUE"], errors="coerce"),
    }).dropna()


def backfill_ecos() -> None:
    start, end = START.replace("-", ""), pd.Timestamp.today().strftime("%Y%m%d")
    bbb = _ecos_series("010320000", start, end)   # 회사채 BBB- 3Y
    aa = _ecos_series("010300000", start, end)    # 회사채 AA- 3Y
    a = _ecos_series("010310000", start, end)     # 회사채 A- 3Y (대안 leg, 민감도용)
    ktb10 = _ecos_series("010210000", start, end)  # 국고채 10Y

    cs = bbb.merge(aa, on="date", suffixes=("_bbb", "_aa")).merge(
        a.rename(columns={"value": "value_a"}), on="date", how="left"
    )
    cs["spread"] = cs["value_bbb"] - cs["value_aa"]
    cs["spread_a"] = cs["value_bbb"] - cs["value_a"]
    cs[["date", "spread", "spread_a"]].to_csv(CACHE / "credit_spread.csv", index=False)
    print(f"ECOS credit_spread: {len(cs)} rows {cs.date.min().date()}..{cs.date.max().date()}", flush=True)

    ktb10 = ktb10.rename(columns={"value": "ktb10_yield"})
    ktb10.to_csv(CACHE / "bond10y_yield.csv", index=False)
    print(f"ECOS bond10y_yield: {len(ktb10)} rows {ktb10.date.min().date()}..{ktb10.date.max().date()}", flush=True)


if __name__ == "__main__":
    _load_env()
    backfill_ecos()   # fast (2 bulk calls)
    backfill_krx()    # slow (~2600 days)
    print("ALL DONE", flush=True)
