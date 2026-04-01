from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketScoreBreakdown:
    time_score: float
    liquidity_score: float
    spread_score: float
    price_score: float
    technical_score: float
    total_score: float


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_time_score(days_to_resolution: float) -> float:
    if 15 <= days_to_resolution <= 45:
        return 1.0
    if 45 < days_to_resolution <= 60:
        return 0.8
    if 7 <= days_to_resolution < 15:
        return 0.6
    return 0.0


def compute_price_score(mid_price: Optional[float]) -> float:
    if mid_price is None:
        return 0.0

    if 0.35 <= mid_price <= 0.80:
        return 1.0
    if 0.20 <= mid_price < 0.35:
        return 0.7
    if 0.80 < mid_price <= 0.90:
        return 0.5
    if 0.10 <= mid_price < 0.20:
        return 0.3
    return 0.0


def compute_spread_score(spread: Optional[float], max_spread_for_zero: float = 0.10) -> float:
    if spread is None:
        return 0.0
    if spread <= 0:
        return 1.0
    score = 1.0 - (spread / max_spread_for_zero)
    return clamp(score, 0.0, 1.0)


def compute_liquidity_score(liquidity: Optional[float], reference_liquidity: float = 10000.0) -> float:
    if liquidity is None or liquidity <= 0:
        return 0.0
    return clamp(liquidity / reference_liquidity, 0.0, 1.0)


def adjust_score_for_side_bias(raw_score: float, side: str, days_to_resolution: float) -> float:
    """
    Penalização ligeira do lado YES quando ainda faltam >= 15 dias.
    Inspirado no paper, mas mantido muito leve.
    """
    if side.upper() == "YES" and days_to_resolution >= 15:
        return raw_score - 0.03
    return raw_score


def compute_market_score(
    *,
    days_to_resolution: float,
    spread: Optional[float],
    mid_price: Optional[float],
    liquidity: Optional[float],
    technical_score: float = 0.5,
    side: str = "YES",
) -> MarketScoreBreakdown:
    """
    technical_score esperado entre 0.0 e 1.0
    """
    technical_score = clamp(technical_score, 0.0, 1.0)

    time_score = compute_time_score(days_to_resolution)
    price_score = compute_price_score(mid_price)
    spread_score = compute_spread_score(spread)
    liquidity_score = compute_liquidity_score(liquidity)

    raw_total = (
        time_score * 0.30
        + liquidity_score * 0.25
        + spread_score * 0.20
        + price_score * 0.15
        + technical_score * 0.10
    )

    adjusted_total = adjust_score_for_side_bias(raw_total, side=side, days_to_resolution=days_to_resolution)
    adjusted_total = clamp(adjusted_total, 0.0, 1.0)

    return MarketScoreBreakdown(
        time_score=time_score,
        liquidity_score=liquidity_score,
        spread_score=spread_score,
        price_score=price_score,
        technical_score=technical_score,
        total_score=adjusted_total,
    )