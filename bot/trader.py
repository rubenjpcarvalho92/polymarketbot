from __future__ import annotations

from dataclasses import dataclass, field

from bot.execution import ExecutionEngine, OrderRequest, OrderSide, OrderStatus
from bot.order_manager import OrderManager
from bot.risk_manager import RiskManager
from strategies.base_strategy import BaseStrategy, Signal, StrategyContext, StrategyResult


@dataclass(slots=True)
class Position:
    market_id: str
    side: OrderSide
    size: float
    average_price: float
    strategy_name: str


@dataclass(slots=True)
class TraderState:
    positions: dict[str, Position] = field(default_factory=dict)


class Trader:
    def __init__(
        self,
        strategies: dict[str, BaseStrategy],
        execution_engine: ExecutionEngine | None = None,
        order_manager: OrderManager | None = None,
        risk_manager: RiskManager | None = None,
    ) -> None:
        self.strategies = strategies
        self.execution_engine = execution_engine or ExecutionEngine()
        self.order_manager = order_manager or OrderManager()
        self.risk_manager = risk_manager or RiskManager()
        self.state = TraderState()

    def process_market(
        self,
        strategy_name: str,
        context: StrategyContext,
        best_bid: float,
        best_ask: float,
        order_size: float = 10.0,
        token_id: str = "",
    ) -> StrategyResult:
        if strategy_name not in self.strategies:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        strategy = self.strategies[strategy_name]
        result = strategy.evaluate(context)

        if result.signal == Signal.HOLD:
            return result

        current_position = self.state.positions.get(context.market_id)

        # ------------------------------------------------------------
        # SELL = FECHAR TOTALMENTE A POSIÇÃO ATUAL
        # ------------------------------------------------------------
        if result.signal == Signal.SELL and current_position is not None and current_position.size > 0:
            close_side = current_position.side
            close_size = current_position.size

            limit_price = self._compute_limit_price_for_exit(
                side=close_side,
                best_bid=best_bid,
                best_ask=best_ask,
            )

            request = OrderRequest(
                market_id=context.market_id,
                side=close_side,
                price=limit_price,
                size=close_size,
                strategy_name=strategy_name,
                token_id=token_id,
            )

            order = self.execution_engine.place_limit_order(
                request=request,
                best_bid=best_bid,
                best_ask=best_ask,
            )

            self.order_manager.register_order(order)

            if order.status == OrderStatus.FILLED:
                self._close_position_from_fill(order)

            return StrategyResult(
                signal=result.signal,
                reason=result.reason,
                metadata={
                    **result.metadata,
                    "action": "close_full_position",
                    "order_id": order.order_id,
                    "order_status": order.status.value,
                    "limit_price": order.price,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "token_id": token_id,
                    "closed_size": close_size,
                    "position_side": close_side.value,
                },
            )

        # ------------------------------------------------------------
        # SEM POSIÇÃO PARA FECHAR -> NÃO FAZ SENTIDO VENDER
        # ------------------------------------------------------------
        if result.signal == Signal.SELL and current_position is None:
            return StrategyResult(
                signal=Signal.HOLD,
                reason="sell_signal_but_no_open_position",
                metadata={**result.metadata},
            )

        # ------------------------------------------------------------
        # ENTRADA NORMAL
        # ------------------------------------------------------------
        side_value = result.metadata.get("side")
        if side_value not in {"YES", "NO"}:
            return StrategyResult(signal=Signal.HOLD, reason="missing_side_metadata")

        order_side = OrderSide(side_value)

        market_exposure = self.get_market_exposure(context.market_id)
        total_exposure = self.get_total_exposure()
        open_orders_count = len(self.order_manager.get_open_orders())

        allowed, reason = self.risk_manager.can_place_order(
            market_exposure=market_exposure,
            total_exposure=total_exposure,
            open_orders_count=open_orders_count,
            order_size=order_size,
        )

        if not allowed:
            return StrategyResult(signal=Signal.HOLD, reason=f"risk_blocked:{reason}")

        limit_price = self._compute_limit_price(
            side=order_side,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        request = OrderRequest(
            market_id=context.market_id,
            side=order_side,
            price=limit_price,
            size=order_size,
            strategy_name=strategy_name,
            token_id=token_id,
        )

        order = self.execution_engine.place_limit_order(
            request=request,
            best_bid=best_bid,
            best_ask=best_ask,
        )

        self.order_manager.register_order(order)

        if order.status == OrderStatus.FILLED:
            self._update_position_from_fill(order)

        return StrategyResult(
            signal=result.signal,
            reason=result.reason,
            metadata={
                **result.metadata,
                "action": "open_position",
                "order_id": order.order_id,
                "order_status": order.status.value,
                "limit_price": order.price,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "token_id": token_id,
            },
        )

    def get_market_exposure(self, market_id: str) -> float:
        position = self.state.positions.get(market_id)
        return position.size if position else 0.0

    def get_total_exposure(self) -> float:
        return sum(position.size for position in self.state.positions.values())

    def _compute_limit_price(self, side: OrderSide, best_bid: float, best_ask: float) -> float:
        if side == OrderSide.YES:
            if best_bid > 0:
                return min(best_bid + 0.01, 0.99)
            return 0.50

        if best_ask > 0:
            return max(best_ask - 0.01, 0.01)
        return 0.50

    def _compute_limit_price_for_exit(self, side: OrderSide, best_bid: float, best_ask: float) -> float:
        # Para fechar posição, tenta usar o lado mais executável.
        if side == OrderSide.YES:
            if best_bid > 0:
                return best_bid
            return 0.50

        if best_ask > 0:
            return best_ask
        return 0.50

    def _update_position_from_fill(self, order) -> None:
        self.state.positions[order.market_id] = Position(
            market_id=order.market_id,
            side=order.side,
            size=order.filled_size,
            average_price=order.average_fill_price,
            strategy_name=order.strategy_name,
        )

    def _close_position_from_fill(self, order) -> None:
        if order.market_id in self.state.positions:
            del self.state.positions[order.market_id]