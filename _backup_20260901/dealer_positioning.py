"""KOSPI200 옵션 딜러 포지셔닝 분석 (MaxPain / Zero Gamma / Call Wall·Put Wall / DEX·VEX·Charm Flow).

부호 규약(가정, WORKPLAN Phase 4-1 / WORKPLAN2 B6 — **KRX에서 검증 불가, 반대일 수 있음**):
- GEX/DEX/VEX/Charm 전부 **하나의** 인벤토리 모델: 딜러 콜 롱·풋 숏 (+1 콜 / -1 풋),
  SqueezeMetrics/SpotGamma 및 FlashAlpha 표준 $DEX 규약. Net GEX = Σ(콜 OI×Γ) − Σ(풋 OI×Γ),
  Net DEX = Σ(콜 OI×δ) − Σ(풋 OI×δ). (예전엔 DEX만 "콜·풋 모두 숏" 리테일 휴리스틱이라
  같은 콜에 대해 GEX와 반대 인벤토리를 가정 — 내부 불일치라 폐기.)
- 그릭스는 각 종목 실제 IV(스마일 보간)로 계산. 기본은 sticky-strike(스팟이 바뀌어도 행사가별
  IV 고정)이며, sticky-moneyness 가정과의 차이는 analyze()의 Zero Gamma 민감도 밴드가 잡는다.

⚠️ 이 부호 규약은 미국시장 기준이다. KB증권 투자자별 순매수(금융투자 = 딜러 근사)에서는
   **콜·풋 모두 순매수(롱)**로 나와 위 가정과 반대였다. 딜러 실제 포지션은 미국시장에서도
   비공개라 검증 불가능한 모델링 관행이다(SpotGamma DDOI). 따라서:
   - Zero Gamma / Call Wall / Put Wall의 **위치**는 전역 부호 반전에 불변이라 "OI(감마)가
     집중된 레벨"로는 읽을 수 있다.
   - 그러나 "Zero Gamma 위 = 안정/아래 = 가속" 같은 **국면 해석**과 Net GEX/DEX/Vanna/Charm
     헤드라인 값의 **부호·크기**는 규약이 뒤집히면 통째로 반대가 된다. 리포트는 이걸
     방향성 단정 없이 레벨·수치로만 제시한다 (SIGN_CONVENTION_CAVEAT).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from greeks import CONTRACT_MULTIPLIER, DIVIDEND_YIELD, RISK_FREE_RATE, compute_greeks

SIGN_CONVENTION_CAVEAT = (
    "부호 규약: 미국식(딜러 콜 롱·풋 숏)을 GEX·DEX·VEX·Charm에 일관 적용. KRX에서 검증 "
    "불가하며 KB증권 데이터(금융투자 콜·풋 순매수)는 반대를 시사한다. 레벨의 위치는 부호 "
    "반전에 불변이나, 국면 해석과 Net 익스포저 부호는 규약에 의존한다."
)


def _interp_extrap(x_new: np.ndarray, x_obs: np.ndarray, y_obs: np.ndarray) -> np.ndarray:
    """log-moneyness 축 선형보간 + **윙은 마지막 두 관측점의 기울기로 외삽**(flat 아님).
    실제 스큐는 하락 윙으로 갈수록 계속 가팔라지므로 flat 연장은 딥OTM 풋 IV를 과소평가한다
    (WORKPLAN2 B4). IV는 [1e-3, 5.0]으로 클립해 비정상 외삽을 막는다."""
    order = np.argsort(x_obs)
    xs, ys = x_obs[order], y_obs[order]
    out = np.interp(x_new, xs, ys)  # 범위 안은 선형보간, 밖은 일단 flat
    if len(xs) >= 2:
        lo_sl = (ys[1] - ys[0]) / (xs[1] - xs[0])
        hi_sl = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
        left, right = x_new < xs[0], x_new > xs[-1]
        out[left] = ys[0] + lo_sl * (x_new[left] - xs[0])
        out[right] = ys[-1] + hi_sl * (x_new[right] - xs[-1])
    return np.clip(out, 1e-3, 5.0)


def fill_iv_smile(chain: pd.DataFrame, spot: float | None = None) -> pd.DataFrame:
    """결측/비정상(≤0) IV를 log-moneyness 축에서 선형보간하고, 관측 범위 밖은 마지막 두
    점 기울기로 외삽한다 (WORKPLAN2 B4). 같은 행사가에 반대 타입 관측 IV가 있으면 먼저
    그걸 복사(풋콜 IV 동일 원칙)한 뒤, 부족하면 타입별 스마일로 보간한다.

    예전엔 flat 외삽 + 타입 완전 분리라 (1) 딥OTM 풋 IV 과소평가, (2) 같은 행사가 콜/풋
    IV가 갈려 감마가 콜집계·풋집계에서 달라지는 문제가 있었다."""
    df = chain.copy()
    if "iv" not in df.columns or df.empty:
        return df
    ref = float(spot) if spot else float(df["strike"].median())
    lm = np.log(df["strike"].to_numpy(dtype=float) / ref)
    strike = df["strike"].to_numpy(dtype=float)
    iv = df["iv"].to_numpy(dtype=float)
    ok = np.isfinite(iv) & (iv > 0)
    typ = df["type"].to_numpy()

    # 1) 같은 행사가 반대 타입에 관측 IV가 있으면 복사 (풋콜 패리티상 IV 동일)
    for i in np.where(~ok)[0]:
        mate = ok & (strike == strike[i]) & (typ != typ[i])
        if mate.any():
            iv[i] = iv[mate][0]
    ok = np.isfinite(iv) & (iv > 0)

    # 2) 타입별 스마일 보간 + 기울기 외삽
    for t in ("C", "P"):
        m = typ == t
        k = m & ok
        need = m & ~ok
        if k.sum() >= 2:
            iv[need] = _interp_extrap(lm[need], lm[k], iv[k])
        elif k.sum() == 1:
            iv[need] = iv[k][0]

    # 3) 최후수단: 타입에 관측이 <2개면 전체 중앙값
    still_bad = ~(np.isfinite(iv) & (iv > 0))
    if still_bad.any():
        good = np.isfinite(iv) & (iv > 0)
        iv[still_bad] = np.median(iv[good]) if good.any() else np.nan
    df["iv"] = iv
    return df


def implied_dividend_yield(spot: float, forward: float, r: float, t: float, bound: float = 0.50) -> float | None:
    """F = S*e^((r-q)T) 관계에서 q 역산. 비정상적으로 크면(유동성 부족 등) None 반환.

    한국 상장사는 배당을 연 1회(대개 12월 말/1분기)에 몰아 준다. 배당락일을 걸치는
    ~30일 옵션이면 그 한 달에 지수의 ~2%가 빠지므로 **연율화** q가 15~40%로 정상적으로
    나온다 — 예전 bound=0.05는 이 정답값을 기각하고 호출측이 1.5% 고정값으로 폴백하게
    만들어 선도가·델타·GEX 가중·Zero Gamma를 그 만기에 10~20p 어긋나게 했다. bound를
    넓히되, 호출측(_resolve_rq)이 '선물 만기가 옵션 만기와 근접할 때만' 신뢰하도록 한다.
    """
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
    zero_gamma_lo: float | None = None    # 파라미터·가정 민감도 밴드 하단
    zero_gamma_hi: float | None = None    # 〃 상단 (WORKPLAN Phase 4-2: 단일 점 표기 금지)
    max_pain_20: float | None = None      # windowed MaxPain ±20% (민감도 병기, WORKPLAN2 B5)
    max_pain_40: float | None = None      # 〃 ±40%

    @property
    def zero_gamma_band_txt(self) -> str | None:
        if self.zero_gamma is None or self.zero_gamma_lo is None or self.zero_gamma_hi is None:
            return None
        return f"{self.zero_gamma:,.1f} (민감도 {self.zero_gamma_lo:,.1f}~{self.zero_gamma_hi:,.1f})"

    @property
    def spot_above_range(self) -> bool:
        return self.spot > self.strike_max

    @property
    def spot_below_range(self) -> bool:
        return self.spot < self.strike_min


def _time_to_expiry(expiry: date, as_of: date) -> float:
    """잔존기간(연). KRX 지수·개별주식 옵션은 최종거래일 **종가**로 현금결제되고 데이터도
    EOD(종가) 기준이라, as_of 종가 → 만기 종가는 close-to-close = 정확히 (expiry-as_of)
    달력일이다(ACT/365). 별도 장중 분수 보정이 필요 없다 (WORKPLAN2 B2 검토 결론).
    T-0은 상류(RECONCILIATION O2)에서 제외하므로 floor 0.25일은 0 나눗셈 방지용."""
    return max((expiry - as_of).days, 0.25) / 365


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
    df = fill_iv_smile(chain, spot)
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
    # WORKPLAN2 B6: GEX·DEX·VEX·Charm 전부 **하나의** 딜러 인벤토리 모델을 쓴다 —
    # 딜러 콜 롱·풋 숏(SpotGamma / FlashAlpha 표준 $DEX). 예전엔 DEX만 "콜·풋 모두 숏"
    # (리테일 0DTE 휴리스틱)이라 같은 체인의 콜에 대해 GEX와 반대 인벤토리를 가정했다.
    dealer_default_sign = np.where(types == "C", 1, -1)
    sign = _resolve_signs(strikes, types, dealer_default_sign, sign_overrides)

    df["dealer_sign"] = sign
    # DEX/VEX/Charm은 $DEX 규약대로 스팟을 곱해 델타 명목가치(통화 단위)로 만든다 —
    # 승수가 작은 개별주식 옵션에서 0.0으로 반올림되지 않게 (RECONCILIATION.md O3).
    # (지수 대비 절대 크기 비교는 여전히 무의미 — 각 종목 자기 히스토리 대비로만 읽을 것.)
    df["dex"] = sign * df["oi"] * df["delta"] * multiplier * spot
    df["gex"] = sign * df["oi"] * df["gamma"] * spot**2 * 0.01 * multiplier
    df["vex"] = sign * df["oi"] * df["vanna"] * multiplier * spot
    df["charm_exp"] = sign * df["oi"] * df["charm"] * multiplier * spot
    return df


def _smile_iv_at_spot(strike: np.ndarray, types: np.ndarray, iv_ref: np.ndarray, ref_spot: float, new_spot: float) -> np.ndarray:
    """sticky-moneyness: 스팟이 ref_spot→new_spot로 움직이면 스마일이 통째로 따라가므로,
    행사가 K의 IV는 원 스마일을 log-moneyness ln(K/new_spot) 에서 평가한 값이 된다.
    타입(C/P)별로 원 스마일(ln(K/ref_spot), iv_ref)을 선형보간한다."""
    lm_ref = np.log(strike / ref_spot)
    lm_new = np.log(strike / new_spot)
    out = iv_ref.copy()
    for tp in ("C", "P"):
        m = types == tp
        if m.sum() < 2:
            continue
        order = np.argsort(lm_ref[m])
        out[m] = np.interp(lm_new[m], lm_ref[m][order], iv_ref[m][order])
    return out


def gex_profile(
    chain: pd.DataFrame,
    as_of: date,
    spot_grid: np.ndarray,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
    multiplier: float = CONTRACT_MULTIPLIER,
    sign_overrides: SignOverrides | None = None,
    iv_sticky_moneyness: bool = False,
) -> pd.Series:
    """Net GEX 프로파일. iv_sticky_moneyness=False(기본)는 sticky-strike(행사가별 IV 고정),
    True는 sticky-moneyness(스마일이 스팟 따라 평행이동) — 둘의 Zero Gamma 차이가
    이 모델의 지배적 불확실성 중 하나다(analyze()의 민감도 밴드에서 사용)."""
    t = _time_to_expiry(chain["expiry"].iloc[0], as_of)
    ref_spot = float(np.median(spot_grid))
    iv = fill_iv_smile(chain, ref_spot)["iv"].to_numpy() / 100
    strike = chain["strike"].to_numpy()
    is_call = (chain["type"] == "C").to_numpy()
    types = chain["type"].to_numpy()
    oi = chain["oi"].to_numpy()
    sign = _resolve_signs(strike, types, np.where(is_call, 1, -1), sign_overrides)

    net_gex = []
    for s in spot_grid:
        sigma = _smile_iv_at_spot(strike, types, iv, ref_spot, s) if iv_sticky_moneyness else iv
        g = compute_greeks(
            spot=np.full(len(chain), s),
            strike=strike,
            t_years=np.full(len(chain), t),
            sigma=sigma,
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


STALE_OI_VOL_MULT = 200  # OI가 당일 거래량의 이 배수를 넘고 딥(±15% 밖)이면 "방치된 잔존분"으로 보고 제외


def _drop_stale_oi(chain: pd.DataFrame, spot: float | None) -> pd.DataFrame:
    """딥ITM/OTM(±15% 밖)에서 OI가 당일 거래량의 STALE_OI_VOL_MULT 배를 넘는 행사가를
    제외한다 — 주가가 크게 움직인 뒤에도 안 정리된 잔존 미결제약정(SK하이닉스 1,050,000
    콜 72,014계약 / 당일 16계약 사례). volume 컬럼이 없으면 원본을 그대로 돌려준다."""
    if spot is None or "volume" not in chain.columns:
        return chain
    deep = (chain["strike"] < spot * 0.85) | (chain["strike"] > spot * 1.15)
    stale = deep & (chain["oi"] > STALE_OI_VOL_MULT * chain["volume"].clip(lower=1))
    return chain[~stale] if stale.any() else chain


def compute_max_pain(chain: pd.DataFrame, spot: float | None = None, moneyness_range: float = 0.3) -> float | None:
    """스팟 ±moneyness_range 안의 근월 하위체인으로만 MaxPain을 계산한다 (windowed·비표준).

    표준 MaxPain은 전 행사가·전 계약을 쓰지만, SK하이닉스처럼 딥ITM 저행사가에 오래된
    잔존 미결제약정(1,050,000 콜 72,014계약, 당일 거래량 16계약)이 전체 OI의 90%를
    차지하는 종목에서는 그 스톡이 call_pain 합을 지배해 MaxPain이 스팟보다 40%+ 아래로
    끌려간다. 후보 행사가뿐 아니라 내재가치 합산에 쓰는 '계약'도 같은 밴드로 제한하고,
    추가로 _drop_stale_oi 로 방치 잔존분을 명시 제외한다 (RECONCILIATION.md O1 / WORKPLAN2 B5).
    """
    chain = _drop_stale_oi(chain, spot)
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
    부호 규약도 GEX와 통일: 딜러 콜 롱·풋 숏 (+1 콜 / -1 풋), WORKPLAN2 B6."""
    t = _time_to_expiry(chain["expiry"].iloc[0], as_of)
    iv = fill_iv_smile(chain, float(np.median(spot_grid)))["iv"].to_numpy() / 100
    strike = chain["strike"].to_numpy()
    types = chain["type"].to_numpy()
    is_call = (types == "C")
    oi = chain["oi"].to_numpy()
    sign = _resolve_signs(strike, types, np.where(is_call, 1, -1), sign_overrides)

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
    iv = fill_iv_smile(chain, float(np.median(spot_grid)))["iv"].to_numpy() / 100
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


RR_DELTA_TOL = 0.10  # 가장 가까운 델타가 이보다 멀면 "25델타"로 부르지 않는다(얇은 체인 방어).


def risk_reversal_25d(chain_with_greeks: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    """25델타 리스크 리버설 = 25델타 콜 IV − 25델타 풋 IV (업계 표준 지표, 예: SpotGamma
    "25D Risk Reversal"). 정확히 델타 0.25/-0.25인 행사가가 상장돼 있지 않으므로
    체인에서 가장 가까운 델타를 가진 행사가의 IV를 쓴다 — 단 그 델타가 0.25에서
    RR_DELTA_TOL 이상 벗어나면(개별주식 등 얇은 체인) 그 leg은 None으로 둔다.
    반환: (콜 IV, 풋 IV, RR)."""
    calls = chain_with_greeks[(chain_with_greeks["type"] == "C") & chain_with_greeks["iv"].notna() & (chain_with_greeks["iv"] > 0)]
    puts = chain_with_greeks[(chain_with_greeks["type"] == "P") & chain_with_greeks["iv"].notna() & (chain_with_greeks["iv"] > 0)]

    call_iv = None
    if not calls.empty:
        idx = (calls["delta"] - 0.25).abs().idxmin()
        if abs(float(calls.loc[idx, "delta"]) - 0.25) <= RR_DELTA_TOL:
            call_iv = float(calls.loc[idx, "iv"])

    put_iv = None
    if not puts.empty:
        idx = (puts["delta"] - (-0.25)).abs().idxmin()
        if abs(float(puts.loc[idx, "delta"]) - (-0.25)) <= RR_DELTA_TOL:
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
    max_pain_20 = compute_max_pain(chain, spot=spot, moneyness_range=0.2)
    max_pain_40 = compute_max_pain(chain, spot=spot, moneyness_range=0.4)
    dex_neutral = _interp_zero_cross(dex_prof, near=spot)  # zero_gamma와 동일하게 스팟 근방 크로스
    call_wall, put_wall, call_wall_above, put_wall_below = find_walls(chain_g, spot)

    # WORKPLAN2 B3: Zero Gamma "파라미터·가정 민감도" 밴드. 지배적 불확실성은 (1) sticky-strike
    # vs sticky-moneyness 스마일 가정, (2) 상수 r/q, (3) 고정 IV 수준. r는 ±25bp(±100bp는
    # 비현실적이라 밴드를 혼자 지배했음), q는 ±100bp, IV는 ±5%, 그리고 sticky-moneyness 1샘플.
    zg_lo = zg_hi = None
    if zero_gamma is not None:
        zg_samples = [zero_gamma]
        # (dr, dq, iv_scale, sticky_moneyness)
        perturbations = [
            (0.0025, 0.0, 1.0, False), (-0.0025, 0.0, 1.0, False),
            (0.0, 0.01, 1.0, False), (0.0, -0.01, 1.0, False),
            (0.0, 0.0, 1.05, False), (0.0, 0.0, 0.95, False),
            (0.0, 0.0, 1.0, True),
        ]
        for dr, dq, sm, sticky in perturbations:
            ch = chain.copy()
            if sm != 1.0 and "iv" in ch.columns:
                ch["iv"] = ch["iv"] * sm
            p = gex_profile(ch, as_of, grid, r=r + dr, q=q + dq, multiplier=multiplier,
                            sign_overrides=sign_overrides, iv_sticky_moneyness=sticky)
            zc = _interp_zero_cross(p, near=spot)
            if zc is not None:
                zg_samples.append(zc)
        zg_lo, zg_hi = float(min(zg_samples)), float(max(zg_samples))

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
        zero_gamma_lo=zg_lo,
        zero_gamma_hi=zg_hi,
        max_pain_20=max_pain_20,
        max_pain_40=max_pain_40,
    )
    return levels, chain_g, profile, dex_prof, vanna_prof


def build_scenarios(levels: Levels) -> list[dict]:
    """OI(감마)가 집중된 레벨을 스팟 위/아래로 정리해 보여준다. 방향 예측이 아니라
    "가격이 이 레벨에 닿으면 딜러 헤지 흐름이 바뀔 수 있는 지점"의 나열이다.

    ⚠️ 각 note의 딜러 헤지 방향(매수/매도, 증폭/완충)은 미국식 부호 규약(딜러 콜 롱·풋
    숏)을 전제한 것이다. KRX에서는 이 규약이 반대일 수 있어(모듈 docstring / KB증권
    데이터 참고) 방향은 "규약이 맞다면"의 조건부로 읽어야 한다. 레벨의 **위치**는
    부호 규약과 무관하게 유효하다.

    'invalidation'은 손절가가 아니라, 그 레벨 구조가 깨졌을 때 다음으로 볼 반대편
    구조적 레벨이다 — 진입가·리스크 허용도와 무관하게 누구에게나 같은 값."""
    spot = levels.spot
    scenarios = []

    # 전역 Call Wall이 스팟 아래면(=대부분 콜 감마가 이미 ITM), 스팟 '위'의 콜 감마 최대
    # (call_wall_above)를 상단 목표로 쓴다 — 없으면 시나리오 자체가 빠져 상단 저항이
    # 레벨표에만 있고 시나리오에서 누락되던 문제 (WORKPLAN2 D2).
    upper_target = None
    if levels.call_wall is not None and levels.call_wall > spot:
        upper_target = levels.call_wall
    elif levels.call_wall_above is not None and levels.call_wall_above > spot:
        upper_target = levels.call_wall_above
    if upper_target is not None:
        invalidation = None
        if levels.zero_gamma is not None and levels.zero_gamma < spot:
            invalidation = levels.zero_gamma
        elif levels.put_wall is not None and levels.put_wall < spot:
            invalidation = levels.put_wall
        elif levels.put_wall_below is not None and levels.put_wall_below < spot:
            invalidation = levels.put_wall_below
        scenarios.append(
            {
                "name": "Bullish Squeeze",
                "trigger": f"{spot:,.1f} 상향 돌파",
                "target": f"{upper_target:,.1f}",
                "invalidation": f"{invalidation:,.1f}" if invalidation is not None else None,
                "note": "콜 감마가 가장 집중된 상단 레벨(Call Wall / 상단 Gamma Wall). 규약이 맞다면 이 위에서 딜러 매수 헤지가 상승을 증폭할 수 있고, 규약이 반대면 완충 구간이 된다",
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
                "note": "만기 수렴 시 MaxPain 근방으로 가격이 수렴하는 경향(통계적 근거는 약함, ±20/30/40% 밴드 민감), Theta decay 우세",
            }
        )
    bearish_trigger = levels.zero_gamma
    bearish_target = levels.put_wall if (levels.put_wall is not None and levels.put_wall < spot) else None
    if bearish_target is None and levels.put_wall_below is not None and levels.put_wall_below < spot:
        bearish_target = levels.put_wall_below
    if bearish_trigger is not None or bearish_target is not None:
        bearish_invalidation = levels.call_wall if (levels.call_wall is not None and levels.call_wall > spot) else levels.call_wall_above
        scenarios.append(
            {
                "name": "Bearish Regime Shift",
                "trigger": f"{bearish_trigger:,.1f} 하향 이탈" if bearish_trigger is not None else "Zero Gamma 이탈",
                "target": f"{bearish_target:,.1f}" if bearish_target is not None else "-",
                "invalidation": f"{bearish_invalidation:,.1f}" if bearish_invalidation is not None else None,
                "note": "합산 감마 부호가 바뀌는 레벨(Zero Gamma). 규약이 맞다면 이 아래에서 딜러 헤지가 추세를 가속(Long→Short Gamma), 규약이 반대면 반대 해석. 위치 자체는 부호 규약에 불변",
            }
        )
    return scenarios
