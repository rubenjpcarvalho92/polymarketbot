from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.config import PolymarketConfig


@dataclass(slots=True)
class PolymarketOrderBook:
    token_id: str
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float


class PolymarketClient:
    def __init__(self, config: PolymarketConfig) -> None:
        self.config = config
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        from py_clob_client.client import ClobClient

        client = ClobClient(
            host=self.config.host,
            chain_id=self.config.chain_id,
            key=self.config.private_key if self.config.private_key else None,
        )

        self._client = client
        return self._client

    def ping(self) -> bool:
        client = self._ensure_client()
        return client is not None

    def get_markets(self, next_cursor: str = "MA==") -> Any:
        client = self._ensure_client()

        if hasattr(client, "get_markets"):
            try:
                return client.get_markets(next_cursor)
            except TypeError:
                return client.get_markets()

        raise NotImplementedError

    def get_order_book(self, token_id: str) -> PolymarketOrderBook:
        client = self._ensure_client()

        if hasattr(client, "get_order_book"):
            book = client.get_order_book(token_id)
        elif hasattr(client, "get_orderbook"):
            book = client.get_orderbook(token_id)
        else:
            raise NotImplementedError

        best_bid = 0.0
        best_ask = 0.0
        bid_size = 0.0
        ask_size = 0.0

        bids = []
        asks = []

        if hasattr(book, "bids") and hasattr(book, "asks"):
            bids = book.bids or []
            asks = book.asks or []

            if bids:
                best_bid_order = max(bids, key=lambda x: float(x.price))
                best_bid = float(best_bid_order.price or 0.0)
                bid_size = float(best_bid_order.size or 0.0)

            if asks:
                best_ask_order = min(asks, key=lambda x: float(x.price))
                best_ask = float(best_ask_order.price or 0.0)
                ask_size = float(best_ask_order.size or 0.0)

        elif isinstance(book, dict):
            bids = book.get("bids", []) or []
            asks = book.get("asks", []) or []

            if bids:
                best_bid_order = max(bids, key=lambda x: float(x.get("price", 0.0) or 0.0))
                best_bid = float(best_bid_order.get("price", 0.0) or 0.0)
                bid_size = float(best_bid_order.get("size", 0.0) or 0.0)

            if asks:
                best_ask_order = min(asks, key=lambda x: float(x.get("price", 0.0) or 0.0))
                best_ask = float(best_ask_order.get("price", 0.0) or 0.0)
                ask_size = float(best_ask_order.get("size", 0.0) or 0.0)

        return PolymarketOrderBook(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
        )

    def place_limit_order(self, token_id: str, side: str, price: float, size: float) -> Any:
        client = self._ensure_client()

        if hasattr(client, "create_order"):
            return client.create_order(
                token_id=token_id,
                side=side,
                price=price,
                size=size,
            )

        raise NotImplementedError

    def cancel_order(self, order_id: str) -> Any:
        client = self._ensure_client()

        if hasattr(client, "cancel"):
            return client.cancel(order_id)
        if hasattr(client, "cancel_order"):
            return client.cancel_order(order_id)

        raise NotImplementedError