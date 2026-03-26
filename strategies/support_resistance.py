from __future__ import annotations


def rolling_support(closes: list[float], lookback: int = 10) -> list[float]:
    if lookback <= 0:
        raise ValueError("lookback must be > 0")

    result: list[float] = []
    for i in range(len(closes)):
        start = max(0, i + 1 - lookback)
        window = closes[start : i + 1]
        result.append(min(window) if window else 0.0)
    return result


def rolling_resistance(closes: list[float], lookback: int = 10) -> list[float]:
    if lookback <= 0:
        raise ValueError("lookback must be > 0")

    result: list[float] = []
    for i in range(len(closes)):
        start = max(0, i + 1 - lookback)
        window = closes[start : i + 1]
        result.append(max(window) if window else 0.0)
    return result


def near_level(price: float, level: float, tolerance: float = 0.02) -> bool:
    if level <= 0:
        return False
    return abs(price - level) <= tolerance