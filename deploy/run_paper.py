from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"

CANDIDATES_JSON = BASE_DIR / "token_analysis_results.json"
PORTFOLIO_STATE_JSON = LOGS_DIR / "portfolio_state.json"
CYCLES_CSV = LOGS_DIR / "cycles.csv"
TRADES_CSV = LOGS_DIR / "trades.csv"
PORTFOLIO_CSV = LOGS_DIR / "portfolio.csv"

CLOB_BASE_URL = "https://clob.polymarket.com"

DEFAULT_TOP_CANDIDATES_TO_CHECK = 10
DEFAULT_HISTORY_POINTS = 80
DEFAULT_SLEEP_SECONDS = 0.05


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_logs_dir() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def safe_float(value: Any) -> Optional[float]:
    if value in (None, "", []):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def env_str(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def append_csv_row(path: Path, row: Dict[str, Any]) -> None:
    ensure_logs_dir()
    file_exists = path.exists()
    fieldnames = list(row.keys())

    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists or path.stat().st_size == 0:
            writer.writeheader()
        writer.writerow(row)


def print_section(title: str) -> None:
    print(title)
    print("-" * len(title))


@dataclass
class CandidateToken:
    parent_market_id: Optional[str]
    parent_question: Optional[str]
    parent_event_title: Optional[str]
    parent_url: Optional[str]
    outcome: str
    token_id: str
    midpoint: Optional[float]
    buy_price: Optional[float]
    sell_price: Optional[float]
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
    positive_return_bonus: Optional[float]
    trend_bonus: Optional[float]
    pump_penalty: Optional[float]
    midpoint_penalty: Optional[float]
    spread_penalty: Optional[float]
    score: float
    ranking_reason: Dict[str, Any]


@dataclass
class OpenPosition:
    token_id: str
    market_name: str
    outcome: str
    quantity: float
    entry_price: float
    entry_cost: float
    entry_timestamp: str


@dataclass
class PortfolioState:
    starting_cash: float
    cash_balance: float
    realized_pnl: float
    open_position: Optional[OpenPosition]

    @staticmethod
    def from_dict(data: Dict[str, Any], starting_cash: float) -> "PortfolioState":
        open_position_raw = data.get("open_position")
        open_position = None
        if isinstance(open_position_raw, dict):
            open_position = OpenPosition(
                token_id=str(open_position_raw["token_id"]),
                market_name=str(open_position_raw["market_name"]),
                outcome=str(open_position_raw["outcome"]),
                quantity=float(open_position_raw["quantity"]),
                entry_price=float(open_position_raw["entry_price"]),
                entry_cost=float(open_position_raw["entry_cost"]),
                entry_timestamp=str(open_position_raw["entry_timestamp"]),
            )

        return PortfolioState(
            starting_cash=float(data.get("starting_cash", starting_cash)),
            cash_balance=float(data.get("cash_balance", starting_cash)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            open_position=open_position,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "starting_cash": self.starting_cash,
            "cash_balance": self.cash_balance,
            "realized_pnl": self.realized_pnl,
            "open_position": asdict(self.open_position) if self.open_position else None,
        }


class PolymarketPaperRunner:
    def __init__(self) -> None:
        self.timeout = env_int("HTTP_TIMEOUT", 20)
        self.sleep_between_calls = env_float("HTTP_SLEEP_SECONDS", DEFAULT_SLEEP_SECONDS)

        self.trading_mode = env_str("TRADING_MODE", "paper")
        self.dry_run = env_bool("DRY_RUN", True)
        self.strategy_name = env_str("STRATEGY_NAME", "macd_classic")
        self.position_sizing_mode = env_str("POSITION_SIZING_MODE", "fixed_percent")
        self.default_order_size = env_float("DEFAULT_ORDER_SIZE", 10.0)
        self.paper_starting_cash = env_float("PAPER_STARTING_CASH", 100.0)

        self.max_candidates_to_check = env_int("MAX_CANDIDATES_TO_CHECK", DEFAULT_TOP_CANDIDATES_TO_CHECK)
        self.history_points = env_int("HISTORY_POINTS", DEFAULT_HISTORY_POINTS)

        self.buy_min_midpoint = env_float("BUY_MIN_MIDPOINT", 0.10)
        self.buy_max_midpoint = env_float("BUY_MAX_MIDPOINT", 0.90)
        self.max_spread = env_float("MAX_SPREAD", 0.02)
        self.min_history_points = env_int("MIN_HISTORY_POINTS", 35)
        self.min_return_pct = env_float("MIN_RETURN_PCT", 0.0)
        self.min_trend_consistency = env_float("MIN_TREND_CONSISTENCY", 0.55)
        self.max_pump_return_pct = env_float("MAX_PUMP_RETURN_PCT", 80.0)

        self.entry_min_imbalance = env_float("ENTRY_MIN_IMBALANCE", 0.50)
        self.entry_max_ask_to_bid_ratio = env_float("ENTRY_MAX_ASK_TO_BID_RATIO", 5.0)

        self.fixed_percent_size = env_float("FIXED_PERCENT_SIZE", 0.02)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "polymarket-paper-runner-buy-selector/1.0",
            }
        )

    def _get(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"{CLOB_BASE_URL}{path}"
        resp = self.session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def load_portfolio_state(self) -> PortfolioState:
        ensure_logs_dir()
        if not PORTFOLIO_STATE_JSON.exists():
            return PortfolioState(
                starting_cash=self.paper_starting_cash,
                cash_balance=self.paper_starting_cash,
                realized_pnl=0.0,
                open_position=None,
            )

        with PORTFOLIO_STATE_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)

        return PortfolioState.from_dict(data, starting_cash=self.paper_starting_cash)

    def save_portfolio_state(self, state: PortfolioState) -> None:
        ensure_logs_dir()
        with PORTFOLIO_STATE_JSON.open("w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    def load_candidates(self) -> List[CandidateToken]:
        if not CANDIDATES_JSON.exists():
            raise FileNotFoundError(f"Ficheiro não encontrado: {CANDIDATES_JSON}")

        with CANDIDATES_JSON.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            raise ValueError("token_analysis_results.json tem de ser uma lista.")

        candidates: List[CandidateToken] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                candidates.append(
                    CandidateToken(
                        parent_market_id=item.get("parent_market_id"),
                        parent_question=item.get("parent_question"),
                        parent_event_title=item.get("parent_event_title"),
                        parent_url=item.get("parent_url"),
                        outcome=str(item.get("outcome", "")),
                        token_id=str(item.get("token_id", "")),
                        midpoint=safe_float(item.get("midpoint")),
                        buy_price=safe_float(item.get("buy_price")),
                        sell_price=safe_float(item.get("sell_price")),
                        spread=safe_float(item.get("spread")),
                        last_trade_price=safe_float(item.get("last_trade_price")),
                        last_trade_side=item.get("last_trade_side"),
                        history_points=int(item.get("history_points", 0)),
                        first_price=safe_float(item.get("first_price")),
                        last_price=safe_float(item.get("last_price")),
                        return_pct=safe_float(item.get("return_pct")),
                        volatility=safe_float(item.get("volatility")),
                        avg_abs_change=safe_float(item.get("avg_abs_change")),
                        min_price=safe_float(item.get("min_price")),
                        max_price=safe_float(item.get("max_price")),
                        trend_consistency=safe_float(item.get("trend_consistency")),
                        positive_return_bonus=safe_float(item.get("positive_return_bonus")),
                        trend_bonus=safe_float(item.get("trend_bonus")),
                        pump_penalty=safe_float(item.get("pump_penalty")),
                        midpoint_penalty=safe_float(item.get("midpoint_penalty")),
                        spread_penalty=safe_float(item.get("spread_penalty")),
                        score=float(item.get("score", 0.0)),
                        ranking_reason=item.get("ranking_reason", {}) if isinstance(item.get("ranking_reason"), dict) else {},
                    )
                )
            except Exception:
                continue

        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    def get_price(self, token_id: str, side: str) -> Optional[float]:
        data = self._get("/price", {"token_id": token_id, "side": side})
        return safe_float(data.get("price"))

    def get_midpoint(self, token_id: str) -> Optional[float]:
        data = self._get("/midpoint", {"token_id": token_id})
        return safe_float(data.get("mid")) or safe_float(data.get("mid_price"))

    def get_spread(self, token_id: str) -> Optional[float]:
        data = self._get("/spread", {"token_id": token_id})
        return safe_float(data.get("spread"))

    def get_last_trade_price(self, token_id: str) -> Tuple[Optional[float], Optional[str]]:
        data = self._get("/last-trade-price", {"token_id": token_id})
        return safe_float(data.get("price")), data.get("side")

    def get_book_snapshot(self, token_id: str) -> Dict[str, Optional[float]]:
        best_bid = self.get_price(token_id, "SELL")
        time.sleep(self.sleep_between_calls)

        best_ask = self.get_price(token_id, "BUY")
        time.sleep(self.sleep_between_calls)

        midpoint = self.get_midpoint(token_id)
        time.sleep(self.sleep_between_calls)

        spread = self.get_spread(token_id)
        time.sleep(self.sleep_between_calls)

        # fallback básico, já que o endpoint do book pode variar no projeto
        bid_size = None
        ask_size = None

        try:
            data = self._get("/book", {"token_id": token_id})
            bids = data.get("bids", []) if isinstance(data, dict) else []
            asks = data.get("asks", []) if isinstance(data, dict) else []

            if isinstance(bids, list) and bids:
                first_bid = bids[0]
                if isinstance(first_bid, dict):
                    bid_size = safe_float(first_bid.get("size")) or safe_float(first_bid.get("quantity"))
                elif isinstance(first_bid, list) and len(first_bid) >= 2:
                    bid_size = safe_float(first_bid[1])

            if isinstance(asks, list) and asks:
                first_ask = asks[0]
                if isinstance(first_ask, dict):
                    ask_size = safe_float(first_ask.get("size")) or safe_float(first_ask.get("quantity"))
                elif isinstance(first_ask, list) and len(first_ask) >= 2:
                    ask_size = safe_float(first_ask[1])
        except Exception:
            bid_size = None
            ask_size = None

        return {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "midpoint": midpoint,
            "spread": spread,
            "bid_size": bid_size,
            "ask_size": ask_size,
        }

    def get_prices_history(
        self,
        token_id: str,
        interval: str = "1d",
        fidelity: int = 60,
    ) -> List[float]:
        data = self._get(
            "/prices-history",
            {
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
        )
        history = data.get("history", [])
        if not isinstance(history, list):
            return []

        prices: List[float] = []
        for row in history:
            if not isinstance(row, dict):
                continue
            p = safe_float(row.get("p"))
            if p is not None:
                prices.append(p)
        return prices

    @staticmethod
    def ema(values: List[float], period: int) -> List[float]:
        if not values:
            return []

        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1 - alpha) * result[-1])
        return result

    def macd_signal(self, prices: List[float]) -> Dict[str, Any]:
        if len(prices) < 35:
            return {
                "signal": "HOLD",
                "reason": "not_enough_real_history_for_macd",
                "metadata": {},
            }

        ema12 = self.ema(prices, 12)
        ema26 = self.ema(prices, 26)

        macd_line = [a - b for a, b in zip(ema12, ema26)]
        signal_line = self.ema(macd_line, 9)
        histogram = [a - b for a, b in zip(macd_line, signal_line)]

        if len(macd_line) < 2 or len(signal_line) < 2:
            return {
                "signal": "HOLD",
                "reason": "macd_series_too_short",
                "metadata": {},
            }

        prev_macd = macd_line[-2]
        curr_macd = macd_line[-1]
        prev_signal = signal_line[-2]
        curr_signal = signal_line[-1]
        curr_hist = histogram[-1]

        if prev_macd <= prev_signal and curr_macd > curr_signal and curr_hist > 0:
            return {
                "signal": "BUY",
                "reason": "macd_bullish_crossover",
                "metadata": {
                    "prev_macd": prev_macd,
                    "curr_macd": curr_macd,
                    "prev_signal": prev_signal,
                    "curr_signal": curr_signal,
                    "histogram": curr_hist,
                },
            }

        if prev_macd >= prev_signal and curr_macd < curr_signal and curr_hist < 0:
            return {
                "signal": "SELL",
                "reason": "macd_bearish_crossover",
                "metadata": {
                    "prev_macd": prev_macd,
                    "curr_macd": curr_macd,
                    "prev_signal": prev_signal,
                    "curr_signal": curr_signal,
                    "histogram": curr_hist,
                },
            }

        return {
            "signal": "HOLD",
            "reason": "macd_no_crossover",
            "metadata": {
                "prev_macd": prev_macd,
                "curr_macd": curr_macd,
                "prev_signal": prev_signal,
                "curr_signal": curr_signal,
                "histogram": curr_hist,
            },
        }

    @staticmethod
    def compute_return_pct(prices: List[float]) -> Optional[float]:
        if len(prices) < 2 or prices[0] == 0:
            return None
        return ((prices[-1] - prices[0]) / prices[0]) * 100.0

    @staticmethod
    def compute_trend_consistency(prices: List[float]) -> Optional[float]:
        if len(prices) < 2:
            return None
        diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        if not diffs:
            return None
        positive_moves = sum(1 for d in diffs if d > 0)
        return positive_moves / len(diffs)

    def calculate_order_cash(self, portfolio: PortfolioState) -> float:
        if self.position_sizing_mode == "fixed_percent":
            return max(0.0, portfolio.cash_balance * self.fixed_percent_size)
        return min(self.default_order_size, portfolio.cash_balance)

    def passes_buy_filter(
        self,
        candidate: CandidateToken,
        prices: List[float],
        book: Dict[str, Optional[float]],
    ) -> Tuple[bool, str]:
        midpoint = book.get("midpoint")
        spread = book.get("spread")
        bid_size = book.get("bid_size")
        ask_size = book.get("ask_size")

        if midpoint is None:
            midpoint = candidate.midpoint
        if spread is None:
            spread = candidate.spread

        if midpoint is None:
            return False, "missing_midpoint"

        if midpoint < self.buy_min_midpoint or midpoint > self.buy_max_midpoint:
            return False, "midpoint_outside_buy_range"

        if spread is None:
            return False, "missing_spread"

        if spread > self.max_spread:
            return False, "spread_too_wide"

        if len(prices) < self.min_history_points:
            return False, "not_enough_real_history"

        return_pct = self.compute_return_pct(prices)
        trend_consistency = self.compute_trend_consistency(prices)

        if return_pct is None:
            return False, "missing_return"

        if return_pct <= self.min_return_pct:
            return False, "not_positive_trend"

        if return_pct > self.max_pump_return_pct:
            return False, "too_extended"

        if trend_consistency is None or trend_consistency < self.min_trend_consistency:
            return False, "weak_trend_consistency"

        if bid_size is not None and ask_size is not None and (bid_size + ask_size) > 0:
            imbalance = bid_size / (bid_size + ask_size)
            if imbalance < self.entry_min_imbalance:
                return False, "weak_bid_imbalance"

            if bid_size > 0 and ask_size / bid_size > self.entry_max_ask_to_bid_ratio:
                return False, "ask_wall_too_large"

        return True, "buy_filter_pass"

    def evaluate_buy_candidate(self, candidate: CandidateToken) -> Dict[str, Any]:
        prices = self.get_prices_history(candidate.token_id, interval="1d", fidelity=60)
        time.sleep(self.sleep_between_calls)

        book = self.get_book_snapshot(candidate.token_id)
        time.sleep(self.sleep_between_calls)

        last_trade_price, last_trade_side = self.get_last_trade_price(candidate.token_id)
        time.sleep(self.sleep_between_calls)

        strategy_result = self.macd_signal(prices)
        passes_filter, filter_reason = self.passes_buy_filter(candidate, prices, book)

        return {
            "candidate": candidate,
            "prices": prices,
            "book": book,
            "last_trade_price": last_trade_price,
            "last_trade_side": last_trade_side,
            "strategy_result": strategy_result,
            "passes_filter": passes_filter,
            "filter_reason": filter_reason,
        }

    def choose_best_buy_candidate(self, candidates: List[CandidateToken]) -> Optional[Dict[str, Any]]:
        checked = 0

        for candidate in candidates:
            if checked >= self.max_candidates_to_check:
                break

            checked += 1
            evaluation = self.evaluate_buy_candidate(candidate)
            strategy_signal = evaluation["strategy_result"]["signal"]

            print()
            print(f"Checking candidate {checked}/{min(len(candidates), self.max_candidates_to_check)}")
            print(f"Market             : {candidate.parent_question} [{candidate.outcome}]")
            print(f"Token ID           : {candidate.token_id}")
            print(f"Scanner score      : {candidate.score:.4f}")
            print(f"Buy filter         : {evaluation['passes_filter']} ({evaluation['filter_reason']})")
            print(f"Strategy signal    : {strategy_signal} ({evaluation['strategy_result']['reason']})")

            book = evaluation["book"]
            print(f"best_bid           : {book.get('best_bid')}")
            print(f"best_ask           : {book.get('best_ask')}")
            print(f"bid_size           : {book.get('bid_size')}")
            print(f"ask_size           : {book.get('ask_size')}")
            print(f"spread             : {book.get('spread')}")
            print(f"midpoint           : {book.get('midpoint')}")
            print(f"history_points     : {len(evaluation['prices'])}")

            if evaluation["passes_filter"] and strategy_signal == "BUY":
                return evaluation

        return None

    def buy_position(self, portfolio: PortfolioState, evaluation: Dict[str, Any]) -> Tuple[PortfolioState, Dict[str, Any]]:
        candidate: CandidateToken = evaluation["candidate"]
        book = evaluation["book"]

        buy_price = book.get("best_ask")
        midpoint = book.get("midpoint")

        if buy_price is None:
            raise ValueError("Não foi possível obter best_ask para compra.")

        order_cash = self.calculate_order_cash(portfolio)
        if order_cash <= 0:
            raise ValueError("Sem capital disponível para abrir posição.")

        quantity = order_cash / buy_price
        entry_cost = quantity * buy_price

        portfolio.cash_balance -= entry_cost
        portfolio.open_position = OpenPosition(
            token_id=candidate.token_id,
            market_name=candidate.parent_question or candidate.parent_event_title or candidate.token_id,
            outcome=candidate.outcome,
            quantity=quantity,
            entry_price=buy_price,
            entry_cost=entry_cost,
            entry_timestamp=utc_now_iso(),
        )

        market_value = quantity * (midpoint if midpoint is not None else buy_price)
        unrealized_pnl = market_value - entry_cost
        equity_total = portfolio.cash_balance + market_value
        total_pnl = portfolio.realized_pnl + unrealized_pnl
        return_pct = ((equity_total - portfolio.starting_cash) / portfolio.starting_cash) * 100.0

        trade_row = {
            "timestamp": utc_now_iso(),
            "token_id": candidate.token_id,
            "market_name": portfolio.open_position.market_name,
            "outcome": candidate.outcome,
            "side": "BUY",
            "price": buy_price,
            "size": quantity,
            "order_status": "FILLED",
            "cash_balance": portfolio.cash_balance,
            "invested_value": entry_cost,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "return_pct": return_pct,
        }
        append_csv_row(TRADES_CSV, trade_row)

        portfolio_row = {
            "timestamp": utc_now_iso(),
            "starting_cash": portfolio.starting_cash,
            "cash_balance": portfolio.cash_balance,
            "invested_value": entry_cost,
            "market_value": market_value,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "total_pnl": total_pnl,
            "return_pct": return_pct,
        }
        append_csv_row(PORTFOLIO_CSV, portfolio_row)

        return portfolio, {
            "buy_price": buy_price,
            "quantity": quantity,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "return_pct": return_pct,
        }

    def sell_position(self, portfolio: PortfolioState) -> Tuple[PortfolioState, Dict[str, Any]]:
        if portfolio.open_position is None:
            raise ValueError("Não existe posição aberta para vender.")

        position = portfolio.open_position
        book = self.get_book_snapshot(position.token_id)
        time.sleep(self.sleep_between_calls)

        prices = self.get_prices_history(position.token_id, interval="1d", fidelity=60)
        strategy_result = self.macd_signal(prices)

        sell_price = book.get("best_bid")
        midpoint = book.get("midpoint")

        if sell_price is None:
            raise ValueError("Não foi possível obter best_bid para venda.")

        proceeds = position.quantity * sell_price
        realized_trade_pnl = proceeds - position.entry_cost

        portfolio.cash_balance += proceeds
        portfolio.realized_pnl += realized_trade_pnl
        portfolio.open_position = None

        market_value = 0.0
        unrealized_pnl = 0.0
        equity_total = portfolio.cash_balance
        total_pnl = portfolio.realized_pnl
        return_pct = ((equity_total - portfolio.starting_cash) / portfolio.starting_cash) * 100.0

        trade_row = {
            "timestamp": utc_now_iso(),
            "token_id": position.token_id,
            "market_name": position.market_name,
            "outcome": position.outcome,
            "side": "SELL",
            "price": sell_price,
            "size": position.quantity,
            "order_status": "FILLED",
            "cash_balance": portfolio.cash_balance,
            "invested_value": 0.0,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "return_pct": return_pct,
        }
        append_csv_row(TRADES_CSV, trade_row)

        portfolio_row = {
            "timestamp": utc_now_iso(),
            "starting_cash": portfolio.starting_cash,
            "cash_balance": portfolio.cash_balance,
            "invested_value": 0.0,
            "market_value": market_value,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "total_pnl": total_pnl,
            "return_pct": return_pct,
        }
        append_csv_row(PORTFOLIO_CSV, portfolio_row)

        return portfolio, {
            "sell_price": sell_price,
            "midpoint": midpoint,
            "strategy_result": strategy_result,
            "realized_trade_pnl": realized_trade_pnl,
            "equity_total": equity_total,
            "return_pct": return_pct,
        }

    def log_cycle(
        self,
        token_id: str,
        market_name: str,
        outcome: str,
        book: Dict[str, Optional[float]],
        signal: str,
        reason: str,
        order_status: str,
        portfolio: PortfolioState,
    ) -> None:
        invested_value = portfolio.open_position.entry_cost if portfolio.open_position else 0.0
        market_value = 0.0
        unrealized_pnl = 0.0

        if portfolio.open_position and portfolio.open_position.token_id == token_id:
            midpoint = book.get("midpoint")
            if midpoint is None:
                midpoint = portfolio.open_position.entry_price
            market_value = portfolio.open_position.quantity * midpoint
            unrealized_pnl = market_value - portfolio.open_position.entry_cost

        equity_total = portfolio.cash_balance + market_value
        total_pnl = portfolio.realized_pnl + unrealized_pnl
        return_pct = ((equity_total - portfolio.starting_cash) / portfolio.starting_cash) * 100.0

        row = {
            "timestamp": utc_now_iso(),
            "token_id": token_id,
            "market_name": market_name,
            "outcome": outcome,
            "best_bid": book.get("best_bid"),
            "best_ask": book.get("best_ask"),
            "midpoint": book.get("midpoint"),
            "spread": book.get("spread"),
            "bid_size": book.get("bid_size"),
            "ask_size": book.get("ask_size"),
            "signal": signal,
            "reason": reason,
            "position_side": outcome if portfolio.open_position else "",
            "limit_price": book.get("best_ask") if signal == "BUY" else book.get("best_bid"),
            "order_status": order_status,
            "cash_balance": portfolio.cash_balance,
            "invested_value": invested_value,
            "market_value": market_value,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": unrealized_pnl,
            "equity_total": equity_total,
            "total_pnl": total_pnl,
            "return_pct": return_pct,
        }
        append_csv_row(CYCLES_CSV, row)

    def print_portfolio(self, portfolio: PortfolioState, current_midpoint: Optional[float] = None) -> None:
        if portfolio.open_position:
            invested_value = portfolio.open_position.entry_cost
            if current_midpoint is None:
                current_midpoint = portfolio.open_position.entry_price
            market_value = portfolio.open_position.quantity * current_midpoint
            unrealized_pnl = market_value - invested_value
        else:
            invested_value = 0.0
            market_value = 0.0
            unrealized_pnl = 0.0

        equity_total = portfolio.cash_balance + market_value
        total_pnl = portfolio.realized_pnl + unrealized_pnl
        return_pct = ((equity_total - portfolio.starting_cash) / portfolio.starting_cash) * 100.0

        print_section("Portfolio")
        print(f"starting_cash: {portfolio.starting_cash}")
        print(f"cash_balance: {portfolio.cash_balance}")
        print(f"invested_value: {invested_value}")
        print(f"market_value: {market_value}")
        print(f"realized_pnl: {portfolio.realized_pnl}")
        print(f"unrealized_pnl: {unrealized_pnl}")
        print(f"equity_total: {equity_total}")
        print(f"total_pnl: {total_pnl}")
        print(f"return_pct: {return_pct}")

    def run(self) -> None:
        ensure_logs_dir()

        portfolio = self.load_portfolio_state()
        candidates = self.load_candidates()

        print(f"Mode                 : {self.trading_mode}")
        print(f"Dry run              : {self.dry_run}")
        print(f"Strategy             : {self.strategy_name}")
        print(f"Position sizing mode : {self.position_sizing_mode}")
        print(f"Default order size   : {self.default_order_size}")
        print(f"Starting cash        : {portfolio.starting_cash}")
        print(f"Equity before cycle  : {portfolio.cash_balance if portfolio.open_position is None else 'dynamic'}")
        print(f"Open exposure        : {portfolio.open_position.entry_cost if portfolio.open_position else 0.0}")

        if portfolio.open_position is not None:
            position = portfolio.open_position

            print()
            print(f"Managing open position: {position.market_name} [{position.outcome}]")
            print(f"Token ID             : {position.token_id}")
            print(f"Entry price          : {position.entry_price}")
            print(f"Quantity             : {position.quantity}")

            prices = self.get_prices_history(position.token_id, interval="1d", fidelity=60)
            time.sleep(self.sleep_between_calls)

            book = self.get_book_snapshot(position.token_id)
            time.sleep(self.sleep_between_calls)

            strategy_result = self.macd_signal(prices)

            print()
            print_section("Live order book snapshot")
            print(f"best_bid : {book.get('best_bid')}")
            print(f"best_ask : {book.get('best_ask')}")
            print(f"bid_size : {book.get('bid_size')}")
            print(f"ask_size : {book.get('ask_size')}")

            print()
            print_section("Trader decision")
            print(strategy_result)

            if strategy_result["signal"] == "SELL":
                portfolio, sell_result = self.sell_position(portfolio)
                self.save_portfolio_state(portfolio)

                self.log_cycle(
                    token_id=position.token_id,
                    market_name=position.market_name,
                    outcome=position.outcome,
                    book=book,
                    signal="SELL",
                    reason=strategy_result["reason"],
                    order_status="FILLED",
                    portfolio=portfolio,
                )

                print()
                print("Position closed. Re-evaluating market for next BUY candidate...")

                chosen = self.choose_best_buy_candidate(candidates)
                if chosen is not None:
                    portfolio, buy_result = self.buy_position(portfolio, chosen)
                    self.save_portfolio_state(portfolio)

                    chosen_candidate: CandidateToken = chosen["candidate"]
                    chosen_book = chosen["book"]

                    self.log_cycle(
                        token_id=chosen_candidate.token_id,
                        market_name=chosen_candidate.parent_question or chosen_candidate.parent_event_title or chosen_candidate.token_id,
                        outcome=chosen_candidate.outcome,
                        book=chosen_book,
                        signal="BUY",
                        reason=str(chosen["strategy_result"]["reason"]),
                        order_status="FILLED",
                        portfolio=portfolio,
                    )

                    print()
                    print("New position opened after sell:")
                    print(f"Market             : {chosen_candidate.parent_question} [{chosen_candidate.outcome}]")
                    print(f"Token ID           : {chosen_candidate.token_id}")
                    print(f"Buy price          : {buy_result['buy_price']}")
                    print(f"Quantity           : {buy_result['quantity']}")
                    self.print_portfolio(portfolio, current_midpoint=chosen_book.get("midpoint"))
                    return

                print()
                print("No valid BUY candidate found after selling.")
                self.print_portfolio(portfolio)
                return

            self.log_cycle(
                token_id=position.token_id,
                market_name=position.market_name,
                outcome=position.outcome,
                book=book,
                signal=strategy_result["signal"],
                reason=strategy_result["reason"],
                order_status="OPEN",
                portfolio=portfolio,
            )
            self.save_portfolio_state(portfolio)
            self.print_portfolio(portfolio, current_midpoint=book.get("midpoint"))
            return

        chosen = self.choose_best_buy_candidate(candidates)

        if chosen is None:
            print()
            print("Nenhum candidato BUY válido encontrado neste ciclo.")
            self.print_portfolio(portfolio)
            return

        candidate: CandidateToken = chosen["candidate"]
        book = chosen["book"]

        print()
        print("Selected BUY candidate")
        print(f"Market               : {candidate.parent_question} [{candidate.outcome}]")
        print(f"Token ID             : {candidate.token_id}")
        print(f"Scanner score        : {candidate.score:.4f}")
        print(f"Strategy reason      : {chosen['strategy_result']['reason']}")
        print(f"Filter reason        : {chosen['filter_reason']}")

        portfolio, buy_result = self.buy_position(portfolio, chosen)
        self.save_portfolio_state(portfolio)

        self.log_cycle(
            token_id=candidate.token_id,
            market_name=candidate.parent_question or candidate.parent_event_title or candidate.token_id,
            outcome=candidate.outcome,
            book=book,
            signal="BUY",
            reason=str(chosen["strategy_result"]["reason"]),
            order_status="FILLED",
            portfolio=portfolio,
        )

        print()
        print_section("Live order book snapshot")
        print(f"best_bid : {book.get('best_bid')}")
        print(f"best_ask : {book.get('best_ask')}")
        print(f"bid_size : {book.get('bid_size')}")
        print(f"ask_size : {book.get('ask_size')}")

        print()
        print_section("Trader decision")
        print(chosen["strategy_result"])

        self.print_portfolio(portfolio, current_midpoint=book.get("midpoint"))


if __name__ == "__main__":
    try:
        runner = PolymarketPaperRunner()
        runner.run()
    except requests.HTTPError as e:
        print(f"Erro HTTP: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)