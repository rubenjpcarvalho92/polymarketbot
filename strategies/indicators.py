from __future__ import annotations


def sma(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be > 0")

    result: list[float] = []
    for i in range(len(values)):
        if i + 1 < period:
            result.append(0.0)
        else:
            window = values[i + 1 - period : i + 1]
            result.append(sum(window) / period)
    return result


def ema(values: list[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if not values:
        return []

    multiplier = 2 / (period + 1)
    result: list[float] = [values[0]]

    for i in range(1, len(values)):
        current = (values[i] - result[-1]) * multiplier + result[-1]
        result.append(current)

    return result


def macd(
    values: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, list[float]]:
    if not values:
        return {"macd": [], "signal": [], "histogram": []}

    fast_ema = ema(values, fast_period)
    slow_ema = ema(values, slow_period)

    macd_line = [fast_ema[i] - slow_ema[i] for i in range(len(values))]
    signal_line = ema(macd_line, signal_period)
    histogram = [macd_line[i] - signal_line[i] for i in range(len(values))]

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def rsi(values: list[float], period: int = 14) -> list[float]:
    if period <= 0:
        raise ValueError("period must be > 0")
    if len(values) < 2:
        return [0.0 for _ in values]

    gains: list[float] = [0.0]
    losses: list[float] = [0.0]

    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(abs(min(delta, 0.0)))

    avg_gains = sma(gains, period)
    avg_losses = sma(losses, period)

    rsi_values: list[float] = []
    for i in range(len(values)):
        if i + 1 < period:
            rsi_values.append(0.0)
            continue

        gain = avg_gains[i]
        loss = avg_losses[i]

        if loss == 0:
            rsi_values.append(100.0)
            continue

        rs = gain / loss
        rsi_values.append(100 - (100 / (1 + rs)))

    return rsi_values


def vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float],
) -> list[float]:
    if not (len(highs) == len(lows) == len(closes) == len(volumes)):
        raise ValueError("All input lists must have the same length")

    cumulative_price_volume = 0.0
    cumulative_volume = 0.0
    result: list[float] = []

    for high, low, close, volume in zip(highs, lows, closes, volumes):
        typical_price = (high + low + close) / 3.0
        cumulative_price_volume += typical_price * volume
        cumulative_volume += volume

        if cumulative_volume == 0:
            result.append(0.0)
        else:
            result.append(cumulative_price_volume / cumulative_volume)

    return result


def histogram_slope(histogram: list[float]) -> float:
    if len(histogram) < 2:
        return 0.0
    return histogram[-1] - histogram[-2]


def is_crossover_up(series_a: list[float], series_b: list[float]) -> bool:
    if len(series_a) < 2 or len(series_b) < 2:
        return False
    return series_a[-2] <= series_b[-2] and series_a[-1] > series_b[-1]


def is_crossover_down(series_a: list[float], series_b: list[float]) -> bool:
    if len(series_a) < 2 or len(series_b) < 2:
        return False
    return series_a[-2] >= series_b[-2] and series_a[-1] < series_b[-1]