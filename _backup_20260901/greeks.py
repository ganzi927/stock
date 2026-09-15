"""Black-Scholes 옵션 그릭스 (KOSPI200 지수옵션, 배당수익률 q 반영).

KRX Open API는 가격/거래량/미결제약정/내재변동성(IV)만 제공하고 델타·감마 같은
그릭스는 주지 않는다. 이 모듈은 IV를 입력으로 받아 표준 Black-Scholes(76류) 공식으로
델타/감마/베가/세타/베가/바나/참을 직접 계산한다.

가정(명시적 근사):
- 무위험이자율 r, 배당수익률 q는 상수로 고정 (실제로는 만기별 변동)
- 유러피안 옵션, 배당연속지급 모형(Merton 확장 B-S)
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

RISK_FREE_RATE = 0.030   # 무위험이자율 가정 (3.0%)
DIVIDEND_YIELD = 0.015   # KOSPI200 배당수익률 가정 (1.5%)
CONTRACT_MULTIPLIER = 250_000  # KOSPI200 옵션 1계약당 25만원


def _d1_d2(spot: np.ndarray, strike: np.ndarray, t: np.ndarray, sigma: np.ndarray, r: float, q: float):
    sigma = np.clip(sigma, 1e-4, None)
    t = np.clip(t, 1e-6, None)
    d1 = (np.log(spot / strike) + (r - q + 0.5 * sigma**2) * t) / (sigma * np.sqrt(t))
    d2 = d1 - sigma * np.sqrt(t)
    return d1, d2


def compute_greeks(
    spot: np.ndarray,
    strike: np.ndarray,
    t_years: np.ndarray,
    sigma: np.ndarray,
    is_call: np.ndarray,
    r: float = RISK_FREE_RATE,
    q: float = DIVIDEND_YIELD,
) -> dict[str, np.ndarray]:
    """벡터화된 그릭스 계산. sigma는 소수(0.20=20%) 단위."""
    spot, strike, t_years, sigma = map(lambda x: np.asarray(x, dtype=float), (spot, strike, t_years, sigma))
    is_call = np.asarray(is_call, dtype=bool)

    d1, d2 = _d1_d2(spot, strike, t_years, sigma, r, q)
    disc_q = np.exp(-q * t_years)
    disc_r = np.exp(-r * t_years)
    pdf_d1 = norm.pdf(d1)

    delta = np.where(is_call, disc_q * norm.cdf(d1), disc_q * (norm.cdf(d1) - 1))
    gamma = disc_q * pdf_d1 / (spot * sigma * np.sqrt(t_years))
    vega = spot * disc_q * pdf_d1 * np.sqrt(t_years) / 100  # IV 1%p 변화당
    vanna = -disc_q * pdf_d1 * d2 / sigma / 100  # IV 1%p 변화당 델타 변화량

    theta_call = (
        -spot * disc_q * pdf_d1 * sigma / (2 * np.sqrt(t_years))
        - r * strike * disc_r * norm.cdf(d2)
        + q * spot * disc_q * norm.cdf(d1)
    ) / 365
    theta_put = (
        -spot * disc_q * pdf_d1 * sigma / (2 * np.sqrt(t_years))
        + r * strike * disc_r * norm.cdf(-d2)
        - q * spot * disc_q * norm.cdf(-d1)
    ) / 365
    theta = np.where(is_call, theta_call, theta_put)

    charm_common = disc_q * pdf_d1 * (2 * (r - q) * t_years - d2 * sigma * np.sqrt(t_years)) / (2 * t_years * sigma * np.sqrt(t_years))
    charm_call = q * disc_q * norm.cdf(d1) - charm_common
    charm_put = -q * disc_q * norm.cdf(-d1) - charm_common
    charm = np.where(is_call, charm_call, charm_put) / 365  # 하루 경과당 델타 변화량

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "vanna": vanna,
        "charm": charm,
    }


def probability_of_touch(spot: float, barrier: float, t_years: float, sigma: float, r: float = RISK_FREE_RATE, q: float = DIVIDEND_YIELD) -> float | None:
    """만기 전 스팟이 barrier를 한 번이라도 터치할 위험중립 확률(PoT).

    기하 브라운 운동(로그가격 X_t = (r-q-σ²/2)t + σW_t)의 드리프트가 있는
    브라운 운동에 대한 first-passage(첫 도달) 확률 공식(반사원리)을 그대로 적용한다.
    이 공식은 배리어 옵션 가격결정 이론의 표준 결과이며, 무위험이자율 r을 드리프트로
    쓰는 위험중립 확률이다(실제 확률이 아님 — 옵션 시장이 IV로 내재하고 있는 확률).

    검증: 드리프트=0(μ=0)일 때 2·N(-|b|/(σ√T))로 축약되는데, 이는 드리프트 없는
    브라운 운동에 대한 반사원리의 잘 알려진 결과와 정확히 일치한다.
    """
    if spot <= 0 or barrier <= 0 or t_years <= 0 or sigma <= 0:
        return None
    b = float(np.log(barrier / spot))
    if b == 0:
        return 1.0
    mu = r - q - 0.5 * sigma**2
    sqt = sigma * np.sqrt(t_years)
    if b > 0:
        term1 = norm.cdf((mu * t_years - b) / sqt)
        term2 = np.exp(2 * mu * b / sigma**2) * norm.cdf((-mu * t_years - b) / sqt)
    else:
        term1 = norm.cdf((b - mu * t_years) / sqt)
        term2 = np.exp(2 * mu * b / sigma**2) * norm.cdf((b + mu * t_years) / sqt)
    pot = float(term1 + term2)
    return min(max(pot, 0.0), 1.0)
