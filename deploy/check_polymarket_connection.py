from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def main() -> None:
    config = load_config()
    client = PolymarketClient(config.polymarket)

    print("Checking Polymarket client...")
    ok = client.ping()
    print(f"Client initialized: {ok}")

    token_id = config.trading.default_token_id
    if token_id:
        try:
            book = client.get_order_book(token_id)
            print("\nOrder book:")
            print(f"token_id : {book.token_id}")
            print(f"best_bid : {book.best_bid}")
            print(f"best_ask : {book.best_ask}")
            print(f"bid_size : {book.bid_size}")
            print(f"ask_size : {book.ask_size}")
        except Exception as exc:
            print(f"Could not fetch order book: {exc}")
    else:
        print("\nNo DEFAULT_TOKEN_ID set in .env, skipping order book check.")


if __name__ == "__main__":
    main()