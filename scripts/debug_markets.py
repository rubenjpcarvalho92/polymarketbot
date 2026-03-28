from __future__ import annotations

import sys
import json
import inspect
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: to_jsonable(v) for k, v in vars(obj).items()}
    return obj


def main() -> None:
    config = load_config()
    client = PolymarketClient(config.polymarket)
    raw = client._ensure_client()

    print("RAW CLIENT TYPE")
    print("=" * 80)
    print(type(raw))
    print()

    print("GET_MARKETS SIGNATURE")
    print("=" * 80)
    try:
        print(inspect.signature(raw.get_markets))
    except Exception as e:
        print(f"Could not inspect signature: {e}")
    print()

    print("GET_MARKETS SOURCE")
    print("=" * 80)
    try:
        print(inspect.getsource(raw.get_markets))
    except Exception as e:
        print(f"Could not inspect source: {e}")
    print()

    print("FETCHING MARKETS...")
    print("=" * 80)
    markets = client.get_markets()
    print(f"type(markets) = {type(markets)}")
    print()

    if isinstance(markets, dict):
        items = (
            markets.get("data")
            or markets.get("markets")
            or markets.get("items")
            or []
        )
        print("DICT KEYS")
        print("=" * 80)
        print(list(markets.keys())[:50])
        print()
    else:
        items = markets or []

    print("COUNTS")
    print("=" * 80)
    print(f"total markets: {len(items)}")
    print()

    print("FIRST 10 MARKETS STATUS")
    print("=" * 80)
    for i, m in enumerate(items[:10], 1):
        if isinstance(m, dict):
            print(
                f"{i}. "
                f"active={m.get('active')} | "
                f"closed={m.get('closed')} | "
                f"archived={m.get('archived')} | "
                f"accepting_orders={m.get('accepting_orders')} | "
                f"enable_order_book={m.get('enable_order_book')} | "
                f"question={m.get('question')}"
            )
        else:
            print(
                f"{i}. "
                f"active={getattr(m, 'active', None)} | "
                f"closed={getattr(m, 'closed', None)} | "
                f"archived={getattr(m, 'archived', None)} | "
                f"accepting_orders={getattr(m, 'accepting_orders', None)} | "
                f"enable_order_book={getattr(m, 'enable_order_book', None)} | "
                f"question={getattr(m, 'question', None)}"
            )
    print()

    if items:
        print("FIRST MARKET FULL JSON")
        print("=" * 80)
        first = to_jsonable(items[0])
        print(json.dumps(first, indent=2, ensure_ascii=False)[:12000])


if __name__ == "__main__":
    main()