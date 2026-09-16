"""매일 실행: 삼성전자/SK하이닉스 개별주식 옵션 딜러 포지셔닝 리포트 생성.

사용법:
    python stock_options_main.py   # reports/stock-options-YYYY-MM-DD.html 생성

combined_main.py에서 generate_stock_options_sections()를 가져다 다른 리포트와 합친다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from ai_commentary import build_options_prompt, generate_commentary
from dealer_positioning import analyze, build_scenarios, positioning_skew, risk_reversal_25d, synthetic_forward_by_strike
from greeks import DIVIDEND_YIELD, RISK_FREE_RATE, probability_of_touch
from krx_market import fetch_market_one_day
from main import _load_dotenv
from options_data import fetch_risk_free_rate
from options_main import _atm_iv, _update_iv_rank_cache
from options_report import build_html, build_section_html
from outlook import section_facts
from dividends import dividends_in_window
from stock_options_data import STOCK_DIV_YIELD, STOCK_UNDERLYINGS, fetch_stock_option_chain

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
REPORTS_DIR = BASE_DIR / "reports"


def _resolve_stock_spot(bas_dd: str, isu_cd: str) -> float | None:
    market = fetch_market_one_day(bas_dd)
    if market.empty:
        return None
    row = market[market["ISU_CD"] == isu_cd]
    if row.empty:
        return None
    return float(row["close"].iloc[0])


def build_stock_option_section(name: str, isu_cd: str, bas_dd: str, as_of: date, r_market: float | None, iv_cache_name: str) -> tuple[str, dict] | None:
    spot = _resolve_stock_spot(bas_dd, isu_cd)
    if spot is None:
        return None

    chain = fetch_stock_option_chain(bas_dd, name)
    if chain.empty:
        return None

    multiplier = float(chain["multiplier"].iloc[0])
    r = r_market if r_market is not None else RISK_FREE_RATE
    expiry = chain["expiry"].iloc[0]
    days_left = (expiry - as_of).days
    t_years = max(days_left, 0.25) / 365

    # 배당수익률 q: 만기 안에 배당락일이 있으면 그 주당 현금배당(dividends.py)을 PV로
    # 환산해 옵션 잔존기간에 대한 **등가 연속수익률**로 쓴다(B1). 없으면 종목별 평상시
    # 상수(STOCK_DIV_YIELD). 지수의 1.5% 상속은 폐기.
    q_base = STOCK_DIV_YIELD.get(name, DIVIDEND_YIELD)
    divs = dividends_in_window(name, as_of, expiry)
    if divs:
        import math

        pv_div = sum(amt * math.exp(-r * (max((d - as_of).days, 0) / 365)) for d, amt in divs)
        q = -math.log(max(1.0 - pv_div / spot, 1e-6)) / t_years if spot > 0 else q_base
        q_note = f"q={q*100:.2f}%(만기 내 배당락 {len(divs)}건, 주당합 {sum(a for _, a in divs):,.0f}원 PV환산)"
    else:
        q = q_base
        q_note = f"q={q*100:.2f}%(종목별 평상시 가정, 현금배당)"

    levels, chain_g, profile, dex_prof, vanna_prof = analyze(chain, spot, as_of, r=r, q=q, multiplier=multiplier)
    scenarios = build_scenarios(levels)

    net_dex = float(chain_g["dex"].sum())
    net_vex = float(chain_g["vex"].sum())
    net_charm = float(chain_g["charm_exp"].sum())

    atm_iv = _atm_iv(chain_g, spot)
    iv_rank = _update_iv_rank_cache(CACHE_DIR / iv_cache_name, as_of, atm_iv)

    r_note = f"r={r*100:.2f}%{'(시장)' if r_market is not None else '(가정)'}"
    expiry_label = f"기준일 {as_of.isoformat()} · 만기 {expiry.isoformat()} (T-{days_left}) · {r_note} · {q_note}"
    sigma = atm_iv / 100
    pot = {
        key: probability_of_touch(spot, level, t_years, sigma, r=r, q=q)
        for key, level in {
            "call_wall": levels.call_wall,
            "put_wall": levels.put_wall,
            "zero_gamma": levels.zero_gamma,
            "max_pain": levels.max_pain,
        }.items()
        if level is not None
    }
    risk_reversal = risk_reversal_25d(chain_g)
    skew = positioning_skew(chain)
    synth_df = synthetic_forward_by_strike(chain, r, q, t_years)

    title = f"{name} 옵션"
    commentary = generate_commentary(
        build_options_prompt(title, spot, levels, net_dex, net_vex, net_charm, scenarios, pot=pot, risk_reversal=risk_reversal, positioning_skew=skew)
    )

    html = build_section_html(
        title=title,
        expiry_label=expiry_label,
        spot=spot,
        levels=levels,
        profile=profile,
        chain_with_greeks=chain_g,
        scenarios=scenarios,
        net_dex=net_dex,
        net_vex=net_vex,
        net_charm=net_charm,
        iv_rank=iv_rank,
        commentary=commentary,
        dex_profile=dex_prof,
        vanna_profile=vanna_prof,
        pot=pot,
        risk_reversal=risk_reversal,
        synth_df=synth_df,
        positioning_skew=skew,
    )
    facts = section_facts(title, expiry_label, spot, levels, scenarios, net_dex, net_vex, net_charm, risk_reversal, skew, pot)
    return html, facts


def generate_stock_options_sections(bas_dd: str | None = None, as_of: date | None = None) -> tuple[list[str], list[dict]]:
    _load_dotenv(BASE_DIR / ".env")
    if bas_dd is None or as_of is None:
        as_of = date.today()
        bas_dd = as_of.strftime("%Y%m%d")

    r_market = fetch_risk_free_rate(bas_dd)

    sections, facts = [], []
    for name, isu_cd in STOCK_UNDERLYINGS.items():
        iv_cache_name = f"atm_iv_{isu_cd}.csv"
        res = build_stock_option_section(name, isu_cd, bas_dd, as_of, r_market, iv_cache_name)
        if res:
            sections.append(res[0])
            facts.append(res[1])
        else:
            print(f"{name} 옵션: 데이터 없음 (건너뜀)")
    return sections, facts


def main() -> None:
    from options_main import _resolve_latest_available_day
    from naver_data import fetch_index_history, update_cache

    _load_dotenv(BASE_DIR / ".env")
    kospi200 = update_cache(CACHE_DIR / "kospi200.csv", fetch_index_history, "KPI200", min_days=620)
    resolved = _resolve_latest_available_day(kospi200)
    if resolved is None:
        print("최근 영업일 중 옵션 데이터를 찾지 못했습니다.")
        return
    bas_dd, as_of, _ = resolved

    sections, _ = generate_stock_options_sections(bas_dd, as_of)
    if not sections:
        print("생성할 옵션 데이터가 없습니다.")
        return

    html = build_html(as_of, sections)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"stock-options-{as_of.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"개별주식 옵션 리포트 생성 완료: {out_path}")


if __name__ == "__main__":
    main()
