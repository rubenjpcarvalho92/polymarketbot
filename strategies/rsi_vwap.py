from __future__ import annotations

from strategies.base_strategy import BaseStrategy, Signal, StrategyContext, StrategyResult
from strategies.indicators import ema, rsi, vwap


class RsiVwapStrategy(BaseStrategy):
    def __init__(self, config: dict | None = None) -> None:
        super().__init__(name="rsi_vwap", config=config)

    def evaluate(self, context: StrategyContext) -> StrategyResult:
        highs = context.data.get("highs", [])
        lows = context.data.get("lows", [])
        closes = context.data.get("closes", [])
        volumes = context.data.get("volumes", [])

        if len(closes) < 20 or not (len(highs) == len(lows) == len(closes) == len(volumes)):
            return StrategyResult(signal=Signal.HOLD, reason="not_enough_data")

        rsi_period = self.config.get("rsi_period", 14)
        oversold = self.config.get("oversold", 30)
        overbought = self.config.get("overbought", 70)

        rsi_values = rsi(closes, rsi_period)
        vwap_values = vwap(highs, lows, closes, volumes)

        current_price = closes[-1]
        current_rsi = rsi_values[-1]
        current_vwap = vwap_values[-1]

        if current_price > 0.90:
            return StrategyResult(signal=Signal.HOLD, reason="price_too_high_for_yes")
        if current_price < 0.10:
            return StrategyResult(signal=Signal.HOLD, reason="price_too_low_for_no")

        bullish = current_price > current_vwap and current_rsi > oversold and rsi_values[-2] <= oversold
        bearish = current_price < current_vwap and current_rsi < overbought and rsi_values[-2] >= overbought

        if bullish:
            return StrategyResult(
                signal=Signal.BUY,
                reason="rsi_vwap_bullish",
                metadata={"side": "YES", "rsi": current_rsi, "vwap": current_vwap},
            )

        if bearish:
            return StrategyResult(
                signal=Signal.SELL,
                reason="rsi_vwap_bearish",
                metadata={"side": "NO", "rsi": current_rsi, "vwap": current_vwap},
            )

        return StrategyResult(signal=Signal.HOLD, reason="no_signal")