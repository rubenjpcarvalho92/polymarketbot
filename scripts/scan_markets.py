from __future__ import annotations

from typing import Any

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_market_question(market: Any) -> str:
    if isinstance(market, dict):
        return (
            market.get("question")
            or market.get("title")
            or market.get("description")
            or "N/A"
        )
    return (
        getattr(market, "question", None)
        or getattr(market, "title", None)
        or getattr(market, "description", None)
        or "N/A"
    )


def extract_tokens(market: Any) -> list[dict[str, Any]]:
    if isinstance(market, dict):
        tokens = market.get("tokens") or market.get("outcomes") or []
    else:
        tokens = getattr(market, "tokens", None) or getattr(market, "outcomes", None) or []

    normalized: list[dict[str, Any]] = []

    for token in tokens:
        if isinstance(token, dict):
            token_id = (
                token.get("token_id")
                or token.get("tokenId")
                or token.get("id")
                or token.get("asset_id")
            )
            label = (
                token.get("outcome")
                or token.get("name")
                or token.get("label")
                or ""
            )
        else:
            token_id = (
                getattr(token, "token_id", None)
                or getattr(token, "tokenId", None)
                or getattr(token, "id", None)
                or getattr(token, "asset_id", None)
            )
            label = (
                getattr(token, "outcome", None)
                or getattr(token, "name", None)
                or getattr(token, "label", None)
                or ""
            )

        if token_id:
            normalized.append(
                {
                    "token_id": str(token_id),
                    "label": str(label),
                }
            )

    return normalized


def is_interesting(best_bid: float, best_ask: float, liquidity: float) -> bool:
    if best_bid <= 0 or best_ask <= 0:
        return False
    if best_ask <= best_bid:
        return False

    spread = best_ask - best_bid

    if spread > 0.03:
        return False
    if liquidity < 10000:
        return False
    if best_bid < 0.05:
        return False
    if best_ask > 0.95:
        return False

    return True


def score_market(best_bid: float, best_ask: float, liquidity: float) -> float:
    spread = best_ask - best_bid
    if spread <= 0:
        return 0.0
    return liquidity / spread


def main() -> None:
    config = load_config()
    client = PolymarketClient(config.polymarket)

    print("Fetching markets...")
    markets = client.get_markets()

    if isinstance(markets, dict):
        market_items = (
            markets.get("data")
            or markets.get("markets")
            or markets.get("items")
            or []
        )
    else:
        market_items = markets or []

    results: list[dict[str, Any]] = []

    for market in market_items:
        question = extract_market_question(market)
        tokens = extract_tokens(market)

        for token in tokens:
            token_id = token["token_id"]
            label = token["label"]

            try:
                book = client.get_order_book(token_id)
            except Exception:
                continue

            best_bid = to_float(book.best_bid)
            best_ask = to_float(book.best_ask)
            bid_size = to_float(book.bid_size)
            ask_size = to_float(book.ask_size)
            liquidity = bid_size + ask_size

            if not is_interesting(best_bid, best_ask, liquidity):
                continue

            results.append(
                {
                    "question": question,
                    "label": label,
                    "token_id": token_id,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "spread": best_ask - best_bid,
                    "bid_size": bid_size,
                    "ask_size": ask_size,
                    "liquidity": liquidity,
                    "score": score_market(best_bid, best_ask, liquidity),
                }
            )

    results.sort(key=lambda x: x["score"], reverse=True)

    print()
    print("TOP 10 MARKETS")
    print("=" * 80)

    for i, item in enumerate(results[:10], start=1):
        print(f"{i}. {item['question']}")
        print(f"   outcome   : {item['label']}")
        print(f"   token_id  : {item['token_id']}")
        print(f"   best_bid  : {item['best_bid']:.4f}")
        print(f"   best_ask  : {item['best_ask']:.4f}")
        print(f"   spread    : {item['spread']:.4f}")
        print(f"   bid_size  : {item['bid_size']:.2f}")
        print(f"   ask_size  : {item['ask_size']:.2f}")
        print(f"   liquidity : {item['liquidity']:.2f}")
        print(f"   score     : {item['score']:.2f}")
        print("-" * 80)

    if not results:
        print("No interesting markets found with current filters.")


if __name__ == "__main__":
    main()