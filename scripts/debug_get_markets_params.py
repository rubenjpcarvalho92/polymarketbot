from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def count_items(result):
    if isinstance(result, dict):
        return len(result.get("data") or result.get("markets") or result.get("items") or [])
    return len(result or [])


def main() -> None:
    config = load_config()
    client = PolymarketClient(config.polymarket)
    raw = client._ensure_client()

    test_calls = [
        ("plain", {}, False),
        ("active_closed_archived", {"active": True, "closed": False, "archived": False}, True),
        ("accepting_orders", {"accepting_orders": True}, True),
        ("enable_order_book", {"enable_order_book": True}, True),
        (
            "full_filter",
            {
                "active": True,
                "closed": False,
                "archived": False,
                "accepting_orders": True,
                "enable_order_book": True,
            },
            True,
        ),
    ]

    for name, kwargs, use_kwargs in test_calls:
        print("=" * 80)
        print(f"TEST: {name}")
        try:
            if use_kwargs:
                result = raw.get_markets(**kwargs)
            else:
                result = raw.get_markets()
            print(f"OK | items={count_items(result)}")
        except Exception as e:
            print(f"ERROR | {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()