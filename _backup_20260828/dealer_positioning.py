"""KOSPI200 옵션 딜러 포지셔닝 분석 (MaxPain / Zero Gamma / Call Wall·Put Wall / DEX·VEX·Charm Flow).

핵심 가정(명시적, README 참고, 웹 검색으로 교차검증됨):
- GEX/VEX(바나)/Charm 익스포저: 딜러는 콜을 순매수(long), 풋을 순매도(short)한 것으로
  가정하는 SqueezeMetrics/SpotGamma류 표준 관례를 따른다.
  즉 "Net GEX/VEX/Charm" = Σ(콜 미결제약정×그릭스) − Σ(풋 미결제약정×그릭스).
- DEX(델타 익스포저)는 GEX와 다른, 별도의 표준 관례를 따른다: 고객이 콜·풋을 모두 순매수하고
  딜러는 콜·풋을 모두 순매도(short)한다고 가정한다(FlashAlpha, MenthorQ 등에서 확인).
  즉 "Net DEX" = −Σ(전체 옵션의 OI×BS델타) — 부호가 GEX와 반대로 전체에 −1이 곱해진다.
- 그릭스는 각 종목의 실제 IV로 계산하되, 스팟이 바뀌어도 IV(변동성 스마일)는 고정한다고 가정한다
  (스마일 동학까지 반영한 2차 효과는 생략).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from greeks import CONTRACT_MULTIPLIER, DIVIDEND_YIELD, RISK_FREE_RATE, compute_greeks


def implied_dividend_yield(spot: float, forward: float, r: float, t: float, bound: float = 0.05) -> float | None:
    """F = S*e^((r-q)T) 관계에서 q 역산. 비정상적으로 크면(유동성 부족 등) None 반환."""
    if spot <= 0 or forward <= 0 or t <= 0:
        return None
    q = r - np.log(forward / spot) / t
    if abs(q) > bound:
        return None
    return float(q)


@dataclass
class Levels:
    """call_wall/put_wall 정의 출처: SpotGamma, FlashAlpha 등 다수 업계 자료가 공통으로
    쓰는 정의 — Call Wall은 콜 GEX만 따로 봤을 때 최댓값 지점, Put Wall은 풋 GEX만
    따로 봤을 때 최댓값(절대값) 지점이다. 스팟 위/아래 방향과는 무관하다.
    ("Dealer Equilibrium"은 검색해도 표준 용어로 확인되지 않아 채택하지 않았다.)"""

    spot: float
    max_pain: float | None
    dex_neutral_maxpain: float | None
    zero_gamma: float | None
    call_wall: float | None
    put_wall: float | None
    strike_min: float
    strike_max: float
    call_wall_above: float | None = None  # 스팟 위 콜 GEX 최대 (상단 Gamma Wall)
    put_wall_below: float | None = None   # 스팟 아래 |풋 GEX| 최대 (하단 Gamma Wall)

    @property
    def spot_above_range(self) -> bool:
        return self.spot > self.strike_max

    @property
    def spot_below_range(self) -> bool:
        return self.spot < self.strike_min


def _time_to_expiry(expiry: date, as_of: date) -> float:
    return max((expiry - as_of).days, 1) / 365


SignOverrides = dict[tuple[float, str], int]


def _resolve_signs(strikes: np.ndarray, types: np.ndarray, default_sign: np.ndarray, overrides: SignOverrides | None) -> np.ndarray:
    """행사가별 실제 매매동향(예: KB증권 '금융투자' 순매수 부호)이 있으면 그걸로,
    없으면 업계 표준 가정(default_sign)으로 대체한다."""
    if not overrides:
        return default_sign
    eff = default_sign.copy()
    for i in range(len(strikes)):
        key = (round(float(strikes[i]), 1), types[i])
        if key in overrides:
            eff[i] = overrides[key]
    return eff


def count_sign_overrides_used(chain: pd.DataFrame, overrides: SignOverrides | None) -> int:
    if not overrides:
        return 0
    strikes = chain["strike"].to_numpy()
    types = chain["type"].to_numpy()
    return sum(1 for s, t in zip(strikes, types) if (round(float(s), 1), t) in overrides)


def with_greeks_at_spot(
    chain: pd.DataFrame,
    spot: float,
    as_of: date,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
) -> pd.DataFrame:
    df = chain.copy()
    df["iv"] = df["iv"].fillna(df["iv"].median())
    t = _time_to_expiry(df["expiry"].iloc[0], as_of)
    g = compute_greeks(
        spot=np.full(len(df), spot),
        strike=df["strike"].to_numpy(),
        t_years=np.full(len(df), t),
        sigma=(df["iv"].to_numpy() / 100),
        is_call=(df["type"] == "C").to_numpy(),
        r=r,
        q=q,
    )
    for k, v in g.items():
        df[k] = v

    types = df["type"].to_numpy()
    strikes = df["strike"].to_numpy()
    gex_default_sign = np.where(types == "C", 1, -1)
    # DEX는 GEX와 다른 부호 규약: 고객이 콜·풋 모두 순매수 → 딜러는 콜·풋 모두 순매도 가정
    # (FlashAlpha/MenthorQ) → 딜러 델타 익스포저는 원시 BS델타 합의 부호를 전체 반전.
    dex_default_sign = np.full(len(df), -1)
    gex_sign = _resolve_signs(strikes, types, gex_default_sign, sign_overrides)
    dex_sign = _resolve_signs(strikes, types, dex_default_sign, sign_overrides)

    df["dealer_sign"] = gex_sign
    # DEX/VEX/Charm은 업계 표준 "$DEX"(FlashAlpha/MenthorQ) 규약대로 스팟을 곱해
    # 델타 명목가치(통화 단위)로 만든다 — 그래야 승수가 작은 개별주식 옵션에서도
    # 0.0으로 반올림되지 않고 지수옵션과 규모가 비교 가능해진다 (RECONCILIATION.md O3).
    df["dex"] = dex_sign * df["oi"] * df["delta"] * multiplier * spot
    df["gex"] = gex_sign * df["oi"] * df["gamma"] * spot**2 * 0.01 * multiplier
    df["vex"] = gex_sign * df["oi"] * df["vanna"] * multiplier * spot
    df["charm_exp"] = gex_sign * df["oi"] * df["charm"] * multiplier * spot
    return df


def gex_profile(
    chain: pd.DataFrame,
    as_of: date,
    spot_grid: np.ndarray,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
) -> pd.Series:
    t = _time_to_expiry(chain["expiry"].iloc[0], as_of)
    iv = chain["iv"].fillna(chain["iv"].median()).to_numpy() / 100
    strike = chain["strike"].to_numpy()
    is_call = (chain["type"] == "C").to_numpy()
    types = chain["type"].to_numpy()
    oi = chain["oi"].to_numpy()
    sign = _resolve_signs(strike, types, np.where(is_call, 1, -1), sign_overrides)

    net_gex = []
    for s in spot_grid:
        g = compute_greeks(
            spot=np.full(len(chain), s),
            strike=strike,
            t_years=np.full(len(chain), t),
            sigma=iv,
            is_call=is_call,
            r=r,
            q=q,
        )
        gex = sign * oi * g["gamma"] * s**2 * 0.01 * multiplier
        net_gex.append(gex.sum())
    return pd.Series(net_gex, index=spot_grid)


def _interp_zero_cross(profile: pd.Series, near: float | None = None) -> float | None:
    """0을 가로지르는 지점을 선형보간으로 추정.

    행사가 범위가 스팟 대비 매우 넓으면(개별주식 옵션 등) 실제 OI가 없는 극단
    구간에서 수치적으로 의미없는 크로스가 생길 수 있어, near(보통 스팟)가 주어지면
    그 지점에 가장 가까운 크로스를 반환한다."""
    xs, ys = profile.index.to_numpy(), profile.to_numpy()
    signs = np.sign(ys)
    crossings = []
    for i in range(len(ys) - 1):
        if signs[i] != 0 and signs[i + 1] != 0 and signs[i] != signs[i + 1]:
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
            crossings.append(float(x0 + (0 - y0) * (x1 - x0) / (y1 - y0)))
    if not crossings:
        return None
    if near is None:
        return crossings[0]
    return min(crossings, key=lambda c: abs(c - near))


def compute_max_pain(chain: pd.DataFrame, spot: float | None = None, moneyness_range: float = 0.3) -> float | None:
    """스팟 ±moneyness_range 안의 근월 하위체인으로만 MaxPain을 계산한다.

    표준 MaxPain은 전 행사가·전 계약을 쓰지만, SK하이닉스처럼 딥ITM 저행사가에 오래된
    잔존 미결제약정(1,050,000 콜 72,014계약, 당일 거래량 16계약)이 전체 OI의 90%를
    차지하는 종목에서는 그 스톡이 call_pain 합을 지배해 MaxPain이 스팟보다 40%+ 아래로
    끌려간다. 후보 행사가뿐 아니라 내재가치 합산에 쓰는 '계약'도 같은 밴드로 제한해야
    이 오염이 사라진다 (RECONCILIATION.md O1). find_walls와 동일한 근방 기준.
    """
    all_strikes = np.sort(chain["strike"].unique())
    if len(all_strikes) == 0:
        return None

    band_lo, band_hi = -np.inf, np.inf
    candidates = all_strikes
    if spot is not None:
        lo, hi = spot * (1 - moneyness_range), spot * (1 + moneyness_range)
        band = all_strikes[(all_strikes >= lo) & (all_strikes <= hi)]
        if len(band) < 3:  # 행사가가 성기면 한 단계 넓힌다
            lo, hi = spot * 0.5, spot * 1.5
            band = all_strikes[(all_strikes >= lo) & (all_strikes <= hi)]
        if len(band) >= 3:
            candidates, band_lo, band_hi = band, lo, hi

    sub = chain[(chain["strike"] >= band_lo) & (chain["strike"] <= band_hi)]
    calls = sub[sub["type"] == "C"][["strike", "oi"]].to_numpy()
    puts = sub[sub["type"] == "P"][["strike", "oi"]].to_numpy()

    pains = []
    for p in candidates:
        call_pain = np.sum(calls[:, 1] * np.maximum(p - calls[:, 0], 0))
        put_pain = np.sum(puts[:, 1] * np.maximum(puts[:, 0] - p, 0))
        pains.append(call_pain + put_pain)
    return float(candidates[int(np.argmin(pains))])


def dex_profile(
    chain: pd.DataFrame,
    as_of: date,
    spot_grid: np.ndarray,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
) -> pd.Series:
    """가상 스팟별 Net DEX(딜러 델타 익스포저) 프로파일. gex_profile과 같은 패턴이며,
    부호 규약은 with_greeks_at_spot()의 dex_default_sign(균일 -1)과 동일하다."""
    t = _time_to_expiry(chain["expiry"].iloc[0], as_of)
    iv = chain["iv"].fillna(chain["iv"].median()).to_numpy() / 100
    strike = chain["strike"].to_numpy()
    types = chain["type"].to_numpy()
    is_call = (types == "C")
    oi = chain["oi"].to_numpy()
    sign = _resolve_signs(strike, types, np.full(len(chain), -1), sign_overrides)

    net_dex = []
    for s in spot_grid:
        g = compute_greeks(
            spot=np.full(len(chain), s), strike=strike, t_years=np.full(len(chain), t), sigma=iv, is_call=is_call, r=r, q=q
        )
        net_dex.append((sign * oi * g["delta"] * multiplier * s).sum())
    return pd.Series(net_dex, index=spot_grid)


def vanna_profile(
    chain: pd.DataFrame,
    as_of: date,
    spot_grid: np.ndarray,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
) -> pd.Series:
    """가상 스팟별 Net Vanna Exposure 프로파일. GEX와 같은 딜러 부호 규약(콜 롱·풋 숏
    가정, 또는 행사가별 override)을 쓴다 — with_greeks_at_spot()의 gex_sign과 동일."""
    t = _time_to_expiry(chain["expiry"].iloc[0], as_of)
    iv = chain["iv"].fillna(chain["iv"].median()).to_numpy() / 100
    strike = chain["strike"].to_numpy()
    types = chain["type"].to_numpy()
    is_call = (types == "C")
    oi = chain["oi"].to_numpy()
    sign = _resolve_signs(strike, types, np.where(is_call, 1, -1), sign_overrides)

    net_vanna = []
    for s in spot_grid:
        g = compute_greeks(
            spot=np.full(len(chain), s), strike=strike, t_years=np.full(len(chain), t), sigma=iv, is_call=is_call, r=r, q=q
        )
        net_vanna.append((sign * oi * g["vanna"] * multiplier * s).sum())
    return pd.Series(net_vanna, index=spot_grid)


def _oi_weighted_strike_range(chain: pd.DataFrame, low_pct: float = 0.02, high_pct: float = 0.98) -> tuple[float | None, float | None]:
    """OI 누적 분포 기준 [low_pct, high_pct] 구간에 해당하는 행사가 범위.
    한두 계약짜리 극단 행사가에 그리드가 휘둘리는 것을 막는다."""
    by_strike = chain.groupby("strike")["oi"].sum().sort_index()
    by_strike = by_strike[by_strike > 0]
    if by_strike.empty:
        return None, None
    cum = by_strike.cumsum() / by_strike.sum()
    lo = by_strike.index[cum.searchsorted(low_pct)]
    hi_idx = min(cum.searchsorted(high_pct), len(cum) - 1)
    hi = by_strike.index[hi_idx]
    return float(lo), float(hi)


def find_walls(
    chain_with_greeks: pd.DataFrame, spot: float, moneyness_range: float = 0.3
) -> tuple[float | None, float | None, float | None, float | None]:
    """Call Wall / Put Wall (SpotGamma/FlashAlpha 등 업계 공통 정의).

    Call Wall = 콜 옵션만의 GEX 합이 가장 큰 행사가.
    Put Wall = 풋 옵션만의 GEX 합의 절대값이 가장 큰 행사가.
    둘 다 스팟 위/아래 방향과 무관하게, 콜/풋을 나눠서 각각 최댓값을 찾는다.

    추가로 call_wall_above(스팟 '위' 콜 GEX 최대) / put_wall_below(스팟 '아래' |풋 GEX|
    최대)도 반환한다 — 전역 Call Wall이 스팟 아래에 있을 때도 상단 저항(Gamma Wall)을
    표시하기 위함. fmkorea가 SK하이닉스에서 "핵심 감마 지지 1,700,000"과 "Gamma Wall
    1,917,930"을 함께 제시하는 것과 같은 이중 레벨 (RECONCILIATION.md O4).

    스팟 대비 ±moneyness_range(기본 30%) 밖의 행사가는 제외한다 — 실제로 개별주식
    옵션에서 딥ITM/OTM에 쌓인 오래된 잔존 미결제약정(예: 주가가 크게 오른 뒤에도
    안 정리된 저행사가 콜)이 감마 기여는 미미한데 미결제약정 수량 자체가 거대해서
    Call Wall/Put Wall을 스팟과 무관한 엉뚱한 곳으로 왜곡시키는 사례를 발견해 반영함
    (2026-08-26 SK하이닉스 사례: 행사가 1,050,000 콜에 미결제약정 72,007계약,
    거래량은 3계약뿐 — KRX 원본 데이터로 확인, 파싱 오류 아님).
    """
    near = chain_with_greeks[
        (chain_with_greeks["strike"] >= spot * (1 - moneyness_range))
        & (chain_with_greeks["strike"] <= spot * (1 + moneyness_range))
    ]
    call_gex = near[near["type"] == "C"].groupby("strike")["gex"].sum()
    put_gex = near[near["type"] == "P"].groupby("strike")["gex"].sum()

    call_wall = float(call_gex.idxmax()) if not call_gex.empty and call_gex.max() > 0 else None
    put_wall = float(put_gex.abs().idxmax()) if not put_gex.empty and put_gex.abs().max() > 0 else None

    call_above = call_gex[call_gex.index > spot]
    put_below = put_gex[put_gex.index < spot]
    call_wall_above = float(call_above.idxmax()) if not call_above.empty and call_above.max() > 0 else None
    put_wall_below = float(put_below.abs().idxmax()) if not put_below.empty and put_below.abs().max() > 0 else None
    # 전역 wall과 같은 값이면 중복 표기 방지
    if call_wall_above == call_wall:
        call_wall_above = None
    if put_wall_below == put_wall:
        put_wall_below = None

    return call_wall, put_wall, call_wall_above, put_wall_below


def positioning_skew(chain: pd.DataFrame) -> dict | None:
    """포지션(미결제약정·거래량) 기준 콜/풋 쏠림.

    25델타 Risk Reversal이 '변동성 스큐'(풋 IV가 콜 IV보다 비싼가)를 재는 것과 달리,
    이건 '실제 포지션이 콜 쪽에 쏠렸나'를 잰다. fmkorea의 "콜 쏠림 %/상방 쏠림도"가
    이 개념 (RECONCILIATION.md O5). 둘은 지수옵션에서 흔히 동시에 성립(콜 OI 우위 +
    풋 IV 비쌈)이라 서로 모순이 아니라 다른 축이다.

    반환: {call_oi, put_oi, call_vol, put_vol, oi_pcr, vol_pcr, oi_skew, vol_skew}
    (skew = (call - put) / (call + put), 양수면 콜 우위).
    """
    if chain.empty:
        return None
    c = chain[chain["type"] == "C"]
    p = chain[chain["type"] == "P"]
    call_oi, put_oi = float(c["oi"].sum()), float(p["oi"].sum())
    call_vol, put_vol = float(c["volume"].sum()), float(p["volume"].sum())

    def _skew(a: float, b: float) -> float | None:
        return (a - b) / (a + b) if (a + b) > 0 else None

    return {
        "call_oi": call_oi,
        "put_oi": put_oi,
        "call_vol": call_vol,
        "put_vol": put_vol,
        "oi_pcr": put_oi / call_oi if call_oi > 0 else None,
        "vol_pcr": put_vol / call_vol if call_vol > 0 else None,
        "oi_skew": _skew(call_oi, put_oi),
        "vol_skew": _skew(call_vol, put_vol),
    }


def risk_reversal_25d(chain_with_greeks: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """25델타 리스크 리버설 = 25델타 콜 IV − 25델타 풋 IV (업계 표준 지표, 예: SpotGamma
    "25D Risk Reversal"). 정확히 델타 0.25/-0.25인 행사가가 상장돼 있지 않으므로
    체인에서 가장 가까운 델타를 가진 행사가의 IV를 쓴다. 반환: (콜 IV, 풋 IV, RR)."""
    calls = chain_with_greeks[(chain_with_greeks["type"] == "C") & chain_with_greeks["iv"].notna() & (chain_with_greeks["iv"] > 0)]
    puts = chain_with_greeks[(chain_with_greeks["type"] == "P") & chain_with_greeks["iv"].notna() & (chain_with_greeks["iv"] > 0)]

    call_iv = None
    if not calls.empty:
        idx = (calls["delta"] - 0.25).abs().idxmin()
        call_iv = float(calls.loc[idx, "iv"])

    put_iv = None
    if not puts.empty:
        idx = (puts["delta"] - (-0.25)).abs().idxmin()
        put_iv = float(puts.loc[idx, "iv"])

    rr = (call_iv - put_iv) if (call_iv is not None and put_iv is not None) else None
    return call_iv, put_iv, rr


def synthetic_forward_by_strike(chain: pd.DataFrame, r: float, q: float, t_years: float) -> pd.DataFrame:
    """풋-콜 패리티 기반 행사가별 내재 스팟(합성지수).

    C − P = S·e^(−qT) − K·e^(−rT)  ⟹  S = (C − P + K·e^(−rT))·e^(qT)

    콜·풋 종가가 둘 다 있는 행사가만 계산할 수 있다(둘 중 하나라도 미체결/결측이면 제외).
    시장이 그 행사가 근방에서 실제로 가격을 매긴 지수 수준을 역산한 것이라, 실제 스팟과
    괴리가 크면 그 행사가 근방 옵션이 상대적으로 고평가/저평가돼 있다는 뜻이다.
    """
    calls = chain[chain["type"] == "C"][["strike", "close"]].rename(columns={"close": "call_close"})
    puts = chain[chain["type"] == "P"][["strike", "close"]].rename(columns={"close": "put_close"})
    merged = pd.merge(calls, puts, on="strike", how="inner").dropna()
    if merged.empty:
        return merged
    merged["implied_spot"] = (merged["call_close"] - merged["put_close"] + merged["strike"] * np.exp(-r * t_years)) * np.exp(q * t_years)
    return merged.sort_values("strike").reset_index(drop=True)


def analyze(
    chain: pd.DataFrame,
    spot: float,
    as_of: date,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
) -> tuple[Levels, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """반환: (levels, chain_g, gex_profile, dex_profile, vanna_profile)."""
    chain_g = with_greeks_at_spot(chain, spot, as_of, r=r, q=q, multiplier=multiplier, sign_overrides=sign_overrides)
    strike_min, strike_max = float(chain["strike"].min()), float(chain["strike"].max())

    # 그리드 범위는 "미결제약정이 실질적으로 쌓여있는" 행사가 기준으로 잡는다.
    # 단순 min/max는 거래 없이 상장만 된 극단 행사가(예: 1계약짜리 outlier)에
    # 취약해 그리드가 지나치게 넓어지고, 그 결과 스팟에서 먼 곳에서 무의미한
    # 0교차(수치 노이즈)가 나올 수 있다 — 그래서 OI 누적 2~98% 구간을 쓴다.
    active_min, active_max = _oi_weighted_strike_range(chain)
    if active_min is None:
        active_min, active_max = strike_min, strike_max

    grid_lo = min(spot * 0.85, active_min * 0.97)
    grid_hi = max(spot * 1.15, active_max * 1.03)
    grid = np.linspace(grid_lo, grid_hi, 141)
    profile = gex_profile(chain, as_of, grid, r=r, q=q, multiplier=multiplier, sign_overrides=sign_overrides)
    dex_prof = dex_profile(chain, as_of, grid, r=r, q=q, multiplier=multiplier, sign_overrides=sign_overrides)
    vanna_prof = vanna_profile(chain, as_of, grid, r=r, q=q, multiplier=multiplier, sign_overrides=sign_overrides)

    zero_gamma = _interp_zero_cross(profile, near=spot)
    max_pain = compute_max_pain(chain, spot=spot)
    dex_neutral = _interp_zero_cross(dex_prof)
    call_wall, put_wall, call_wall_above, put_wall_below = find_walls(chain_g, spot)

    levels = Levels(
        spot=spot,
        max_pain=max_pain,
        dex_neutral_maxpain=dex_neutral,
        zero_gamma=zero_gamma,
        call_wall=call_wall,
        put_wall=put_wall,
        strike_min=float(chain["strike"].min()),
        strike_max=float(chain["strike"].max()),
        call_wall_above=call_wall_above,
        put_wall_below=put_wall_below,
    )
    return levels, chain_g, profile, dex_prof, vanna_prof


def build_scenarios(levels: Levels) -> list[dict]:
    """Call Wall/Put Wall은 콜/풋 각각의 최대 감마 집중점이라 스팟 위/아래 어디든
    있을 수 있다 — 실제 위치를 보고 방향에 맞게 시나리오를 구성한다.

    'invalidation'(무효화 레벨)은 개인 포지션의 손절가가 아니다 — 그 시나리오가
    가정하는 구조(예: 상승 돌파)가 깨졌을 때 다음으로 봐야 할 반대 방향의 구조적
    레벨(Zero Gamma/Call Wall/Put Wall 등)일 뿐이라, 진입가·리스크 허용도와 무관하게
    누구에게나 같은 값이다."""
    spot = levels.spot
    scenarios = []

    if levels.call_wall is not None and levels.call_wall > spot:
        invalidation = None
        if levels.zero_gamma is not None and levels.zero_gamma < spot:
            invalidation = levels.zero_gamma
        elif levels.put_wall is not None and levels.put_wall < spot:
            invalidation = levels.put_wall
        scenarios.append(
            {
                "name": "Bullish Squeeze",
                "trigger": f"{spot:,.1f} 상향 돌파",
                "target": f"{levels.call_wall:,.1f}",
                "invalidation": f"{invalidation:,.1f}" if invalidation is not None else None,
                "note": "콜 감마 집중구간(Call Wall) 돌파 시 딜러 헤지 매수가 상승을 증폭할 수 있는 구간",
            }
        )
    if levels.max_pain:
        upper = levels.call_wall if (levels.call_wall is not None and levels.call_wall > spot) else None
        lower = levels.put_wall if (levels.put_wall is not None and levels.put_wall < spot) else None
        if upper is not None and lower is not None:
            box_invalidation = f"상단 {upper:,.1f} / 하단 {lower:,.1f} 이탈 시"
        elif upper is not None:
            box_invalidation = f"상단 {upper:,.1f} 이탈 시"
        elif lower is not None:
            box_invalidation = f"하단 {lower:,.1f} 이탈 시"
        else:
            box_invalidation = None
        scenarios.append(
            {
                "name": "Base Case (박스권)",
                "trigger": f"{levels.max_pain:,.1f} 부근 유지",
                "target": f"{levels.max_pain:,.1f}",
                "invalidation": box_invalidation,
                "note": "만기 수렴 시 MaxPain 근방으로 가격이 자석처럼 끌리는 경향, Theta decay 우세",
            }
        )
    bearish_trigger = levels.zero_gamma
    bearish_target = levels.put_wall if (levels.put_wall is not None and levels.put_wall < spot) else None
    if bearish_trigger is not None or bearish_target is not None:
        bearish_invalidation = levels.call_wall if (levels.call_wall is not None and levels.call_wall > spot) else None
        scenarios.append(
            {
                "name": "Bearish Regime Shift",
                "trigger": f"{bearish_trigger:,.1f} 하향 이탈" if bearish_trigger is not None else "Zero Gamma 이탈",
                "target": f"{bearish_target:,.1f}" if bearish_target is not None else "-",
                "invalidation": f"{bearish_invalidation:,.1f}" if bearish_invalidation is not None else None,
                "note": "Zero Gamma 붕괴 시 Long→Short Gamma 전환, Put Wall 방향으로 하락이 가속될 수 있는 구간",
            }
        )
    return scenarios
