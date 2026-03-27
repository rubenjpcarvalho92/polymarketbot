from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RiskLimits:
    max_position_per_market: float = 100.0
    max_total_exposure: float = 500.0
    max_open_orders: int = 10
    max_daily_loss: float = 100.0
    max_consecutive_losses: int = 3


class RiskManager:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.daily_realized_pnl: float = 0.0
        self.consecutive_losses: int = 0

    def can_place_order(
        self,
        market_exposure: float,
        total_exposure: float,
        open_orders_count: int,
        order_size: float,
    ) -> tuple[bool, str]:
        if order_size <= 0:
            return False, "invalid_order_size"

        if open_orders_count >= self.limits.max_open_orders:
            return False, "max_open_orders_reached"

        if market_exposure + order_size > self.limits.max_position_per_market:
            return False, "max_position_per_market_exceeded"

        if total_exposure + order_size > self.limits.max_total_exposure:
            return False, "max_total_exposure_exceeded"

        if abs(self.daily_realized_pnl) >= self.limits.max_daily_loss and self.daily_realized_pnl < 0:
            return False, "max_daily_loss_reached"

        if self.consecutive_losses >= self.limits.max_consecutive_losses:
            return False, "max_consecutive_losses_reached"

        return True, "ok"

    def register_closed_trade(self, pnl: float) -> None:
        self.daily_realized_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        elif pnl > 0:
            self.consecutive_losses = 0