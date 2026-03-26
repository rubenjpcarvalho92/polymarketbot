from __future__ import annotations

from strategies.base_strategy import BaseStrategy, Signal, StrategyContext, StrategyResult
from strategies.indicators import ema, histogram_slope, is_crossover_down, is_crossover_up, macd
from strategies.support_resistance import near_level, rolling_resistance, rolling_support


class MacdRefinedStrategy(BaseStrategy):
    def __init__(self, config: dict | None = None) -> None:
        super().__init__(name="macd_refined", config=config)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        closes = context.data.get("closes", [])
        if len(closes) < 200:
            return StrategyResult(signal=Signal.HOLD, reason="not_enough_data")

        ma200 = ema(closes, self.config.get("ma_period", 200))
        current_price = closes[-1]
        current_ma200 = ma200[-1]

        if current_price <= 0 or current_ma200 <= 0:
            return StrategyResult(signal=Signal.HOLD, reason="invalid_price")

        macd_result = macd(
            closes,
            fast_period=self.config.get("fast_period", 12),
            slow_period=self.config.get("slow_period", 26),
            signal_period=self.config.get("signal_period", 9),
        )

        macd_line = macd_result["macd"]
        signal_line = macd_result["signal"]
        histogram = macd_result["histogram"]

        support = rolling_support(closes, self.config.get("sr_lookback", 10))[-1]
        resistance = rolling_resistance(closes, self.config.get("sr_lookback", 10))[-1]
        tolerance = self.config.get("sr_tolerance", 0.02)

        distance_from_ma = abs(current_price - current_ma200)
        min_distance_from_ma = self.config.get("min_distance_from_ma", 0.01)

        if distance_from_ma < min_distance_from_ma:
            return StrategyResult(signal=Signal.HOLD, reason="too_close_to_ma200")

        if current_price > 0.90:
            return StrategyResult(signal=Signal.HOLD, reason="price_too_high_for_yes")
        if current_price < 0.10:
            return StrategyResult(signal=Signal.HOLD, reason="price_too_low_for_no")

        hist_slope = histogram_slope(histogram)

        bullish = (
            current_price > current_ma200
            and is_crossover_up(macd_line, signal_line)
            and hist_slope > 0
            and near_level(current_price, support, tolerance)
        )

        bearish = (
            current_price < current_ma200
            and is_crossover_down(macd_line, signal_line)
            and hist_slope < 0
            and near_level(current_price, resistance, tolerance)
        )

        if bullish:
            return StrategyResult(
                signal=Signal.BUY,
                reason="refined_macd_bullish",
                metadata={"side": "YES", "support": support, "ma200": current_ma200},
            )

        if bearish:
            return StrategyResult(
                signal=Signal.SELL,
                reason="refined_macd_bearish",
                metadata={"side": "NO", "resistance": resistance, "ma200": current_ma200},
            )

        return StrategyResult(signal=Signal.HOLD, reason="no_signal")