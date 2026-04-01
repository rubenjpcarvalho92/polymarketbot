from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderManagerState:
    orders: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TraderState:
    positions: Dict[str, Any] = field(default_factory=dict)


class Trader:
    """
    Trader compatível com o resto do projeto atual.

    Esperado por run_paper.py:
      - Trader(strategies=..., execution_engine=...)
      - process_market(...)
      - order_manager
      - state
    """

    def __init__(
        self,
        *,
        strategies: Dict[str, Any],
        execution_engine: Any,
    ) -> None:
        self.strategies = strategies or {}
        self.execution_engine = execution_engine

        self.order_manager = getattr(execution_engine, "order_manager", None)
        if self.order_manager is None:
            self.order_manager = OrderManagerState()
        elif getattr(self.order_manager, "orders", None) is None:
            self.order_manager.orders = {}

        self.state = getattr(execution_engine, "state", None)
        if self.state is None:
            self.state = TraderState()
        elif getattr(self.state, "positions", None) is None:
            self.state.positions = {}

    def _normalize_signal(self, value: Any) -> Signal:
        if isinstance(value, Signal):
            return value

        text = str(value or "").strip().upper()
        if text == "BUY":
            return Signal.BUY
        if text == "SELL":
            return Signal.SELL
        return Signal.HOLD

    def _default_side_for_signal(self, signal: Signal) -> str:
        if signal == Signal.BUY:
            return "BUY"
        if signal == Signal.SELL:
            return "SELL"
        return ""

    def _coerce_strategy_result(self, raw_result: Any) -> StrategyResult:
        if raw_result is None:
            return StrategyResult(
                signal=Signal.HOLD,
                reason="strategy_returned_none",
                metadata={},
            )

        if isinstance(raw_result, StrategyResult):
            raw_result.signal = self._normalize_signal(raw_result.signal)
            if raw_result.metadata is None:
                raw_result.metadata = {}
            return raw_result

        signal = self._normalize_signal(getattr(raw_result, "signal", None))
        reason = str(getattr(raw_result, "reason", "unknown_strategy_reason") or "unknown_strategy_reason")
        metadata = getattr(raw_result, "metadata", {}) or {}

        if not isinstance(metadata, dict):
            metadata = {"raw_metadata": metadata}

        return StrategyResult(
            signal=signal,
            reason=reason,
            metadata=metadata,
        )

    def _run_strategy(
        self,
        *,
        strategy_name: str,
        context: Any,
    ) -> StrategyResult:
        strategy = self.strategies.get(strategy_name)
        if strategy is None:
            return StrategyResult(
                signal=Signal.HOLD,
                reason=f"unknown_strategy:{strategy_name}",
                metadata={},
            )

        raw_result = None

        if hasattr(strategy, "generate_signal"):
            raw_result = strategy.generate_signal(context)
        elif hasattr(strategy, "evaluate"):
            raw_result = strategy.evaluate(context)
        elif hasattr(strategy, "process"):
            raw_result = strategy.process(context)
        elif hasattr(strategy, "run"):
            raw_result = strategy.run(context)
        else:
            return StrategyResult(
                signal=Signal.HOLD,
                reason=f"strategy_has_no_supported_entrypoint:{strategy_name}",
                metadata={},
            )

        return self._coerce_strategy_result(raw_result)

    def _build_hold_result(
        self,
        *,
        strategy_result: StrategyResult,
        token_id: str,
        best_bid: float,
        best_ask: float,
        order_size: float,
    ) -> StrategyResult:
        metadata = dict(strategy_result.metadata or {})
        metadata.setdefault("token_id", token_id)
        metadata.setdefault("best_bid", best_bid)
        metadata.setdefault("best_ask", best_ask)
        metadata.setdefault("order_size_requested", order_size)
        metadata.setdefault("order_status", "NONE")

        return StrategyResult(
            signal=Signal.HOLD,
            reason=strategy_result.reason,
            metadata=metadata,
        )

    def _execute_signal(
        self,
        *,
        signal_result: StrategyResult,
        token_id: str,
        best_bid: float,
        best_ask: float,
        order_size: float,
    ) -> StrategyResult:
        metadata = dict(signal_result.metadata or {})
        metadata.setdefault("token_id", token_id)
        metadata.setdefault("best_bid", best_bid)
        metadata.setdefault("best_ask", best_ask)
        metadata.setdefault("order_size_requested", order_size)
        metadata.setdefault("side", self._default_side_for_signal(signal_result.signal))
        metadata.setdefault("position_side", metadata.get("side", ""))

        if self.execution_engine is None:
            metadata.setdefault("order_status", "NOT_EXECUTED")
            return StrategyResult(
                signal=signal_result.signal,
                reason=signal_result.reason,
                metadata=metadata,
            )

        try:
            if hasattr(self.execution_engine, "execute_signal"):
                executed = self.execution_engine.execute_signal(
                    signal=signal_result.signal.value,
                    token_id=token_id,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    order_size=order_size,
                    metadata=metadata,
                )
                return self._merge_execution_result(signal_result, executed, metadata)

            if hasattr(self.execution_engine, "execute_trade"):
                executed = self.execution_engine.execute_trade(
                    signal=signal_result.signal.value,
                    token_id=token_id,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    order_size=order_size,
                    metadata=metadata,
                )
                return self._merge_execution_result(signal_result, executed, metadata)

            if hasattr(self.execution_engine, "place_order"):
                side = metadata.get("side") or metadata.get("position_side") or signal_result.signal.value
                executed = self.execution_engine.place_order(
                    token_id=token_id,
                    side=side,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    size=order_size,
                    metadata=metadata,
                )
                return self._merge_execution_result(signal_result, executed, metadata)

        except Exception as exc:
            metadata["order_status"] = "ERROR"
            metadata["execution_error"] = str(exc)
            return StrategyResult(
                signal=signal_result.signal,
                reason=f"{signal_result.reason}|execution_error",
                metadata=metadata,
            )

        metadata.setdefault("order_status", "NOT_EXECUTED")
        return StrategyResult(
            signal=signal_result.signal,
            reason=signal_result.reason,
            metadata=metadata,
        )

    def _merge_execution_result(
        self,
        strategy_result: StrategyResult,
        executed: Any,
        fallback_metadata: Dict[str, Any],
    ) -> StrategyResult:
        if executed is None:
            metadata = dict(fallback_metadata)
            metadata.setdefault("order_status", "NONE")
            return StrategyResult(
                signal=strategy_result.signal,
                reason=strategy_result.reason,
                metadata=metadata,
            )

        if isinstance(executed, StrategyResult):
            executed.signal = self._normalize_signal(executed.signal)
            executed.metadata = executed.metadata or {}
            executed.metadata.setdefault("order_status", "UNKNOWN")
            return executed

        if hasattr(executed, "signal") and hasattr(executed, "reason"):
            coerced = self._coerce_strategy_result(executed)
            coerced.metadata = coerced.metadata or {}
            coerced.metadata.setdefault("order_status", "UNKNOWN")
            return coerced

        metadata = dict(fallback_metadata)
        if isinstance(executed, dict):
            metadata.update(executed)
        else:
            metadata["raw_execution_result"] = executed

        metadata.setdefault("order_status", "UNKNOWN")

        return StrategyResult(
            signal=strategy_result.signal,
            reason=strategy_result.reason,
            metadata=metadata,
        )

    def process_market(
        self,
        *,
        strategy_name: str,
        context: Any,
        best_bid: float,
        best_ask: float,
        order_size: float,
        token_id: str,
    ) -> StrategyResult:
        strategy_result = self._run_strategy(
            strategy_name=strategy_name,
            context=context,
        )

        metadata = dict(strategy_result.metadata or {})
        metadata.setdefault("token_id", token_id)
        metadata.setdefault("best_bid", best_bid)
        metadata.setdefault("best_ask", best_ask)
        metadata.setdefault("order_size_requested", order_size)
        strategy_result.metadata = metadata

        if strategy_result.signal == Signal.HOLD:
            return self._build_hold_result(
                strategy_result=strategy_result,
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                order_size=order_size,
            )

        return self._execute_signal(
            signal_result=strategy_result,
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            order_size=order_size,
        )