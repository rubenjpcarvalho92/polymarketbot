from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backtesting.fill_simulator import FillSimulator
from backtesting.metrics import BacktestMetrics, BacktestMetricsCalculator, BacktestTrade
from bot.execution import OrderSide
from data.candles import Candle
from strategies.base_strategy import BaseStrategy, Signal, StrategyContext


@dataclass(slots=True)
class OpenBacktestPosition:
    market_id: str
    side: OrderSide
    entry_timestamp: str
    entry_price: float
    size: float
    strategy_name: str


class BacktestEngine:
    def __init__(
        self,
        strategy: BaseStrategy,
        fill_simulator: FillSimulator | None = None,
        order_size: float = 10.0,
    ) -> None:
        self.strategy = strategy
        self.fill_simulator = fill_simulator or FillSimulator()
        self.order_size = order_size
        self.metrics_calculator = BacktestMetricsCalculator()

    def run(self, market_id: str, candles: Iterable[Candle]) -> BacktestMetrics:
        candles = list(candles)
        position: OpenBacktestPosition | None = None

        for i in range(len(candles)):
            history = candles[: i + 1]
            candle = candles[i]

            context = StrategyContext(
                market_id=market_id,
                timestamp=candle.timestamp,
                data={
                    "highs": [c.high for c in history],
                    "lows": [c.low for c in history],
                    "closes": [c.close for c in history],
                    "volumes": [c.volume for c in history],
                },
            )

            result = self.strategy.evaluate(context)

            if position is None:
                if result.signal == Signal.BUY:
                    position = OpenBacktestPosition(
                        market_id=market_id,
                        side=OrderSide.YES,
                        entry_timestamp=candle.timestamp,
                        entry_price=candle.close,
                        size=self.order_size,
                        strategy_name=self.strategy.name,
                    )

                elif result.signal == Signal.SELL:
                    position = OpenBacktestPosition(
                        market_id=market_id,
                        side=OrderSide.NO,
                        entry_timestamp=candle.timestamp,
                        entry_price=candle.close,
                        size=self.order_size,
                        strategy_name=self.strategy.name,
                    )

            else:
                should_exit = (
                    (position.side == OrderSide.YES and result.signal == Signal.SELL)
                    or (position.side == OrderSide.NO and result.signal == Signal.BUY)
                )

                if should_exit:
                    exit_price = candle.close

                    pnl = (
                        (exit_price - position.entry_price) * position.size
                        if position.side == OrderSide.YES
                        else (position.entry_price - exit_price) * position.size
                    )

                    self.metrics_calculator.add_trade(
                        BacktestTrade(
                            market_id=position.market_id,
                            strategy_name=position.strategy_name,
                            side=position.side.value,
                            entry_timestamp=position.entry_timestamp,
                            exit_timestamp=candle.timestamp,
                            entry_price=position.entry_price,
                            exit_price=exit_price,
                            size=position.size,
                            pnl=pnl,
                        )
                    )

                    position = None

        return self.metrics_calculator.build()