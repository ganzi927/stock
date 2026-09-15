"""매일 실행: KOSPI200 옵션(정규월물 + 위클리) 딜러 포지셔닝 리포트 생성.

사용법:
    python options_main.py   # reports/options-YYYY-MM-DD.html 생성
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from ai_commentary import build_options_prompt, generate_commentary
from dealer_positioning import analyze, build_scenarios, count_sign_overrides_used, implied_dividend_yield, positioning_skew, risk_reversal_25d, synthetic_forward_by_strike
from greeks import DIVIDEND_YIELD, RISK_FREE_RATE, probability_of_touch
from indicators import _rolling_percentile_score
from investor_flow import load_investor_flow
from main import _load_dotenv
from naver_data import fetch_index_history, update_cache
from options_data import REGULAR_PROD, WEEKLY_THU_PROD, fetch_kospi200_futures, fetch_kospi200_spot, fetch_option_chain, fetch_risk_free_rate
from options_report import build_html, build_section_html
from outlook import section_facts

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
REPORTS_DIR = BASE_DIR / "reports"


def _update_iv_rank_cache(cache_path: Path, as_of: date, atm_iv: float) -> float | None:
    if cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["date"])
    else:
        df = pd.DataFrame(columns=["date", "atm_iv"])

    today_ts = pd.Timestamp(as_of)
    df = df[df["date"] != today_ts]
    new_row = pd.DataFrame([{"date": today_ts, "atm_iv": atm_iv}])
    df = pd.concat([d for d in (df, new_row) if not d.empty], ignore_index=True)
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(cache_path, index=False)

    score = _rolling_percentile_score(df["atm_iv"])
    return float(score.iloc[-1]) if pd.notna(score.iloc[-1]) else None


def _atm_iv(chain_g: pd.DataFrame, spot: float) -> float:
    nearest_strike = chain_g.iloc[(chain_g["strike"] - spot).abs().argsort()[:1]]["strike"].iloc[0]
    atm_rows = chain_g[(chain_g["strike"] == nearest_strike) & chain_g["iv"].notna()]
    return float(atm_rows["iv"].mean())


def _resolve_rq(spot: float, as_of: date, expiry, r_market: float | None, futures: pd.DataFrame) -> tuple[float, float, bool, bool]:
    """실제 시장금리/선물가 기반 r, q 결정. 반환: (r, q, r_is_market, q_is_implied)."""
    r = r_market if r_market is not None else RISK_FREE_RATE
    r_is_market = r_market is not None

    q = DIVIDEND_YIELD
    q_is_implied = False
    if not futures.empty:
        futures = futures.copy()
        futures["diff_days"] = futures["expiry"].apply(lambda e: abs((pd.Timestamp(e) - pd.Timestamp(expiry)).days))
        nearest = futures.loc[futures["diff_days"].idxmin()]
        # 선물 만기가 옵션 만기와 10일 이내로 맞을 때만 선물내재 q를 신뢰한다. 위클리
        # 옵션에 먼 월물 선물의 배당구조를 씌우면 q가 왜곡된다(위클리는 T가 짧아 q 영향은
        # 작으므로 폴백해도 무방). 근접 시엔 배당락을 걸친 큰 연율 q도 그대로 받는다.
        if int(nearest["diff_days"]) <= 10:
            t = max((pd.Timestamp(nearest["expiry"]) - pd.Timestamp(as_of)).days, 1) / 365
            implied_q = implied_dividend_yield(spot, nearest["price"], r, t)
            if implied_q is not None:
                q = implied_q
                q_is_implied = True

    return r, q, r_is_market, q_is_implied


def build_product_section(
    prod_nm: str,
    title: str,
    bas_dd: str,
    as_of: date,
    spot: float,
    iv_cache_name: str,
    r_market: float | None,
    futures: pd.DataFrame,
    sign_overrides: dict | None = None,
    investor_flow_note: str | None = None,
    with_commentary: bool = True,
) -> tuple[str, dict] | None:
    chain = fetch_option_chain(bas_dd, prod_nm)
    if chain.empty:
        return None

    expiry = chain["expiry"].iloc[0]
    r, q, r_is_market, q_is_implied = _resolve_rq(spot, as_of, expiry, r_market, futures)

    levels, chain_g, profile, dex_prof, vanna_prof = analyze(chain, spot, as_of, r=r, q=q, sign_overrides=sign_overrides)
    scenarios = build_scenarios(levels)

    net_dex = float(chain_g["dex"].sum())
    net_vex = float(chain_g["vex"].sum())
    net_charm = float(chain_g["charm_exp"].sum())

    atm_iv = _atm_iv(chain_g, spot)
    iv_rank = _update_iv_rank_cache(CACHE_DIR / iv_cache_name, as_of, atm_iv)

    days_left = (expiry - as_of).days
    r_note = f"r={r*100:.2f}%{'(시장)' if r_is_market else '(가정)'}"
    q_note = f"q={q*100:.2f}%{'(선물내재)' if q_is_implied else '(가정)'}"
    # 옵션 EOD 데이터는 지수 시세보다 늦게 게시될 수 있어(_resolve_latest_available_day),
    # 페이지 상단의 "오늘" 날짜와 다를 수 있다 — 혼동 방지를 위해 기준일을 명시한다.
    expiry_label = f"기준일 {as_of.isoformat()} · 만기 {expiry.isoformat()} (T-{days_left}) · {r_note} · {q_note}"

    n_overridden = count_sign_overrides_used(chain, sign_overrides)
    n_total = chain["strike"].nunique() * 2
    override_note = (
        f"행사가 {n_overridden}/{n_total}개는 KB증권 실제 '금융투자' 순매수 부호 반영, 나머지는 업계 표준 가정"
        if n_overridden > 0
        else None
    )

    t_years = max(days_left, 1) / 365
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

    commentary = None
    if with_commentary:
        commentary = generate_commentary(
            build_options_prompt(
                title, spot, levels, net_dex, net_vex, net_charm, scenarios,
                pot=pot, risk_reversal=risk_reversal, investor_flow_note=investor_flow_note,
                positioning_skew=skew,
            )
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
        commentary=commentary,
        iv_rank=iv_rank,
        override_note=override_note,
        dex_profile=dex_prof,
        vanna_profile=vanna_prof,
        pot=pot,
        risk_reversal=risk_reversal,
        synth_df=synth_df,
        positioning_skew=skew,
    )
    facts = section_facts(title, expiry_label, spot, levels, scenarios, net_dex, net_vex, net_charm, risk_reversal, skew, pot)
    return html, facts


def _build_investor_flow_note() -> str | None:
    """KB증권 uploads/ 파일이 있으면 투자자별 콜/풋 순매수를 AI 코멘트용 사실 문장으로
    요약한다. GEX/DEX 계산에는 안 쓰지만(README 참고), '오늘 실제 이랬다'는 사실은
    코멘트에서 인용할 수 있다."""
    data = load_investor_flow(BASE_DIR / "uploads")
    if data is None or data["amount"] is None:
        return None
    amount = data["amount"]
    parts = []
    for investor in ("금융투자", "개인", "외국인", "투신"):
        c, p = amount.call.get(investor), amount.put.get(investor)
        if c is not None and p is not None:
            parts.append(f"{investor} 콜 {c:+,.0f}백만원/풋 {p:+,.0f}백만원 순매수")
    if not parts:
        return None
    return f"KB증권 상장일 누적 순매수({data['updated_at']:%Y-%m-%d} 기준 파일): " + "; ".join(parts)


def _resolve_latest_available_day(kospi200: pd.DataFrame, max_lookback: int = 5) -> tuple[str, "date", float] | None:
    """옵션 EOD 데이터는 지수 시세보다 늦게 게시되는 경우가 있어, 최근 영업일부터
    거슬러 올라가며 실제 옵션 체인이 존재하는 첫 날짜를 찾는다."""
    for i in range(max_lookback):
        row = kospi200.iloc[-1 - i]
        as_of = row["date"].date()
        bas_dd = as_of.strftime("%Y%m%d")
        probe = fetch_option_chain(bas_dd, REGULAR_PROD)
        if not probe.empty:
            return bas_dd, as_of, float(row["close"])
    return None


def generate_options_sections(kospi200: pd.DataFrame | None = None) -> tuple[list[str], date | None, list[dict]]:
    """옵션 섹션 HTML 리스트 생성. 반환: (섹션 HTML 리스트, 사용된 기준일, 섹션별 facts)."""
    if kospi200 is None:
        kospi200 = update_cache(CACHE_DIR / "kospi200.csv", fetch_index_history, "KPI200", min_days=620)

    resolved = _resolve_latest_available_day(kospi200)
    if resolved is None:
        print("최근 영업일 중 옵션 데이터를 찾지 못했습니다. KRX_API_KEY 및 이용신청 상태를 확인하세요.")
        return [], None, []
    bas_dd, as_of, spot = resolved
    # A1: spot을 선물과 같은 스냅샷인 KRX SPOT_PRC로 교체(basis 오염 제거). 없으면 네이버 종가.
    krx_spot = fetch_kospi200_spot(bas_dd)
    if krx_spot is not None:
        spot = krx_spot
    r_market = fetch_risk_free_rate(bas_dd)
    futures = fetch_kospi200_futures(bas_dd)

    # KB증권 행사가별 '금융투자' 부호 반영 기능(investor_flow.build_strike_sign_overrides)은
    # 만들어봤지만 기본적으로 꺼둔다: 실제로 켜보니 정규월물 Zero Gamma가 fmkorea 원본
    # (1,046.4)과 0.3%(1,049.9)까지 근접했던 순수 업계 표준 가정 방식보다, 켠 뒤(457.4,
    # 56% 차이)가 오히려 훨씬 나빠지는 걸 확인했다 — 금융투자가 폭넓게 콜·풋 순매수
    # 상태라 Net GEX가 넓은 구간에서 양수로 쏠리면서 Zero Gamma가 스팟에서 멀리
    # 튀었기 때문. README "행사가별 실제 부호 반영" 절 참고. 필요하면 아래 None 대신
    # investor_flow.build_strike_sign_overrides(BASE_DIR / "uploads") 결과를 다시 넣으면 된다.
    investor_flow_note = _build_investor_flow_note()

    sections, facts = [], []
    for prod_nm, title, iv_cache_name, sign_overrides, flow_note in [
        (REGULAR_PROD, "코스피200 옵션 (정규월물)", "atm_iv_regular.csv", None, investor_flow_note),
        (WEEKLY_THU_PROD, "코스피200 위클리 옵션 (목요일 만기)", "atm_iv_weekly.csv", None, None),
    ]:
        res = build_product_section(prod_nm, title, bas_dd, as_of, spot, iv_cache_name, r_market, futures, sign_overrides, flow_note)
        if res:
            sections.append(res[0])
            facts.append(res[1])
        else:
            print(f"{title}: 데이터 없음 (건너뜀)")

    return sections, as_of, facts


def main() -> None:
    _load_dotenv(BASE_DIR / ".env")
    sections, as_of, _ = generate_options_sections()

    if not sections:
        print("생성할 옵션 데이터가 없습니다. KRX_API_KEY를 확인하세요.")
        return

    html = build_html(as_of, sections)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"options-{as_of.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"옵션 리포트 생성 완료: {out_path}")


if __name__ == "__main__":
    main()
