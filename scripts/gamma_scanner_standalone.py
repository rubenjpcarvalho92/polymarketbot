from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


@dataclass
class MarketRow:
    event_id: Optional[str]
    event_title: Optional[str]
    event_slug: Optional[str]

    market_id: Optional[str]
    market_slug: Optional[str]
    question: Optional[str]
    url: Optional[str]

    active: Optional[bool]
    closed: Optional[bool]
    archived: Optional[bool]
    enable_order_book: Optional[bool]

    liquidity: float
    volume: float
    volume_24hr: float

    yes_token_id: Optional[str]
    no_token_id: Optional[str]
    yes_price: Optional[float]
    no_price: Optional[float]

    start_date_iso: Optional[str]
    end_date_iso: Optional[str]

    score: float
    ranking_reason: Dict[str, Any]


class GammaScanner:
    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "gamma-scanner-standalone/2.0",
            }
        )

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"{GAMMA_BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _to_bool(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"true", "1", "yes"}:
                return True
            if v in {"false", "0", "no"}:
                return False
        return None

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value in (None, "", []):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _first_non_empty(d: Dict[str, Any], keys: List[str]) -> Any:
        for key in keys:
            if key in d and d[key] not in (None, "", [], {}):
                return d[key]
        return None

    @staticmethod
    def _extract_token(tokens: List[Dict[str, Any]], wanted_outcome: str) -> Dict[str, Any]:
        wanted = wanted_outcome.strip().lower()
        for token in tokens or []:
            outcome = str(token.get("outcome", "")).strip().lower()
            if outcome == wanted:
                return token
        return {}

    @staticmethod
    def _parse_iso_datetime(date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except Exception:
            return None

    def _is_future_market(self, end_date_iso: Optional[str]) -> bool:
        if not end_date_iso:
            return True
        dt = self._parse_iso_datetime(end_date_iso)
        if dt is None:
            return True
        return dt > datetime.now(timezone.utc)

    @staticmethod
    def _score(
        liquidity: float,
        volume: float,
        volume_24hr: float,
        order_book_ok: bool,
        active_ok: bool,
    ) -> float:
        return (
            1.8 * math.log1p(max(liquidity, 0.0))
            + 1.0 * math.log1p(max(volume, 0.0))
            + 1.5 * math.log1p(max(volume_24hr, 0.0))
            + (1.0 if order_book_ok else 0.0)
            + (0.5 if active_ok else 0.0)
        )

    def fetch_active_events(
        self,
        page_size: int = 100,
        max_pages: int = 2,
        sleep_between_pages: float = 0.0,
    ) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        offset = 0

        for _ in range(max_pages):
            params = {
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
            }

            batch = self._get("/events", params=params)

            if not isinstance(batch, list):
                raise RuntimeError(f"Resposta inesperada do endpoint /events: {type(batch).__name__}")

            if not batch:
                break

            events.extend(batch)

            if len(batch) < page_size:
                break

            offset += page_size

            if sleep_between_pages > 0:
                time.sleep(sleep_between_pages)

        return events

    def flatten_events_to_markets(
        self,
        events: List[Dict[str, Any]],
    ) -> List[MarketRow]:
        results: List[MarketRow] = []

        for event in events:
            event_id = self._first_non_empty(event, ["id", "event_id"])
            event_title = self._first_non_empty(event, ["title", "name", "ticker"])
            event_slug = self._first_non_empty(event, ["slug"])

            markets = event.get("markets") or []
            if not isinstance(markets, list):
                continue

            for market in markets:
                active = self._to_bool(self._first_non_empty(market, ["active"]))
                closed = self._to_bool(self._first_non_empty(market, ["closed"]))
                archived = self._to_bool(self._first_non_empty(market, ["archived"]))
                enable_order_book = self._to_bool(
                    self._first_non_empty(
                        market,
                        ["enableOrderBook", "enable_order_book", "accepting_orders"],
                    )
                )

                liquidity = self._to_float(
                    self._first_non_empty(market, ["liquidity", "liquidityNum", "liquidityClob"])
                )
                volume = self._to_float(
                    self._first_non_empty(market, ["volume", "volumeNum", "volumeClob"])
                )
                volume_24hr = self._to_float(
                    self._first_non_empty(
                        market,
                        ["volume24hr", "volume_24hr", "oneDayVolume", "one_day_volume", "volume24hrClob"],
                    )
                )

                start_date_iso = self._first_non_empty(
                    market, ["startDate", "start_date", "start_date_iso", "startDateIso"]
                )
                end_date_iso = self._first_non_empty(
                    market, ["endDate", "end_date", "end_date_iso", "endDateIso"]
                )

                yes_token_id = None
                no_token_id = None
                yes_price = None
                no_price = None

                tokens = market.get("tokens") or []
                if isinstance(tokens, list) and tokens:
                    yes_token = self._extract_token(tokens, "yes")
                    no_token = self._extract_token(tokens, "no")

                    yes_token_id = yes_token.get("token_id")
                    no_token_id = no_token.get("token_id")

                    if yes_token.get("price") is not None:
                        try:
                            yes_price = float(yes_token["price"])
                        except (TypeError, ValueError):
                            yes_price = None

                    if no_token.get("price") is not None:
                        try:
                            no_price = float(no_token["price"])
                        except (TypeError, ValueError):
                            no_price = None

                if (not yes_token_id or not no_token_id) and market.get("clobTokenIds"):
                    raw = market.get("clobTokenIds")
                    try:
                        parsed = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(parsed, list) and len(parsed) >= 2:
                            yes_token_id = yes_token_id or str(parsed[0])
                            no_token_id = no_token_id or str(parsed[1])
                    except Exception:
                        pass

                market_slug = self._first_non_empty(market, ["slug"])
                question = self._first_non_empty(market, ["question", "title", "name"])

                score = self._score(
                    liquidity=liquidity,
                    volume=volume,
                    volume_24hr=volume_24hr,
                    order_book_ok=(enable_order_book is not False),
                    active_ok=(active is not False),
                )

                ranking_reason = {
                    "liquidity": liquidity,
                    "volume": volume,
                    "volume_24hr": volume_24hr,
                    "enable_order_book": enable_order_book,
                    "active": active,
                }

                results.append(
                    MarketRow(
                        event_id=str(event_id) if event_id is not None else None,
                        event_title=event_title,
                        event_slug=event_slug,
                        market_id=str(self._first_non_empty(market, ["id", "market_id"]))
                        if self._first_non_empty(market, ["id", "market_id"]) is not None
                        else None,
                        market_slug=market_slug,
                        question=question,
                        url=f"https://polymarket.com/market/{market_slug}" if market_slug else None,
                        active=active,
                        closed=closed,
                        archived=archived,
                        enable_order_book=enable_order_book,
                        liquidity=liquidity,
                        volume=volume,
                        volume_24hr=volume_24hr,
                        yes_token_id=str(yes_token_id) if yes_token_id is not None else None,
                        no_token_id=str(no_token_id) if no_token_id is not None else None,
                        yes_price=yes_price,
                        no_price=no_price,
                        start_date_iso=start_date_iso,
                        end_date_iso=end_date_iso,
                        score=score,
                        ranking_reason=ranking_reason,
                    )
                )

        return results

    def filter_markets(
        self,
        markets: List[MarketRow],
        min_liquidity: float = 1000.0,
        min_volume_24hr: float = 500.0,
        require_order_book: bool = True,
        require_yes_no_tokens: bool = True,
        require_future_end_date: bool = True,
        exclude_keywords: Optional[List[str]] = None,
    ) -> List[MarketRow]:
        exclude_keywords = [k.lower() for k in (exclude_keywords or [])]
        filtered: List[MarketRow] = []

        for market in markets:
            if market.closed is True:
                continue
            if market.archived is True:
                continue
            if market.active is False:
                continue

            if require_order_book and market.enable_order_book is False:
                continue

            if market.liquidity < min_liquidity:
                continue

            if market.volume_24hr < min_volume_24hr:
                continue

            if require_yes_no_tokens and (not market.yes_token_id or not market.no_token_id):
                continue

            if require_future_end_date and not self._is_future_market(market.end_date_iso):
                continue

            text = f"{market.event_title or ''} {market.question or ''}".lower()
            if any(keyword in text for keyword in exclude_keywords):
                continue

            filtered.append(market)

        filtered.sort(key=lambda x: x.score, reverse=True)
        return filtered

    def scan(
        self,
        page_size: int = 100,
        max_pages: int = 2,
        min_liquidity: float = 1000.0,
        min_volume_24hr: float = 500.0,
        require_order_book: bool = True,
        require_yes_no_tokens: bool = True,
        require_future_end_date: bool = True,
        exclude_keywords: Optional[List[str]] = None,
        top_n: int = 15,
    ) -> Dict[str, List[MarketRow]]:
        events = self.fetch_active_events(
            page_size=page_size,
            max_pages=max_pages,
        )

        raw_markets = self.flatten_events_to_markets(events)

        filtered_markets = self.filter_markets(
            markets=raw_markets,
            min_liquidity=min_liquidity,
            min_volume_24hr=min_volume_24hr,
            require_order_book=require_order_book,
            require_yes_no_tokens=require_yes_no_tokens,
            require_future_end_date=require_future_end_date,
            exclude_keywords=exclude_keywords,
        )

        return {
            "raw": raw_markets,
            "filtered": filtered_markets[:top_n],
        }


def print_markets(markets: List[MarketRow], title: str) -> None:
    print(f"\n{title}: {len(markets)} mercados\n")
    for i, m in enumerate(markets, start=1):
        print(f"{i:02d}. {m.question}")
        print(f"    Event        : {m.event_title}")
        print(f"    URL          : {m.url}")
        print(f"    Market ID    : {m.market_id}")
        print(f"    YES token ID : {m.yes_token_id}")
        print(f"    NO token ID  : {m.no_token_id}")
        print(f"    YES price    : {m.yes_price}")
        print(f"    NO price     : {m.no_price}")
        print(f"    Liquidity    : {m.liquidity}")
        print(f"    Volume       : {m.volume}")
        print(f"    Volume 24h   : {m.volume_24hr}")
        print(f"    End date     : {m.end_date_iso}")
        print(f"    Score        : {m.score:.2f}")
        print(f"    Reason       : {m.ranking_reason}")
        print("-" * 100)


def save_json(markets: List[MarketRow], filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as f:
        json.dump([asdict(m) for m in markets], f, ensure_ascii=False, indent=2)
    print(f"JSON gravado em: {filename}")


if __name__ == "__main__":
    try:
        scanner = GammaScanner()

        result = scanner.scan(
            page_size=100,
            max_pages=100,
            min_liquidity=1000.0,
            min_volume_24hr=500.0,
            require_order_book=True,
            require_yes_no_tokens=True,
            require_future_end_date=True,
            exclude_keywords=[
                "2028 presidential nomination",
                "2028 us presidential election",
            ],
            top_n=200,
        )

        raw_markets = result["raw"]
        filtered_markets = result["filtered"]

        print_markets(filtered_markets, "Encontrados")
        save_json(raw_markets, "gamma_scan_results_raw.json")
        save_json(filtered_markets, "gamma_scan_results_filtered.json")

    except requests.HTTPError as e:
        print(f"Erro HTTP: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)