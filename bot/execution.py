from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from bot.config import AppConfig
from bot.polymarket_client import PolymarketClient


class OrderSide(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    STALE = "STALE"


@dataclass(slots=True)
class OrderRequest:
    market_id: str
    side: OrderSide
    price: float
    size: float
    strategy_name: str
    token_id: str = ""


@dataclass(slots=True)
class Order:
    order_id: str
    market_id: str
    side: OrderSide
    price: float
    size: float
    strategy_name: str
    status: OrderStatus
    created_at: str
    filled_size: float = 0.0
    average_fill_price: float = 0.0
    updated_at: Optional[str] = None
    token_id: str = ""
    live_response: Optional[dict] = None


class ExecutionEngine:
    """
    Supports:
    - paper mode: simulated immediate fills
    - live mode: real client call, but still controlled by DRY_RUN
    """

    def __init__(
        self,
        app_config: AppConfig | None = None,
        polymarket_client: PolymarketClient | None = None,
    ) -> None:
        self.app_config = app_config
        self.polymarket_client = polymarket_client
        self._order_counter = 0

    def place_limit_order(
        self,
        request: OrderRequest,
        best_bid: float,
        best_ask: float,
    ) -> Order:
        self._order_counter += 1
        now = datetime.now(timezone.utc).isoformat()

        order = Order(
            order_id=f"ord_{self._order_counter}",
            market_id=request.market_id,
            side=request.side,
            price=request.price,
            size=request.size,
            strategy_name=request.strategy_name,
            status=OrderStatus.OPEN,
            created_at=now,
            updated_at=now,
            token_id=request.token_id,
        )

        if request.size <= 0:
            order.status = OrderStatus.REJECTED
            return order

        if request.price <= 0 or request.price >= 1:
            order.status = OrderStatus.REJECTED
            return order

        mode = "paper"
        dry_run = True

        if self.app_config is not None:
            mode = self.app_config.trading.trading_mode
            dry_run = self.app_config.trading.dry_run

        # ------------------------------------------------------------
        # LIVE MODE
        # ------------------------------------------------------------
        if mode == "live" and not dry_run:
            if self.polymarket_client is None:
                order.status = OrderStatus.REJECTED
                order.live_response = {"error": "missing_polymarket_client"}
                return order

            if not request.token_id:
                order.status = OrderStatus.REJECTED
                order.live_response = {"error": "missing_token_id"}
                return order

            try:
                response = self.polymarket_client.place_limit_order(
                    token_id=request.token_id,
                    side=request.side.value,
                    price=request.price,
                    size=request.size,
                )
                order.live_response = {"response": response}
                order.status = OrderStatus.OPEN
                return order
            except Exception as exc:
                order.status = OrderStatus.REJECTED
                order.live_response = {"error": str(exc)}
                return order

        # ------------------------------------------------------------
        # PAPER MODE = IMMEDIATE FILL
        # ------------------------------------------------------------
        fill_price = self._get_paper_fill_price(
            side=request.side,
            request_price=request.price,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        order.status = OrderStatus.FILLED
        order.filled_size = request.size
        order.average_fill_price = fill_price
        order.updated_at = datetime.now(timezone.utc).isoformat()
        order.live_response = {
            "paper_fill": True,
            "best_bid": best_bid,
            "best_ask": best_ask,
        }

        return order

    def _get_paper_fill_price(
        self,
        side: OrderSide,
        request_price: float,
        best_bid: float,
        best_ask: float,
    ) -> float:
        if side == OrderSide.YES:
            if best_ask > 0:
                return best_ask
            if best_bid > 0:
                return best_bid
            return request_price

        if side == OrderSide.NO:
            if best_bid > 0:
                return best_bid
            if best_ask > 0:
                return best_ask
            return request_price

        return request_price

    def cancel_order(self, order: Order) -> Order:
        if order.status in {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return order

        if self.app_config is not None:
            mode = self.app_config.trading.trading_mode
            dry_run = self.app_config.trading.dry_run
        else:
            mode = "paper"
            dry_run = True

        if mode == "live" and not dry_run and self.polymarket_client and order.order_id:
            try:
                response = self.polymarket_client.cancel_order(order.order_id)
                order.live_response = {"cancel_response": response}
            except Exception as exc:
                order.live_response = {"cancel_error": str(exc)}

        order.status = OrderStatus.CANCELED
        order.updated_at = datetime.now(timezone.utc).isoformat()
        return order

    def mark_stale(self, order: Order) -> Order:
        if order.status == OrderStatus.OPEN:
            order.status = OrderStatus.STALE
            order.updated_at = datetime.now(timezone.utc).isoformat()
        return order