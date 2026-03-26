from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.execution import Order, OrderStatus


@dataclass(slots=True)
class OrderManagerConfig:
    stale_after_seconds: int = 30


class OrderManager:
    def __init__(self, config: OrderManagerConfig | None = None) -> None:
        self.config = config or OrderManagerConfig()
        self.orders: dict[str, Order] = {}

    def register_order(self, order: Order) -> None:
        self.orders[order.order_id] = order

    def get_order(self, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    def get_open_orders(self) -> list[Order]:
        return [order for order in self.orders.values() if order.status == OrderStatus.OPEN]

    def get_orders_by_market(self, market_id: str) -> list[Order]:
        return [order for order in self.orders.values() if order.market_id == market_id]

    def get_orders_by_strategy(self, strategy_name: str) -> list[Order]:
        return [order for order in self.orders.values() if order.strategy_name == strategy_name]

    def mark_stale_orders(self) -> list[Order]:
        now = datetime.now(timezone.utc)
        stale_orders: list[Order] = []

        for order in self.get_open_orders():
            created_at = self._parse_timestamp(order.created_at)
            age = now - created_at

            if age > timedelta(seconds=self.config.stale_after_seconds):
                order.status = OrderStatus.STALE
                order.updated_at = now.isoformat()
                stale_orders.append(order)

        return stale_orders

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> datetime:
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt