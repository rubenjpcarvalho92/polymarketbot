from __future__ import annotations

from strategies.base_strategy import BaseStrategy, Signal, StrategyContext, StrategyResult
from strategies.indicators import is_crossover_down, is_crossover_up, macd


class MacdClassicStrategy(BaseStrategy):
    def __init__(self, config: dict | None = None) -> None:
        super().__init__(name="macd_classic", config=config)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        closes = context.data.get("closes", [])
        if len(closes) < 35:
            return StrategyResult(signal=Signal.HOLD, reason="not_enough_data")

        result = macd(
            closes,
            fast_period=self.config.get("fast_period", 12),
            slow_period=self.config.get("slow_period", 26),
            signal_period=self.config.get("signal_period", 9),
        )

        macd_line = result["macd"]
        signal_line = result["signal"]

        if is_crossover_up(macd_line, signal_line):
            return StrategyResult(
                signal=Signal.BUY,
                reason="macd_bullish_crossover",
                metadata={"side": "YES"},
            )

        if is_crossover_down(macd_line, signal_line):
            return StrategyResult(
                signal=Signal.SELL,
                reason="macd_bearish_crossover",
                metadata={"side": "NO"},
            )

        return StrategyResult(signal=Signal.HOLD, reason="no_signal")