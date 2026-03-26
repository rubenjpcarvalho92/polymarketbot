from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OrderBookSnapshot:
    market_id: str
    timestamp: str
    best_bid: float
    best_ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def midpoint(self) -> float:
        if self.best_bid <= 0 or self.best_ask <= 0:
            return 0.0
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread(self) -> float:
        if self.best_bid <= 0 or self.best_ask <= 0:
            return 0.0
        return self.best_ask - self.best_bid

    @property
    def top_book_depth(self) -> float:
        return self.bid_size + self.ask_size


def snapshot_from_dict(payload: dict[str, Any]) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        market_id=str(payload.get("market_id", "")),
        timestamp=str(payload.get("timestamp", "")),
        best_bid=float(payload.get("best_bid", 0.0) or 0.0),
        best_ask=float(payload.get("best_ask", 0.0) or 0.0),
        bid_size=float(payload.get("bid_size", 0.0) or 0.0),
        ask_size=float(payload.get("ask_size", 0.0) or 0.0),
    )