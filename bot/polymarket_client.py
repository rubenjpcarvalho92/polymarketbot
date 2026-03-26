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
    """
    Thin wrapper around py-clob-client.

    This file is written to be safe:
    - it only imports py-clob-client lazily
    - it supports public read methods without forcing real trading
    - order placement is available but controlled by execution mode
    """

    def __init__(self, config: PolymarketConfig) -> None:
        self.config = config
        self._client: Any | None = None

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from py_clob_client.client import ClobClient
        except ImportError as exc:
            raise ImportError(
                "py-clob-client is not installed. Install it before using PolymarketClient."
            ) from exc

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

    def get_markets(self) -> Any:
        client = self._ensure_client()
        if hasattr(client, "get_markets"):
            return client.get_markets()
        raise NotImplementedError("This py-clob-client version does not expose get_markets().")

    def get_order_book(self, token_id: str) -> PolymarketOrderBook:
        client = self._ensure_client()

        if hasattr(client, "get_order_book"):
            book = client.get_order_book(token_id)
        elif hasattr(client, "get_orderbook"):
            book = client.get_orderbook(token_id)
        else:
            raise NotImplementedError("This py-clob-client version does not expose order book methods.")

        best_bid = 0.0
        best_ask = 0.0
        bid_size = 0.0
        ask_size = 0.0

        bids = []
        asks = []

        if isinstance(book, dict):
            bids = book.get("bids", []) or []
            asks = book.get("asks", []) or []

        if bids:
            top_bid = bids[0]
            if isinstance(top_bid, dict):
                best_bid = float(top_bid.get("price", 0.0) or 0.0)
                bid_size = float(top_bid.get("size", 0.0) or 0.0)

        if asks:
            top_ask = asks[0]
            if isinstance(top_ask, dict):
                best_ask = float(top_ask.get("price", 0.0) or 0.0)
                ask_size = float(top_ask.get("size", 0.0) or 0.0)

        return PolymarketOrderBook(
            token_id=token_id,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
        )

    def place_limit_order(
        self,
        token_id: str,
        side: str,
        price: float,
        size: float,
    ) -> Any:
        client = self._ensure_client()

        if hasattr(client, "create_order"):
            return client.create_order(
                token_id=token_id,
                side=side,
                price=price,
                size=size,
            )

        raise NotImplementedError("This py-clob-client version does not expose create_order().")

    def cancel_order(self, order_id: str) -> Any:
        client = self._ensure_client()

        if hasattr(client, "cancel"):
            return client.cancel(order_id)
        if hasattr(client, "cancel_order"):
            return client.cancel_order(order_id)

        raise NotImplementedError("This py-clob-client version does not expose cancel methods.")