from __future__ import annotations

import sys
import inspect
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def count_items(result: Any) -> int:
    if isinstance(result, dict):
        return len(result.get("data") or result.get("markets") or result.get("items") or [])
    return len(result or [])


def first_item(result: Any) -> Any:
    if isinstance(result, dict):
        items = result.get("data") or result.get("markets") or result.get("items") or []
    else:
        items = result or []
    return items[0] if items else None


def print_first_status(item: Any) -> None:
    if not item:
        print("first item: None")
        return

    if isinstance(item, dict):
        print(
            "first item status:",
            {
                "active": item.get("active"),
                "closed": item.get("closed"),
                "archived": item.get("archived"),
                "accepting_orders": item.get("accepting_orders"),
                "enable_order_book": item.get("enable_order_book"),
                "question": item.get("question"),
            },
        )
    else:
        print(
            "first item status:",
            {
                "active": getattr(item, "active", None),
                "closed": getattr(item, "closed", None),
                "archived": getattr(item, "archived", None),
                "accepting_orders": getattr(item, "accepting_orders", None),
                "enable_order_book": getattr(item, "enable_order_book", None),
                "question": getattr(item, "question", None),
            },
        )


def main() -> None:
    config = load_config()
    client = PolymarketClient(config.polymarket)
    raw = client._ensure_client()

    print("SIGNATURE")
    print("=" * 80)
    try:
        print(inspect.signature(raw.get_markets))
    except Exception as e:
        print(f"Could not inspect signature: {e}")
    print()

    test_calls = [
        ("plain", {}, False),
        ("limit_only", {"limit": 50}, True),
        ("next_cursor_only", {"next_cursor": ""}, True),
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
            print_first_status(first_item(result))
        except Exception as e:
            print(f"ERROR | {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()