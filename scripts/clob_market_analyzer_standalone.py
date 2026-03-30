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

    midpoint_penalty: float
    spread_penalty: float
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
                "User-Agent": "clob-market-analyzer-standalone/2.0",
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
        # API/docs sometimes show mid or mid_price depending on surface
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
    def _midpoint_extreme_penalty(midpoint: Optional[float]) -> float:
        """
        Penaliza contratos muito perto de 0 ou 1.
        Zona saudável ~ [0.10, 0.90].
        """
        if midpoint is None:
            return 1.5

        if midpoint < 0.03 or midpoint > 0.97:
            return 4.0
        if midpoint < 0.05 or midpoint > 0.95:
            return 2.5
        if midpoint < 0.10 or midpoint > 0.90:
            return 1.0
        return 0.0

    @staticmethod
    def _spread_penalty(spread: Optional[float]) -> float:
        """
        Tighter spread = melhor mercado.
        """
        if spread is None:
            return 2.0
        if spread >= 0.10:
            return 4.0
        if spread >= 0.05:
            return 2.0
        if spread >= 0.02:
            return 1.0
        return 0.0

    @staticmethod
    def _score(
        midpoint: Optional[float],
        buy_price: Optional[float],
        sell_price: Optional[float],
        spread: Optional[float],
        last_trade_price: Optional[float],
        history_points: int,
        return_pct: Optional[float],
        volatility: Optional[float],
        avg_abs_change: Optional[float],
    ) -> Tuple[float, float, float]:
        """
        Score mais orientado a trading real:
        - favorece histórico suficiente
        - favorece movimento absoluto e alguma volatilidade
        - penaliza spread largo
        - penaliza contratos muito perto de 0 ou 1
        - reduz peso de return_pct puro
        """
        history_term = math.log1p(max(history_points, 0))
        return_term = min(abs(return_pct), 25.0) if return_pct is not None else 0.0
        vol_term = volatility or 0.0
        change_term = avg_abs_change or 0.0

        midpoint_bonus = 1.0 if midpoint is not None else 0.0
        trade_bonus = 1.0 if last_trade_price is not None else 0.0
        price_bonus = 1.0 if (buy_price is not None and sell_price is not None) else 0.0

        midpoint_penalty = ClobAnalyzer._midpoint_extreme_penalty(midpoint)
        spread_penalty = ClobAnalyzer._spread_penalty(spread)

        raw_score = (
            1.4 * history_term
            + 0.03 * return_term
            + 20.0 * vol_term
            + 60.0 * change_term
            + midpoint_bonus
            + trade_bonus
            + price_bonus
            - midpoint_penalty
            - spread_penalty
        )

        return raw_score, midpoint_penalty, spread_penalty

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
        buy_price = None
        sell_price = None
        spread = None
        last_trade_price = None
        last_trade_side = None
        history: List[Dict[str, Any]] = []

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

        score, midpoint_penalty, spread_penalty = self._score(
            midpoint=midpoint,
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            last_trade_price=last_trade_price,
            history_points=history_points,
            return_pct=metrics["return_pct"],
            volatility=metrics["volatility"],
            avg_abs_change=metrics["avg_abs_change"],
        )

        ranking_reason = {
            "history_points": history_points,
            "midpoint": midpoint,
            "buy_price": buy_price,
            "sell_price": sell_price,
            "spread": spread,
            "last_trade_price": last_trade_price,
            "return_pct": metrics["return_pct"],
            "volatility": metrics["volatility"],
            "avg_abs_change": metrics["avg_abs_change"],
            "midpoint_penalty": midpoint_penalty,
            "spread_penalty": spread_penalty,
        }

        return TokenAnalysis(
            parent_market_id=parent_market_id,
            parent_question=parent_question,
            parent_event_title=parent_event_title,
            parent_url=parent_url,
            outcome=outcome,
            token_id=token_id,
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
            midpoint_penalty=midpoint_penalty,
            spread_penalty=spread_penalty,
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
                analyses.append(
                    self.analyze_token(
                        token_id=str(yes_token_id),
                        outcome="YES",
                        parent_market_id=parent_market_id,
                        parent_question=parent_question,
                        parent_event_title=parent_event_title,
                        parent_url=parent_url,
                        interval=interval,
                        fidelity=fidelity,
                    )
                )

            if no_token_id:
                analyses.append(
                    self.analyze_token(
                        token_id=str(no_token_id),
                        outcome="NO",
                        parent_market_id=parent_market_id,
                        parent_question=parent_question,
                        parent_event_title=parent_event_title,
                        parent_url=parent_url,
                        interval=interval,
                        fidelity=fidelity,
                    )
                )

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
            print(f"    Event            : {item.parent_event_title}")
            print(f"    URL              : {item.parent_url}")
            print(f"    Token ID         : {item.token_id}")
            print(f"    Midpoint         : {item.midpoint}")
            print(f"    Best BUY price   : {item.buy_price}")
            print(f"    Best SELL price  : {item.sell_price}")
            print(f"    Spread           : {item.spread}")
            print(f"    Last trade       : {item.last_trade_price} ({item.last_trade_side})")
            print(f"    History points   : {item.history_points}")
            print(f"    First / Last     : {item.first_price} -> {item.last_price}")
            print(f"    Return %         : {item.return_pct}")
            print(f"    Volatility       : {item.volatility}")
            print(f"    Avg abs change   : {item.avg_abs_change}")
            print(f"    Min / Max        : {item.min_price} / {item.max_price}")
            print(f"    Midpoint penalty : {item.midpoint_penalty}")
            print(f"    Spread penalty   : {item.spread_penalty}")
            print(f"    Score            : {item.score:.4f}")
            print("-" * 100)


if __name__ == "__main__":
    try:
        analyzer = ClobAnalyzer(timeout=20, sleep_between_calls=0.05)

        analyses = analyzer.analyze_from_json(
            input_json=INPUT_JSON,
            interval="1d",
            fidelity=60,
            top_n=20,  # mete None para analisar tudo
        )

        analyzer.print_summary(analyses, limit=20)
        analyzer.save_json(analyses, OUTPUT_JSON)

    except requests.HTTPError as e:
        print(f"Erro HTTP: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)