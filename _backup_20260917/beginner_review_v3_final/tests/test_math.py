"""known-answer 테스트 스위트 (WORKPLAN2 D1). pytest 불필요 — 직접 실행:

    python tests/test_math.py

성공하면 exit 0, 하나라도 실패하면 상세 출력 후 exit 1.
각 테스트는 '독립 계산(유한차분/몬테카를로/완전탐색/손계산)'과 프로덕션 코드를 대조한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Windows 기본 콘솔(cp949)에서 유니코드(≈, — 등) 출력 시 UnicodeEncodeError 방지.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dealer_positioning import compute_max_pain  # noqa: E402
from greeks import _d1_d2, compute_greeks, probability_of_touch  # noqa: E402
from indicators import BREADTH_EMA_FAST, BREADTH_EMA_SLOW, _rolling_percentile_score  # noqa: E402

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _FAILURES.append(name)


def approx(a: float, b: float, rel: float = 1e-4, abs_: float = 1e-8) -> bool:
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


# ---------------------------------------------------------------------------
# 1. Black-Scholes 그릭스 vs 중심 유한차분 (Merton, 연속배당 q)
# ---------------------------------------------------------------------------
def _bs_price(S, K, T, sig, r, q, is_call):
    d1, d2 = _d1_d2(np.array([S]), np.array([K]), np.array([T]), np.array([sig]), r, q)
    from scipy.stats import norm

    d1, d2 = float(d1[0]), float(d2[0])
    if is_call:
        return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def test_greeks_vs_fd():
    S, K, T, sig, r, q = 350.0, 355.0, 20 / 365, 0.16, 0.032, 0.012
    for is_call in (True, False):
        g = compute_greeks(
            spot=[S], strike=[K], t_years=[T], sigma=[sig], is_call=[is_call], r=r, q=q
        )
        g = {k: float(v[0]) for k, v in g.items()}

        hS = S * 1e-4
        delta_fd = (_bs_price(S + hS, K, T, sig, r, q, is_call) - _bs_price(S - hS, K, T, sig, r, q, is_call)) / (2 * hS)
        gamma_fd = (_bs_price(S + hS, K, T, sig, r, q, is_call) - 2 * _bs_price(S, K, T, sig, r, q, is_call) + _bs_price(S - hS, K, T, sig, r, q, is_call)) / hS**2

        hv = 1e-5
        vega_fd = (_bs_price(S, K, T, sig + hv, r, q, is_call) - _bs_price(S, K, T, sig - hv, r, q, is_call)) / (2 * hv) / 100

        hT = 1e-6
        # theta = -dPrice/dT (시간이 흐르면 T 감소), /365 로 하루당
        theta_fd = -(_bs_price(S, K, T + hT, sig, r, q, is_call) - _bs_price(S, K, T - hT, sig, r, q, is_call)) / (2 * hT) / 365

        # vanna = d(delta)/d(sigma), /100 (IV 1%p 당)
        def delta_at(sv):
            return (_bs_price(S + hS, K, T, sv, r, q, is_call) - _bs_price(S - hS, K, T, sv, r, q, is_call)) / (2 * hS)

        vanna_fd = (delta_at(sig + hv) - delta_at(sig - hv)) / (2 * hv) / 100

        # charm = -d(delta)/dT, /365 (하루 경과당 델타 변화)
        def delta_atT(Tv):
            return (_bs_price(S + hS, K, Tv, sig, r, q, is_call) - _bs_price(S - hS, K, Tv, sig, r, q, is_call)) / (2 * hS)

        charm_fd = -(delta_atT(T + hT) - delta_atT(T - hT)) / (2 * hT) / 365

        side = "call" if is_call else "put"
        check(f"greeks/{side}: delta", approx(g["delta"], delta_fd, rel=1e-4), f"{g['delta']:.6f} vs {delta_fd:.6f}")
        check(f"greeks/{side}: gamma", approx(g["gamma"], gamma_fd, rel=1e-3), f"{g['gamma']:.6f} vs {gamma_fd:.6f}")
        check(f"greeks/{side}: vega", approx(g["vega"], vega_fd, rel=1e-4), f"{g['vega']:.6f} vs {vega_fd:.6f}")
        check(f"greeks/{side}: theta", approx(g["theta"], theta_fd, rel=1e-3), f"{g['theta']:.6f} vs {theta_fd:.6f}")
        check(f"greeks/{side}: vanna", approx(g["vanna"], vanna_fd, rel=1e-3), f"{g['vanna']:.6e} vs {vanna_fd:.6e}")
        check(f"greeks/{side}: charm", approx(g["charm"], charm_fd, rel=2e-3), f"{g['charm']:.6e} vs {charm_fd:.6e}")


def test_greeks_call_put_parity():
    """콜 델타 − 풋 델타 = e^{-qT} (같은 행사가), 콜/풋 감마·베가 동일."""
    S, K, T, sig, r, q = 350.0, 340.0, 33 / 365, 0.2, 0.03, 0.015
    gc = compute_greeks(spot=[S], strike=[K], t_years=[T], sigma=[sig], is_call=[True], r=r, q=q)
    gp = compute_greeks(spot=[S], strike=[K], t_years=[T], sigma=[sig], is_call=[False], r=r, q=q)
    check("parity: delta_c - delta_p = e^{-qT}", approx(float(gc["delta"][0] - gp["delta"][0]), np.exp(-q * T), rel=1e-9))
    check("parity: gamma_c = gamma_p", approx(float(gc["gamma"][0]), float(gp["gamma"][0]), rel=1e-12))
    check("parity: vega_c = vega_p", approx(float(gc["vega"][0]), float(gp["vega"][0]), rel=1e-12))
    check("parity: vanna_c = vanna_p", approx(float(gc["vanna"][0]), float(gp["vanna"][0]), rel=1e-12))


# ---------------------------------------------------------------------------
# 2. Probability of Touch
# ---------------------------------------------------------------------------
def test_pot_driftless_reduction():
    """μ=0 (r-q-σ²/2=0) 이면 PoT = 2·N(-|b|/(σ√T))."""
    from scipy.stats import norm

    sig, T = 0.2, 0.25
    r_q = 0.5 * sig**2  # r - q = σ²/2  →  drift μ = 0
    S, barrier = 100.0, 108.0
    pot = probability_of_touch(S, barrier, T, sig, r=r_q, q=0.0)
    b = abs(np.log(barrier / S))
    expected = 2 * norm.cdf(-b / (sig * np.sqrt(T)))
    check("PoT: driftless reduces to 2N(-|b|/σ√T)", approx(pot, expected, rel=1e-9), f"{pot:.6f} vs {expected:.6f}")


def test_pot_vs_montecarlo():
    S, barrier, T, sig, r, q = 350.0, 365.0, 30 / 365, 0.18, 0.03, 0.015
    pot = probability_of_touch(S, barrier, T, sig, r=r, q=q)

    rng = np.random.default_rng(42)
    n_paths, n_steps = 40000, 500
    dt = T / n_steps
    mu = r - q - 0.5 * sig**2
    logS = np.full(n_paths, np.log(S))
    hit = np.zeros(n_paths, dtype=bool)
    logB = np.log(barrier)
    for _ in range(n_steps):
        logS += mu * dt + sig * np.sqrt(dt) * rng.standard_normal(n_paths)
        hit |= logS >= logB
    mc = hit.mean()
    # 이산 모니터링이라 MC가 약간 낮게 편향됨 — 절대 3%p 이내면 통과
    check("PoT: vs Monte Carlo (±3%p, MC는 이산이라 하향 편향)", abs(pot - mc) < 0.03, f"analytic {pot:.4f} vs MC {mc:.4f}")


# ---------------------------------------------------------------------------
# 3. Max Pain — 잔존 OI 없는 깨끗한 체인에서는 windowed == 완전탐색
# ---------------------------------------------------------------------------
def test_maxpain_clean_chain_matches_bruteforce():
    import pandas as pd

    spot = 350.0
    strikes = np.arange(320.0, 381.0, 2.5)
    rng = np.random.default_rng(7)
    rows = []
    for k in strikes:
        # ATM 근처 OI가 큰 정규분포꼴 (잔존 딥ITM 없음)
        oi_c = max(1, int(2000 * np.exp(-((k - spot) ** 2) / (2 * 15**2)) + rng.integers(0, 50)))
        oi_p = max(1, int(2000 * np.exp(-((k - spot) ** 2) / (2 * 15**2)) + rng.integers(0, 50)))
        rows.append({"type": "C", "strike": k, "oi": oi_c})
        rows.append({"type": "P", "strike": k, "oi": oi_p})
    chain = pd.DataFrame(rows)

    # 완전탐색 표준 max pain (전 행사가·전 계약)
    calls = chain[chain["type"] == "C"][["strike", "oi"]].to_numpy()
    puts = chain[chain["type"] == "P"][["strike", "oi"]].to_numpy()
    pains = []
    for p in strikes:
        cp = np.sum(calls[:, 1] * np.maximum(p - calls[:, 0], 0))
        pp = np.sum(puts[:, 1] * np.maximum(puts[:, 0] - p, 0))
        pains.append(cp + pp)
    brute = float(strikes[int(np.argmin(pains))])

    windowed = compute_max_pain(chain, spot=spot)
    check("maxpain: windowed == 완전탐색 (깨끗한 체인)", approx(windowed, brute, abs_=2.5), f"windowed {windowed} vs brute {brute}")


# ---------------------------------------------------------------------------
# 4. McClellan Oscillator — EMA(19)-EMA(39), α = 2/(span+1)
# ---------------------------------------------------------------------------
def test_mcclellan_oscillator_by_hand():
    import pandas as pd

    check("mcclellan: span 상수", BREADTH_EMA_FAST == 19 and BREADTH_EMA_SLOW == 39)

    r = pd.Series([0.1, -0.2, 0.3, -0.1, 0.05, 0.2, -0.3, 0.15, 0.0, -0.05] * 30)
    a_f, a_s = 2 / (19 + 1), 2 / (39 + 1)

    def ema_by_hand(series, alpha):
        out = []
        prev = series.iloc[0]
        out.append(prev)
        for x in series.iloc[1:]:
            prev = alpha * x + (1 - alpha) * prev
            out.append(prev)
        return pd.Series(out, index=series.index)

    osc_hand = ema_by_hand(r, a_f) - ema_by_hand(r, a_s)
    osc_pandas = r.ewm(span=19, adjust=False).mean() - r.ewm(span=39, adjust=False).mean()
    check("mcclellan: pandas ewm(adjust=False) == 손계산 재귀 EMA", bool(np.allclose(osc_hand.to_numpy(), osc_pandas.to_numpy(), atol=1e-12)))


# ---------------------------------------------------------------------------
# 5. 롤링 백분위 점수 — 단조성 / invert 대칭
# ---------------------------------------------------------------------------
def test_percentile_score_monotone_and_invert():
    import pandas as pd

    s = pd.Series(np.linspace(0, 1, 400) + np.sin(np.linspace(0, 20, 400)) * 0.01)
    up = _rolling_percentile_score(s, window=252)
    down = _rolling_percentile_score(s, invert=True, window=252)
    valid = up.dropna().index
    # 순증가 시리즈 → 마지막 값은 자기 창에서 최상위여야 함 (≈100)
    check("percentile: 순증가 시리즈 최근값 ≈ 상위", up.iloc[-1] > 95, f"{up.iloc[-1]:.1f}")
    check("percentile: invert = 100 - 정방향 (겹치는 구간)", bool(np.allclose((up.loc[valid] + down.loc[valid]).to_numpy(), 100.0, atol=1e-9)))
    check("percentile: 범위 [0,100]", bool((up.dropna().between(0, 100).all())))


# ---------------------------------------------------------------------------
# 6. 합성선물(풋콜패리티) 왕복
# ---------------------------------------------------------------------------
def test_synthetic_forward_roundtrip():
    import pandas as pd

    from dealer_positioning import synthetic_forward_by_strike

    S, r, q, T = 350.0, 0.03, 0.02, 40 / 365
    strikes = np.array([330.0, 340.0, 350.0, 360.0, 370.0])
    from scipy.stats import norm

    def px(K, is_call):
        d1, d2 = _d1_d2(np.array([S]), np.array([K]), np.array([T]), np.array([0.2]), r, q)
        d1, d2 = float(d1[0]), float(d2[0])
        if is_call:
            return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)

    rows = []
    for k in strikes:
        rows.append({"type": "C", "strike": k, "close": px(k, True)})
        rows.append({"type": "P", "strike": k, "close": px(k, False)})
    chain = pd.DataFrame(rows)
    out = synthetic_forward_by_strike(chain, r, q, T)
    check("synthetic fwd: 모든 행사가에서 내재 스팟 ≈ 실제 스팟", bool(np.allclose(out["implied_spot"].to_numpy(), S, atol=1e-6)), f"{out['implied_spot'].to_numpy()}")


def main() -> int:
    for fn in [
        test_greeks_vs_fd,
        test_greeks_call_put_parity,
        test_pot_driftless_reduction,
        test_pot_vs_montecarlo,
        test_maxpain_clean_chain_matches_bruteforce,
        test_mcclellan_oscillator_by_hand,
        test_percentile_score_monotone_and_invert,
        test_synthetic_forward_roundtrip,
    ]:
        fn()
    print()
    if _FAILURES:
        print(f"{len(_FAILURES)} FAILED: {', '.join(_FAILURES)}")
        return 1
    print("모든 테스트 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
