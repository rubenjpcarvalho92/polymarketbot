from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(slots=True)
class StrategyContext:
    market_id: str
    timestamp: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyResult:
    signal: Signal
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    def __init__(self, name: str, config: dict[str, Any] | None = None) -> None:
        self.name = name
        self.config = config or {}

    @abstractmethod
    def evaluate(self, context: StrategyContext) -> StrategyResult:
        raise NotImplementedError