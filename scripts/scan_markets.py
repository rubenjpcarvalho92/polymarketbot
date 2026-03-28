from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


def has_valid_book(best_bid: float, best_ask: float) -> bool:
    return best_bid > 0 and best_ask > 0 and best_ask > best_bid


def is_interesting(best_bid: float, best_ask: float, liquidity: float) -> bool:
    if not has_valid_book(best_bid, best_ask):
        return False

    spread = best_ask - best_bid

    # filtros mais relaxados para diagnóstico
    if spread > 0.08:
        return False
    if liquidity < 1000:
        return False
    if best_bid < 0.02:
        return False
    if best_ask > 0.98:
        return False

    return True


def score_market(best_bid: float, best_ask: float, liquidity: float) -> float:
    spread = best_ask - best_bid
    if spread <= 0:
        return 0.0
    return liquidity / spread


def print_market_block(index: int, item: dict[str, Any]) -> None:
    print(f"{index}. {item['question']}")
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

    all_results: list[dict[str, Any]] = []
    filtered_results: list[dict[str, Any]] = []

    scanned_markets = 0
    scanned_tokens = 0
    valid_books = 0

    for market in market_items:
        scanned_markets += 1
        question = extract_market_question(market)
        tokens = extract_tokens(market)

        for token in tokens:
            scanned_tokens += 1

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

            if not has_valid_book(best_bid, best_ask):
                continue

            valid_books += 1

            item = {
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

            all_results.append(item)

            if is_interesting(best_bid, best_ask, liquidity):
                filtered_results.append(item)

    filtered_results.sort(key=lambda x: x["score"], reverse=True)
    by_liquidity = sorted(all_results, key=lambda x: x["liquidity"], reverse=True)
    by_spread = sorted(all_results, key=lambda x: x["spread"])

    print()
    print("SUMMARY")
    print("=" * 80)
    print(f"Markets scanned : {scanned_markets}")
    print(f"Tokens scanned  : {scanned_tokens}")
    print(f"Valid books     : {valid_books}")
    print(f"Passed filters  : {len(filtered_results)}")

    print()
    print("TOP 10 FILTERED MARKETS")
    print("=" * 80)
    if filtered_results:
        for i, item in enumerate(filtered_results[:10], start=1):
            print_market_block(i, item)
    else:
        print("No interesting markets found with current filters.")
        print("-" * 80)

    print()
    print("TOP 10 BY LIQUIDITY")
    print("=" * 80)
    if by_liquidity:
        for i, item in enumerate(by_liquidity[:10], start=1):
            print_market_block(i, item)
    else:
        print("No markets with valid order book found.")
        print("-" * 80)

    print()
    print("TOP 10 BY LOWEST SPREAD")
    print("=" * 80)
    if by_spread:
        for i, item in enumerate(by_spread[:10], start=1):
            print_market_block(i, item)
    else:
        print("No markets with valid order book found.")
        print("-" * 80)


if __name__ == "__main__":
    main()