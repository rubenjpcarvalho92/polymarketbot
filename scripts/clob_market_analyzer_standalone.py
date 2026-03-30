# scripts/clob_market_analyzer_standalone.py
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


CLOB_BASE_URL = "https://clob.polymarket.com"
INPUT_JSON = "gamma_scan_results_filtered.json"
OUTPUT_JSON = "token_analysis_results.json"


@dataclass
class TokenAnalysis:
    parent_market_id: Optional[str]
    parent_question: Optional[str]
    parent_event_title: Optional[str]
    parent_url: Optional[str]

    outcome: str
    token_id: str

    midpoint: Optional[float]
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
                "User-Agent": "clob-market-analyzer-standalone/1.0",
            }
        )

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

    def get_midpoint(self, token_id: str) -> Optional[float]:
        data = self._get("/midpoint", {"token_id": token_id})
        # docs show {"mid_price": "0.45"} on REST
        mid = data.get("mid_price")
        if mid is None:
            mid = data.get("mid")
        return self._to_float(mid)

    def get_last_trade_price(self, token_id: str) -> Tuple[Optional[float], Optional[str]]:
        data = self._get("/last-trade-price", {"token_id": token_id})
        price = self._to_float(data.get("price"))
        side = data.get("side")
        return price, side

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
        if not isinstance(history, list):
            return []
        return history

    @staticmethod
    def _extract_prices(history: List[Dict[str, Any]]) -> List[float]:
        prices: List[float] = []
        for row in history:
            p = row.get("p")
            try:
                prices.append(float(p))
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

        return {
            "first_price": first_price,
            "last_price": last_price,
            "return_pct": return_pct,
            "volatility": volatility,
            "avg_abs_change": avg_abs_change,
            "min_price": min_price,
            "max_price": max_price,
        }

    @staticmethod
    def _score(
        midpoint: Optional[float],
        last_trade_price: Optional[float],
        history_points: int,
        return_pct: Optional[float],
        volatility: Optional[float],
        avg_abs_change: Optional[float],
    ) -> float:
        # Score simples para triagem inicial
        history_term = math.log1p(max(history_points, 0))
        return_term = abs(return_pct) if return_pct is not None else 0.0
        vol_term = volatility if volatility is not None else 0.0
        change_term = avg_abs_change if avg_abs_change is not None else 0.0

        midpoint_bonus = 1.0 if midpoint is not None else 0.0
        trade_bonus = 1.0 if last_trade_price is not None else 0.0

        return (
            1.2 * history_term
            + 0.08 * return_term
            + 8.0 * vol_term
            + 20.0 * change_term
            + midpoint_bonus
            + trade_bonus
        )

    def analyze_token(
        self,
        token_id: str,
        outcome: str,
        parent_market_id: Optional[str],
        parent_question: Optional[str],
        parent_event_title: Optional[str],
        parent_url: Optional[str],
        interval: str,
        fidelity: int,
    ) -> TokenAnalysis:
        midpoint = None
        last_trade_price = None
        last_trade_side = None
        history: List[Dict[str, Any]] = []

        try:
            midpoint = self.get_midpoint(token_id)
        except Exception:
            midpoint = None

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

        score = self._score(
            midpoint=midpoint,
            last_trade_price=last_trade_price,
            history_points=history_points,
            return_pct=metrics["return_pct"],
            volatility=metrics["volatility"],
            avg_abs_change=metrics["avg_abs_change"],
        )

        ranking_reason = {
            "history_points": history_points,
            "midpoint": midpoint,
            "last_trade_price": last_trade_price,
            "return_pct": metrics["return_pct"],
            "volatility": metrics["volatility"],
            "avg_abs_change": metrics["avg_abs_change"],
        }

        return TokenAnalysis(
            parent_market_id=parent_market_id,
            parent_question=parent_question,
            parent_event_title=parent_event_title,
            parent_url=parent_url,
            outcome=outcome,
            token_id=token_id,
            midpoint=midpoint,
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

            yes_token_id = market.get("yes_token_id")
            no_token_id = market.get("no_token_id")

            if yes_token_id:
                analysis_yes = self.analyze_token(
                    token_id=str(yes_token_id),
                    outcome="YES",
                    parent_market_id=parent_market_id,
                    parent_question=parent_question,
                    parent_event_title=parent_event_title,
                    parent_url=parent_url,
                    interval=interval,
                    fidelity=fidelity,
                )
                analyses.append(analysis_yes)

            if no_token_id:
                analysis_no = self.analyze_token(
                    token_id=str(no_token_id),
                    outcome="NO",
                    parent_market_id=parent_market_id,
                    parent_question=parent_question,
                    parent_event_title=parent_event_title,
                    parent_url=parent_url,
                    interval=interval,
                    fidelity=fidelity,
                )
                analyses.append(analysis_no)

        analyses.sort(key=lambda x: x.score, reverse=True)
        return analyses

    @staticmethod
    def save_json(analyses: List[TokenAnalysis], output_json: str = OUTPUT_JSON) -> None:
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in analyses], f, ensure_ascii=False, indent=2)
        print(f"\nJSON gravado em: {output_json}")

    @staticmethod
    def print_summary(analyses: List[TokenAnalysis], limit: int = 20) -> None:
        print(f"\nEncontradas {len(analyses)} análises de tokens\n")
        for idx, item in enumerate(analyses[:limit], start=1):
            print(f"{idx:02d}. {item.parent_question} [{item.outcome}]")
            print(f"    Event          : {item.parent_event_title}")
            print(f"    URL            : {item.parent_url}")
            print(f"    Token ID       : {item.token_id}")
            print(f"    Midpoint       : {item.midpoint}")
            print(f"    Last trade     : {item.last_trade_price} ({item.last_trade_side})")
            print(f"    History points : {item.history_points}")
            print(f"    First / Last   : {item.first_price} -> {item.last_price}")
            print(f"    Return %       : {item.return_pct}")
            print(f"    Volatility     : {item.volatility}")
            print(f"    Avg abs change : {item.avg_abs_change}")
            print(f"    Min / Max      : {item.min_price} / {item.max_price}")
            print(f"    Score          : {item.score:.4f}")
            print("-" * 100)


if __name__ == "__main__":
    try:
        analyzer = ClobAnalyzer(timeout=20, sleep_between_calls=0.05)

        analyses = analyzer.analyze_from_json(
            input_json=INPUT_JSON,
            interval="1d",
            fidelity=60,
            top_n=20,  # None para analisar tudo
        )

        analyzer.print_summary(analyses, limit=20)
        analyzer.save_json(analyses, OUTPUT_JSON)

    except requests.HTTPError as e:
        print(f"Erro HTTP: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)