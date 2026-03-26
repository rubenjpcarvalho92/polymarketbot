from __future__ import annotations

from dataclasses import dataclass

from bot.execution import OrderSide


@dataclass(slots=True)
class SimulatedFill:
    filled: bool
    fill_price: float


class FillSimulator:
    def simulate(
        self,
        side: OrderSide,
        requested_price: float,
        candle_close: float,
    ) -> SimulatedFill:
        if side == OrderSide.YES:
            return SimulatedFill(
                filled=requested_price >= candle_close,
                fill_price=candle_close,
            )

        return SimulatedFill(
            filled=requested_price <= candle_close,
            fill_price=candle_close,
        )