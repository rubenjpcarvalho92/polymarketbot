from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.market_scoring import compute_market_score
from bot.polymarket_client import PolymarketClient


OUTPUT_JSON = PROJECT_ROOT / "data" / "btc_markets_scan.json"

# Keywords fortes e específicas
BTC_KEYWORDS = [
    "bitcoin",
    "btc",
    "xbt",
    "bitcoin price",
    "btc price",
    "bitcoin etf",
    "btc etf",
    "bitcoin ath",
    "btc ath",
    "all time high bitcoin",
    "all time high btc",
    "bitcoin dominance",
    "btc dominance",
    "satoshi",
]

CRYPTO_KEYWORDS = [
    "bitcoin",
    "btc",
    "xbt",
    "ethereum",
    "eth",
    "solana",
    "sol",
    "ripple",
    "xrp",
    "dogecoin",
    "doge",
    "cardano",
    "ada",
    "avalanche",
    "avax",
    "crypto",
    "cryptocurrency",
    "stablecoin",
    "defi",
    "nft",
    "altcoin",
    "memecoin",
    "meme coin",
    "binance",
    "coinbase",
    "blackrock bitcoin etf",
    "spot bitcoin etf",
]

MIN_DAYS = 8.0
MAX_DAYS = 90.0
MIN_LIQUIDITY = 500.0
MAX_SPREAD = 0.05


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
    text = str(value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
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


def get_market_text(market: dict[str, Any]) -> str:
    parts = [
        str(market.get("question") or ""),
        str(market.get("title") or ""),
        str(market.get("event_title") or market.get("eventTitle") or ""),
        str(market.get("description") or ""),
        str(market.get("category") or ""),
        str(market.get("subcategory") or ""),
    ]
    return " ".join(parts).lower().strip()


def is_crypto_market(market: dict[str, Any]) -> bool:
    text = get_market_text(market)
    return any(keyword in text for keyword in CRYPTO_KEYWORDS)


def is_btc_market(market: dict[str, Any]) -> bool:
    text = get_market_text(market)
    return any(keyword in text for keyword in BTC_KEYWORDS)


def market_has_valid_status(market: dict[str, Any]) -> bool:
    active = market.get("active")
    closed = market.get("closed")
    archived = market.get("archived")
    enable_order_book = market.get("enable_order_book", market.get("enableOrderBook"))

    if active is False:
        return False
    if closed is True:
        return False
    if archived is True:
        return False
    if enable_order_book is False:
        return False

    return True


def market_is_allowed(
    *,
    question: str,
    event_title: str,
    days_to_resolution: float,
    midpoint: Optional[float],
    spread: Optional[float],
    liquidity: Optional[float],
    min_days: float = MIN_DAYS,
    max_days: float = MAX_DAYS,
    min_liquidity: float = MIN_LIQUIDITY,
    max_spread: float = MAX_SPREAD,
) -> bool:
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


def get_attr_or_key(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj.get(name)
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def extract_book_data(book: Any) -> dict[str, Optional[float]]:
    best_bid = safe_float(get_attr_or_key(book, "best_bid", "bestBid"))
    best_ask = safe_float(get_attr_or_key(book, "best_ask", "bestAsk"))
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
    market: dict[str, Any],
    token: dict[str, Any],
    book: Any,
) -> Optional[ScannedMarket]:
    question = str(market.get("question", "") or "")
    event_title = str(market.get("event_title") or market.get("eventTitle") or market.get("title") or "")
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

    total_markets_seen = 0
    crypto_markets_seen = 0
    btc_markets_seen = 0

    for page in range(1, max_pages + 1):
        print(f"Scanning page {page} with cursor={cursor}")

        response = client.get_markets(cursor=cursor)
        markets = response.get("data") or response.get("markets") or []
        next_cursor = response.get("next_cursor") or response.get("nextCursor")

        if not markets:
            break

        for market in markets:
            total_markets_seen += 1

            if not market_has_valid_status(market):
                continue

            # 1º filtro: crypto only
            if not is_crypto_market(market):
                continue
            crypto_markets_seen += 1

            # 2º filtro: BTC only
            if not is_btc_market(market):
                continue
            btc_markets_seen += 1

            question = str(market.get("question") or "")
            event_title = str(market.get("event_title") or market.get("eventTitle") or market.get("title") or "")
            print(f"[BTC MARKET] {question or event_title}")

            tokens = market.get("tokens") or market.get("outcomes") or []
            if not isinstance(tokens, list) or not tokens:
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

                item = build_scanned_market(
                    market=market,
                    token=token,
                    book=book,
                )
                if item is not None:
                    scanned.append(item)

        if not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor

    print()
    print("DISCOVERY SUMMARY")
    print("=" * 80)
    print(f"Total markets scanned : {total_markets_seen}")
    print(f"Crypto markets found  : {crypto_markets_seen}")
    print(f"BTC markets found     : {btc_markets_seen}")
    print(f"BTC markets kept      : {len(scanned)}")
    print("=" * 80)

    scanned.sort(key=lambda x: x.total_score, reverse=True)
    return scanned


def main() -> None:
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    client = PolymarketClient(config.polymarket)

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