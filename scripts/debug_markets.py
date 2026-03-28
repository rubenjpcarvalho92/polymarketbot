from __future__ import annotations

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.polymarket_client import PolymarketClient


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {k: to_jsonable(v) for k, v in vars(obj).items()}
    return obj


def main():
    config = load_config()
    client = PolymarketClient(config.polymarket)

    markets = client.get_markets()

    if isinstance(markets, dict):
        items = markets.get("data") or markets.get("markets") or markets.get("items") or []
    else:
        items = markets or []

    print(f"Total markets: {len(items)}")
    if not items:
        return

    first = items[0]
    print(type(first))
    print(json.dumps(to_jsonable(first), indent=2, ensure_ascii=False)[:12000])


if __name__ == "__main__":
    main()