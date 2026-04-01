from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.market_scoring import compute_market_score
from bot.polymarket_client import PolymarketClient


OUTPUT_JSON = PROJECT_ROOT / "data" / "btc_markets_scan.json"

BTC_KEYWORDS = [
    "bitcoin",
    "btc",
    "bitcoin price",
    "will bitcoin",
    "will btc",
    "btc price",
    "reach",
    "hit",
    "above",
    "below",
    "close above",
    "close below",
    "ath",
    "all time high",
]


@dataclass
class ScannedMarket:
    market_id: str
    token_id: str
    question: str
    event_title: str
    url: Optional[str]
    side: str
    end_date: Optional[str]
    days_to_resolution: float

    best_bid: Optional[float]
    best_ask: Optional[float]
    midpoint: Optional[float]
    spread: Optional[float]

    liquidity: Optional[float]
    volume: Optional[float]

    time_score: float
    liquidity_score: float
    spread_score: float
    price_score: float
    technical_score: float
    total_score: float


def parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_days_to_resolution(end_date: Optional[str]) -> float:
    dt = parse_iso_datetime(end_date)
    if dt is None:
        return 9999.0

    now = datetime.now(timezone.utc)
    return (dt - now).total_seconds() / 86400.0


def safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_midpoint(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    if best_bid <= 0 and best_ask <= 0:
        return None
    return (best_bid + best_ask) / 2.0


def compute_spread(best_bid: Optional[float], best_ask: Optional[float]) -> Optional[float]:
    if best_bid is None or best_ask is None:
        return None
    if best_ask < best_bid:
        return None
    return best_ask - best_bid


def is_btc_market(question: str, event_title: str) -> bool:
    text = f"{question} {event_title}".lower()
    return any(keyword in text for keyword in BTC_KEYWORDS)


def market_is_allowed(
    *,
    question: str,
    event_title: str,
    days_to_resolution: float,
    midpoint: Optional[float],
    spread: Optional[float],
    liquidity: Optional[float],
    min_days: float = 15.0,
    max_days: float = 60.0,
    min_liquidity: float = 1000.0,
    max_spread: float = 0.05,
) -> bool:
    if not is_btc_market(question, event_title):
        return False

    if days_to_resolution < min_days or days_to_resolution > max_days:
        return False

    if midpoint is None:
        return False

    if midpoint < 0.10 or midpoint > 0.90:
        return False

    if spread is None or spread > max_spread:
        return False

    if liquidity is None or liquidity < min_liquidity:
        return False

    return True


def extract_book_data(book: Dict[str, Any]) -> Dict[str, Optional[float]]:
    best_bid = safe_float(book.get("best_bid") or book.get("bestBid"))
    best_ask = safe_float(book.get("best_ask") or book.get("bestAsk"))
    midpoint = compute_midpoint(best_bid, best_ask)
    spread = compute_spread(best_bid, best_ask)

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "midpoint": midpoint,
        "spread": spread,
    }


def build_scanned_market(
    *,
    market: Dict[str, Any],
    token: Dict[str, Any],
    book: Dict[str, Any],
) -> Optional[ScannedMarket]:
    question = market.get("question", "") or ""
    event_title = market.get("event_title") or market.get("eventTitle") or ""
    market_id = str(market.get("id", "") or "")
    token_id = str(token.get("token_id") or token.get("tokenId") or "")
    side = str(token.get("outcome") or token.get("side") or "YES").upper()
    url = market.get("url")
    end_date = market.get("end_date") or market.get("endDate")

    liquidity = safe_float(market.get("liquidity"))
    volume = safe_float(market.get("volume") or market.get("volumeNum"))
    days = compute_days_to_resolution(end_date)

    book_data = extract_book_data(book)
    midpoint = book_data["midpoint"]
    spread = book_data["spread"]
    best_bid = book_data["best_bid"]
    best_ask = book_data["best_ask"]

    if not market_is_allowed(
        question=question,
        event_title=event_title,
        days_to_resolution=days,
        midpoint=midpoint,
        spread=spread,
        liquidity=liquidity,
    ):
        return None

    score = compute_market_score(
        days_to_resolution=days,
        spread=spread,
        mid_price=midpoint,
        liquidity=liquidity,
        technical_score=0.5,
        side=side,
    )

    return ScannedMarket(
        market_id=market_id,
        token_id=token_id,
        question=question,
        event_title=event_title,
        url=url,
        side=side,
        end_date=end_date,
        days_to_resolution=days,
        best_bid=best_bid,
        best_ask=best_ask,
        midpoint=midpoint,
        spread=spread,
        liquidity=liquidity,
        volume=volume,
        time_score=score.time_score,
        liquidity_score=score.liquidity_score,
        spread_score=score.spread_score,
        price_score=score.price_score,
        technical_score=score.technical_score,
        total_score=score.total_score,
    )


def fetch_tradeable_btc_markets(client: PolymarketClient, max_pages: int = 10) -> List[ScannedMarket]:
    scanned: List[ScannedMarket] = []
    cursor: Optional[str] = None

    for page in range(1, max_pages + 1):
        print(f"Scanning page {page} with cursor={cursor}")

        response = client.get_markets(cursor=cursor)
        markets = response.get("data") or response.get("markets") or []
        next_cursor = response.get("next_cursor") or response.get("nextCursor")

        if not markets:
            break

        for market in markets:
            tokens = market.get("tokens") or market.get("outcomes") or []
            if not tokens:
                continue

            for token in tokens:
                token_id = str(token.get("token_id") or token.get("tokenId") or "")
                if not token_id:
                    continue

                try:
                    book = client.get_order_book(token_id)
                except Exception as exc:
                    print(f"Failed to fetch order book for token {token_id}: {exc}")
                    continue

                item = build_scanned_market(market=market, token=token, book=book)
                if item is not None:
                    scanned.append(item)

        if not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor

    scanned.sort(key=lambda x: x.total_score, reverse=True)
    return scanned


def main() -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    client = PolymarketClient()

    print("Fetching BTC-focused tradeable markets...")
    results = fetch_tradeable_btc_markets(client=client, max_pages=10)

    print()
    print("SUMMARY")
    print("=" * 80)
    print(f"BTC markets kept : {len(results)}")

    for idx, market in enumerate(results[:15], start=1):
        print(
            f"{idx:02d}. score={market.total_score:.4f} | "
            f"side={market.side:>3} | "
            f"mid={market.midpoint} | "
            f"spread={market.spread} | "
            f"liq={market.liquidity} | "
            f"days={market.days_to_resolution:.1f} | "
            f"{market.question}"
        )

    with OUTPUT_JSON.open("w", encoding="utf-8") as f:
        json.dump([asdict(item) for item in results], f, ensure_ascii=False, indent=2)

    print()
    print(f"Saved results to: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()