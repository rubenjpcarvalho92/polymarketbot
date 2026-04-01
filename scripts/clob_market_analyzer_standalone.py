from __future__ import annotations

import json
import math
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


CLOB_BASE_URL = "https://clob.polymarket.com"
INPUT_JSON = "gamma_scan_results_filtered.json"
OUTPUT_JSON = "token_analysis_results.json"

BTC_KEYWORDS = [
    "bitcoin",
    "btc",
    "xbt",
    "satoshi",
    "ath",
    "all time high",
]

NEW_ENTRY_MIN_DAYS = 15.0
NEW_ENTRY_MAX_DAYS = 60.0
FORCE_EXIT_DAYS = 7.0


@dataclass
class TokenAnalysis:
    parent_market_id: Optional[str]
    parent_question: Optional[str]
    parent_event_title: Optional[str]
    parent_url: Optional[str]

    outcome: str
    token_id: str

    end_date: Optional[str]
    days_to_resolution: Optional[float]
    liquidity: Optional[float]
    volume: Optional[float]
    btc_relevance_score: float

    midpoint: Optional[float]
    buy_price: Optional[float]   # best ask: price to buy
    sell_price: Optional[float]  # best bid: price to sell
    spread: Optional[float]

    last_trade_price: Optional[float]
    last_trade_side: Optional[str]

    history_points: int
    first_price: Optional[float]
    last_price: Optional[float]
    return_pct: Optional[float]
    volatility: Optional[float]
    avg_abs_change: Optional[float]
    min_price: Optional[float]
    max_price: Optional[float]
    trend_consistency: Optional[float]
    positive_return_bonus: float
    trend_bonus: float
    pump_penalty: float

    midpoint_penalty: float
    spread_penalty: float
    time_penalty: float
    btc_bonus: float
    liquidity_bonus: float
    score: float
    ranking_reason: Dict[str, Any]


class ClobAnalyzer:
    def __init__(self, timeout: int = 20, sleep_between_calls: float = 0.05) -> None:
        self.timeout = timeout
        self.sleep_between_calls = sleep_between_calls
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "clob-market-analyzer-standalone/6.0-btc-focused",
            }
        )
        self.exclusion_reasons: Counter[str] = Counter()

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"{CLOB_BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _to_float(value: Any) -> Optional[float]:
        if value in (None, "", []):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_iso_datetime(raw_value: Any) -> Optional[datetime]:
        text = str(raw_value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            return None

    @classmethod
    def _compute_days_to_resolution(cls, end_date: Any) -> Optional[float]:
        parsed = cls._parse_iso_datetime(end_date)
        if parsed is None:
            return None
        now = datetime.now(timezone.utc)
        return (parsed - now).total_seconds() / 86400.0

    @staticmethod
    def _is_btc_market_text(question: Optional[str], event_title: Optional[str]) -> bool:
        text = f"{question or ''} {event_title or ''}".strip().lower()
        if not text:
            return False
        return any(keyword in text for keyword in BTC_KEYWORDS)

    @staticmethod
    def _compute_btc_relevance_score(question: Optional[str], event_title: Optional[str]) -> float:
        text = f"{question or ''} {event_title or ''}".strip().lower()
        if not text:
            return 0.0

        score = 0.0

        if "bitcoin" in text:
            score += 0.50
        if "btc" in text:
            score += 0.40
        if "ath" in text or "all time high" in text:
            score += 0.15
        if "above" in text or "below" in text:
            score += 0.10
        if "reach" in text or "hit" in text:
            score += 0.10
        if "price" in text or "$" in text:
            score += 0.10

        return min(score, 1.0)

    @staticmethod
    def _compute_time_penalty(days_to_resolution: Optional[float]) -> float:
        if days_to_resolution is None:
            return 3.0
        if days_to_resolution <= FORCE_EXIT_DAYS:
            return 3.0
        if days_to_resolution < NEW_ENTRY_MIN_DAYS:
            return 2.0
        if days_to_resolution > NEW_ENTRY_MAX_DAYS:
            return 1.5
        return 0.0

    @staticmethod
    def _compute_liquidity_bonus(liquidity: Optional[float], volume: Optional[float]) -> float:
        liq = liquidity or 0.0
        vol = volume or 0.0

        liq_score = min(max(liq / 10000.0, 0.0), 1.0)
        vol_score = min(max(vol / 10000.0, 0.0), 1.0)

        return (liq_score * 1.5) + (vol_score * 0.75)

    def get_midpoint(self, token_id: str) -> Optional[float]:
        data = self._get("/midpoint", {"token_id": token_id})
        return self._to_float(data.get("mid")) or self._to_float(data.get("mid_price"))

    def get_price(self, token_id: str, side: str) -> Optional[float]:
        data = self._get("/price", {"token_id": token_id, "side": side})
        return self._to_float(data.get("price"))

    def get_spread(self, token_id: str) -> Optional[float]:
        data = self._get("/spread", {"token_id": token_id})
        return self._to_float(data.get("spread"))

    def get_last_trade_price(self, token_id: str) -> Tuple[Optional[float], Optional[str]]:
        data = self._get("/last-trade-price", {"token_id": token_id})
        return self._to_float(data.get("price")), data.get("side")

    def get_prices_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }
        if start_ts is not None:
            params["startTs"] = start_ts
        if end_ts is not None:
            params["endTs"] = end_ts

        data = self._get("/prices-history", params)
        history = data.get("history", [])
        return history if isinstance(history, list) else []

    @staticmethod
    def _extract_prices(history: List[Dict[str, Any]]) -> List[float]:
        prices: List[float] = []
        for row in history:
            try:
                prices.append(float(row.get("p")))
            except (TypeError, ValueError):
                continue
        return prices

    @staticmethod
    def _compute_metrics(prices: List[float]) -> Dict[str, Optional[float]]:
        if not prices:
            return {
                "first_price": None,
                "last_price": None,
                "return_pct": None,
                "volatility": None,
                "avg_abs_change": None,
                "min_price": None,
                "max_price": None,
                "trend_consistency": None,
            }

        first_price = prices[0]
        last_price = prices[-1]
        min_price = min(prices)
        max_price = max(prices)

        return_pct = None
        if first_price not in (None, 0):
            return_pct = ((last_price - first_price) / first_price) * 100.0

        diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        avg_abs_change = statistics.mean(abs(x) for x in diffs) if diffs else 0.0
        volatility = statistics.pstdev(prices) if len(prices) > 1 else 0.0

        positive_moves = sum(1 for d in diffs if d > 0)
        trend_consistency = (positive_moves / len(diffs)) if diffs else 0.0

        return {
            "first_price": first_price,
            "last_price": last_price,
            "return_pct": return_pct,
            "volatility": volatility,
            "avg_abs_change": avg_abs_change,
            "min_price": min_price,
            "max_price": max_price,
            "trend_consistency": trend_consistency,
        }

    @staticmethod
    def _midpoint_extreme_penalty(midpoint: Optional[float]) -> float:
        if midpoint is None:
            return 1.5

        if midpoint < 0.10 or midpoint > 0.90:
            return 3.0
        if midpoint < 0.15 or midpoint > 0.85:
            return 1.25
        return 0.0

    @staticmethod
    def _spread_penalty(spread: Optional[float]) -> float:
        if spread is None:
            return 2.0
        if spread > 0.02:
            return 3.0
        if spread >= 0.015:
            return 1.25
        if spread >= 0.01:
            return 0.4
        return 0.0

    @staticmethod
    def _pump_penalty(
        history_points: int,
        return_pct: Optional[float],
        volatility: Optional[float],
        avg_abs_change: Optional[float],
        trend_consistency: Optional[float],
    ) -> float:
        penalty = 0.0

        if return_pct is not None and return_pct > 35 and history_points < 20:
            penalty += 2.0

        if return_pct is not None and return_pct > 60:
            penalty += 2.0

        if volatility is not None and volatility > 0.10:
            penalty += 1.5

        if avg_abs_change is not None and avg_abs_change > 0.05:
            penalty += 1.0

        if trend_consistency is not None and trend_consistency < 0.50:
            penalty += 1.25

        return penalty

    @staticmethod
    def _positive_return_bonus(return_pct: Optional[float]) -> float:
        if return_pct is None:
            return 0.0
        if return_pct <= 0:
            return 0.0
        if return_pct >= 20:
            return 1.5
        return 0.075 * return_pct

    @staticmethod
    def _trend_bonus(trend_consistency: Optional[float]) -> float:
        if trend_consistency is None:
            return 0.0
        if trend_consistency >= 0.70:
            return 2.0
        if trend_consistency >= 0.60:
            return 1.0
        if trend_consistency >= 0.55:
            return 0.4
        return 0.0

    @staticmethod
    def _is_eligible(
        *,
        is_btc_market: bool,
        midpoint: Optional[float],
        spread: Optional[float],
        history_points: int,
        volatility: Optional[float],
        avg_abs_change: Optional[float],
        return_pct: Optional[float],
        trend_consistency: Optional[float],
        days_to_resolution: Optional[float],
    ) -> tuple[bool, str]:
        if not is_btc_market:
            return False, "not_btc_market"

        if days_to_resolution is None:
            return False, "missing_end_date"

        if days_to_resolution <= FORCE_EXIT_DAYS:
            return False, "too_close_to_resolution"

        if days_to_resolution < NEW_ENTRY_MIN_DAYS:
            return False, "below_entry_window"

        if days_to_resolution > NEW_ENTRY_MAX_DAYS:
            return False, "above_entry_window"

        if midpoint is None:
            return False, "missing_midpoint"

        if midpoint < 0.10 or midpoint > 0.90:
            return False, "midpoint_too_extreme"

        if spread is None:
            return False, "missing_spread"

        if spread > 0.02:
            return False, "spread_too_wide"

        if history_points < 12:
            return False, "not_enough_history"

        vol_ok = volatility is not None and volatility > 0.003
        move_ok = avg_abs_change is not None and avg_abs_change > 0.0015

        if not (vol_ok and move_ok):
            return False, "no_meaningful_movement"

        if return_pct is None:
            return False, "missing_return"

        if return_pct < -5:
            return False, "not_buy_trending"

        if trend_consistency is None or trend_consistency < 0.35:
            return False, "weak_trend_consistency"

        if return_pct > 80:
            return False, "too_extended"

        return True, "eligible"

    @staticmethod
    def _score(
        *,
        midpoint: Optional[float],
        buy_price: Optional[float],
        sell_price: Optional[float],
        spread: Optional[float],
        last_trade_price: Optional[float],
        history_points: int,
        return_pct: Optional[float],
        volatility: Optional[float],
        avg_abs_change: Optional[float],
        trend_consistency: Optional[float],
        days_to_resolution: Optional[float],
        btc_relevance_score: float,
        liquidity: Optional[float],
        volume: Optional[float],
        outcome: str,
    ) -> Tuple[float, float, float, float, float, float, float, float, float]:
        history_term = math.log1p(max(history_points, 0))
        capped_return = min(return_pct, 25.0) if return_pct is not None else 0.0
        vol_term = volatility or 0.0
        change_term = avg_abs_change or 0.0

        midpoint_bonus = 1.0 if midpoint is not None else 0.0
        trade_bonus = 1.0 if last_trade_price is not None else 0.0
        price_bonus = 1.0 if (buy_price is not None and sell_price is not None) else 0.0

        midpoint_penalty = ClobAnalyzer._midpoint_extreme_penalty(midpoint)
        spread_penalty = ClobAnalyzer._spread_penalty(spread)
        pump_penalty = ClobAnalyzer._pump_penalty(
            history_points=history_points,
            return_pct=return_pct,
            volatility=volatility,
            avg_abs_change=avg_abs_change,
            trend_consistency=trend_consistency,
        )
        positive_return_bonus = ClobAnalyzer._positive_return_bonus(return_pct)
        trend_bonus = ClobAnalyzer._trend_bonus(trend_consistency)
        time_penalty = ClobAnalyzer._compute_time_penalty(days_to_resolution)
        btc_bonus = btc_relevance_score * 2.0
        liquidity_bonus = ClobAnalyzer._compute_liquidity_bonus(liquidity, volume)

        yes_bias_penalty = 0.03 if outcome.upper() == "YES" and (days_to_resolution or 0) >= NEW_ENTRY_MIN_DAYS else 0.0

        raw_score = (
            1.6 * history_term
            + 0.03 * capped_return
            + 30.0 * vol_term
            + 140.0 * change_term
            + midpoint_bonus
            + trade_bonus
            + price_bonus
            + positive_return_bonus
            + trend_bonus
            + btc_bonus
            + liquidity_bonus
            - midpoint_penalty
            - spread_penalty
            - pump_penalty
            - time_penalty
            - yes_bias_penalty
        )

        return (
            raw_score,
            midpoint_penalty,
            spread_penalty,
            pump_penalty,
            positive_return_bonus,
            trend_bonus,
            time_penalty,
            btc_bonus,
            liquidity_bonus,
        )

    def analyze_token(
        self,
        token_id: str,
        outcome: str,
        parent_market_id: Optional[str],
        parent_question: Optional[str],
        parent_event_title: Optional[str],
        parent_url: Optional[str],
        parent_end_date: Optional[str],
        parent_liquidity: Optional[float],
        parent_volume: Optional[float],
        interval: str,
        fidelity: int,
    ) -> Optional[TokenAnalysis]:
        midpoint = None
        buy_price = None
        sell_price = None
        spread = None
        last_trade_price = None
        last_trade_side = None
        history: List[Dict[str, Any]] = []

        days_to_resolution = self._compute_days_to_resolution(parent_end_date)
        is_btc_market = self._is_btc_market_text(parent_question, parent_event_title)
        btc_relevance_score = self._compute_btc_relevance_score(parent_question, parent_event_title)

        try:
            midpoint = self.get_midpoint(token_id)
        except Exception:
            midpoint = None

        time.sleep(self.sleep_between_calls)

        try:
            buy_price = self.get_price(token_id, "BUY")
        except Exception:
            buy_price = None

        time.sleep(self.sleep_between_calls)

        try:
            sell_price = self.get_price(token_id, "SELL")
        except Exception:
            sell_price = None

        time.sleep(self.sleep_between_calls)

        try:
            spread = self.get_spread(token_id)
        except Exception:
            spread = None

        time.sleep(self.sleep_between_calls)

        try:
            last_trade_price, last_trade_side = self.get_last_trade_price(token_id)
        except Exception:
            last_trade_price, last_trade_side = None, None

        time.sleep(self.sleep_between_calls)

        try:
            history = self.get_prices_history(
                token_id=token_id,
                interval=interval,
                fidelity=fidelity,
            )
        except Exception:
            history = []

        prices = self._extract_prices(history)
        metrics = self._compute_metrics(prices)
        history_points = len(prices)

        eligible, eligibility_reason = self._is_eligible(
            is_btc_market=is_btc_market,
            midpoint=midpoint,
            spread=spread,
            history_points=history_points,
            volatility=metrics["volatility"],
            avg_abs_change=metrics["avg_abs_change"],
            return_pct=metrics["return_pct"],
            trend_consistency=metrics["trend_consistency"],
            days_to_resolution=days_to_resolution,
        )

        if not eligible:
            self.exclusion_reasons[eligibility_reason] += 1
            return None

        (
            score,
            midpoint_penalty,
            spread_penalty,
            pump_penalty,
            positive_return_bonus,
            trend_bonus,
            time_penalty,
            btc_bonus,
            liquidity_bonus,
        ) = self._score(
            midpoint=midpoint,
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            last_trade_price=last_trade_price,
            history_points=history_points,
            return_pct=metrics["return_pct"],
            volatility=metrics["volatility"],
            avg_abs_change=metrics["avg_abs_change"],
            trend_consistency=metrics["trend_consistency"],
            days_to_resolution=days_to_resolution,
            btc_relevance_score=btc_relevance_score,
            liquidity=parent_liquidity,
            volume=parent_volume,
            outcome=outcome,
        )

        ranking_reason = {
            "eligibility_reason": eligibility_reason,
            "history_points": history_points,
            "end_date": parent_end_date,
            "days_to_resolution": days_to_resolution,
            "liquidity": parent_liquidity,
            "volume": parent_volume,
            "btc_relevance_score": btc_relevance_score,
            "midpoint": midpoint,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "spread": spread,
            "last_trade_price": last_trade_price,
            "return_pct": metrics["return_pct"],
            "volatility": metrics["volatility"],
            "avg_abs_change": metrics["avg_abs_change"],
            "trend_consistency": metrics["trend_consistency"],
            "midpoint_penalty": midpoint_penalty,
            "spread_penalty": spread_penalty,
            "pump_penalty": pump_penalty,
            "positive_return_bonus": positive_return_bonus,
            "trend_bonus": trend_bonus,
            "time_penalty": time_penalty,
            "btc_bonus": btc_bonus,
            "liquidity_bonus": liquidity_bonus,
        }

        return TokenAnalysis(
            parent_market_id=parent_market_id,
            parent_question=parent_question,
            parent_event_title=parent_event_title,
            parent_url=parent_url,
            outcome=outcome,
            token_id=token_id,
            end_date=parent_end_date,
            days_to_resolution=days_to_resolution,
            liquidity=parent_liquidity,
            volume=parent_volume,
            btc_relevance_score=btc_relevance_score,
            midpoint=midpoint,
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            last_trade_price=last_trade_price,
            last_trade_side=last_trade_side,
            history_points=history_points,
            first_price=metrics["first_price"],
            last_price=metrics["last_price"],
            return_pct=metrics["return_pct"],
            volatility=metrics["volatility"],
            avg_abs_change=metrics["avg_abs_change"],
            min_price=metrics["min_price"],
            max_price=metrics["max_price"],
            trend_consistency=metrics["trend_consistency"],
            positive_return_bonus=positive_return_bonus,
            trend_bonus=trend_bonus,
            pump_penalty=pump_penalty,
            midpoint_penalty=midpoint_penalty,
            spread_penalty=spread_penalty,
            time_penalty=time_penalty,
            btc_bonus=btc_bonus,
            liquidity_bonus=liquidity_bonus,
            score=score,
            ranking_reason=ranking_reason,
        )

    def analyze_from_json(
        self,
        input_json: str = INPUT_JSON,
        interval: str = "1d",
        fidelity: int = 60,
        top_n: Optional[int] = None,
    ) -> List[TokenAnalysis]:
        path = Path(input_json)
        if not path.exists():
            raise FileNotFoundError(f"Ficheiro não encontrado: {input_json}")

        with path.open("r", encoding="utf-8") as f:
            markets = json.load(f)

        if not isinstance(markets, list):
            raise ValueError("O JSON de entrada deve ser uma lista de mercados.")

        analyses: List[TokenAnalysis] = []
        selected_markets = markets[:top_n] if top_n is not None else markets

        for market in selected_markets:
            parent_market_id = market.get("market_id")
            parent_question = market.get("question")
            parent_event_title = market.get("event_title")
            parent_url = market.get("url")
            parent_end_date = (
                market.get("end_date")
                or market.get("endDate")
                or market.get("end_date_iso")
                or market.get("resolve_date")
            )
            parent_liquidity = self._to_float(market.get("liquidity"))
            parent_volume = self._to_float(market.get("volume"))

            yes_token_id = market.get("yes_token_id")
            no_token_id = market.get("no_token_id")

            if yes_token_id:
                result = self.analyze_token(
                    token_id=str(yes_token_id),
                    outcome="YES",
                    parent_market_id=parent_market_id,
                    parent_question=parent_question,
                    parent_event_title=parent_event_title,
                    parent_url=parent_url,
                    parent_end_date=parent_end_date,
                    parent_liquidity=parent_liquidity,
                    parent_volume=parent_volume,
                    interval=interval,
                    fidelity=fidelity,
                )
                if result is not None:
                    analyses.append(result)

            if no_token_id:
                result = self.analyze_token(
                    token_id=str(no_token_id),
                    outcome="NO",
                    parent_market_id=parent_market_id,
                    parent_question=parent_question,
                    parent_event_title=parent_event_title,
                    parent_url=parent_url,
                    parent_end_date=parent_end_date,
                    parent_liquidity=parent_liquidity,
                    parent_volume=parent_volume,
                    interval=interval,
                    fidelity=fidelity,
                )
                if result is not None:
                    analyses.append(result)

        analyses.sort(key=lambda x: x.score, reverse=True)
        return analyses

    @staticmethod
    def save_json(analyses: List[TokenAnalysis], output_json: str = OUTPUT_JSON) -> None:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in analyses], f, ensure_ascii=False, indent=2)
        print(f"\nJSON gravado em: {output_json}")

    def print_exclusion_summary(self) -> None:
        print("\nResumo de exclusões:\n")
        if not self.exclusion_reasons:
            print("Nenhuma exclusão registada.")
            return

        for reason, count in self.exclusion_reasons.most_common():
            print(f"  - {reason}: {count}")

    @staticmethod
    def print_summary(analyses: List[TokenAnalysis], limit: int = 20) -> None:
        print(f"\nEncontradas {len(analyses)} análises de tokens elegíveis\n")
        for idx, item in enumerate(analyses[:limit], start=1):
            print(f"{idx:02d}. {item.parent_question} [{item.outcome}]")
            print(f"    Event                  : {item.parent_event_title}")
            print(f"    URL                    : {item.parent_url}")
            print(f"    Token ID               : {item.token_id}")
            print(f"    End date               : {item.end_date}")
            print(f"    Days to resolution     : {item.days_to_resolution}")
            print(f"    Liquidity              : {item.liquidity}")
            print(f"    Volume                 : {item.volume}")
            print(f"    BTC relevance score    : {item.btc_relevance_score}")
            print(f"    Midpoint               : {item.midpoint}")
            print(f"    Best BUY price         : {item.buy_price}")
            print(f"    Best SELL price        : {item.sell_price}")
            print(f"    Spread                 : {item.spread}")
            print(f"    Last trade             : {item.last_trade_price} ({item.last_trade_side})")
            print(f"    History points         : {item.history_points}")
            print(f"    First / Last           : {item.first_price} -> {item.last_price}")
            print(f"    Return %               : {item.return_pct}")
            print(f"    Volatility             : {item.volatility}")
            print(f"    Avg abs change         : {item.avg_abs_change}")
            print(f"    Min / Max              : {item.min_price} / {item.max_price}")
            print(f"    Trend consistency      : {item.trend_consistency}")
            print(f"    Positive return bonus  : {item.positive_return_bonus}")
            print(f"    Trend bonus            : {item.trend_bonus}")
            print(f"    Pump penalty           : {item.pump_penalty}")
            print(f"    Midpoint penalty       : {item.midpoint_penalty}")
            print(f"    Spread penalty         : {item.spread_penalty}")
            print(f"    Time penalty           : {item.time_penalty}")
            print(f"    BTC bonus              : {item.btc_bonus}")
            print(f"    Liquidity bonus        : {item.liquidity_bonus}")
            print(f"    Score                  : {item.score:.4f}")
            print("-" * 100)


if __name__ == "__main__":
    try:
        analyzer = ClobAnalyzer(timeout=20, sleep_between_calls=0.05)

        analyses = analyzer.analyze_from_json(
            input_json=INPUT_JSON,
            interval="1d",
            fidelity=60,
            top_n=None,
        )

        analyzer.print_summary(analyses, limit=20)
        analyzer.print_exclusion_summary()
        analyzer.save_json(analyses, OUTPUT_JSON)

    except requests.HTTPError as e:
        print(f"Erro HTTP: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)