from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import AppConfig, load_config
from bot.csv_logger import append_csv_row
from bot.execution import ExecutionEngine
from bot.paper_portfolio import PaperPortfolio
from bot.polymarket_client import PolymarketClient
from bot.price_history import (
    append_raw_market_snapshot,
    bootstrap_history_file_from_api,
    build_market_data_from_candles,
)
from bot.trader import Trader
from strategies.base_strategy import StrategyContext
from strategies.macd_classic import MacdClassicStrategy
from strategies.macd_refined import MacdRefinedStrategy
from strategies.position_sizing import (
    PositionSizingConfig,
    PositionSizingMode,
    PositionSizingState,
    PositionSizer,
)
from strategies.rsi_vwap import RsiVwapStrategy


LOGS_DIR = PROJECT_ROOT / "logs"
TOKEN_ANALYSIS_JSON = PROJECT_ROOT / "token_analysis_results.json"


@dataclass
class CandidateToken:
    token_id: str
    market_name: str
    outcome: str
    score: float
    midpoint: float
    spread: float
    return_pct: float
    trend_consistency: float
    history_points: int


def get_strategies() -> dict:
    return {
        "macd_classic": MacdClassicStrategy(),
        "macd_refined": MacdRefinedStrategy(),
        "rsi_vwap": RsiVwapStrategy(),
    }


def get_public_clob_host(config: AppConfig) -> str:
    raw_host = getattr(config.polymarket, "host", None) or "https://clob.polymarket.com"
    return str(raw_host).rstrip("/")


def build_fake_history_from_orderbook(best_bid: float, best_ask: float) -> dict:
    midpoint = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.5

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    base = midpoint - 0.03

    for i in range(220):
        value = base + (i * 0.00025)

        if i % 13 in (0, 1, 2):
            value -= 0.002
        elif i % 13 in (7, 8):
            value += 0.0015

        value = max(0.05, min(0.95, value))

        high = min(value + 0.01, 0.99)
        low = max(value - 0.01, 0.01)

        closes.append(value)
        highs.append(high)
        lows.append(low)
        volumes.append(10.0 + (i % 5))

    closes[-1] = midpoint
    highs[-1] = min(midpoint + 0.01, 0.99)
    lows[-1] = max(midpoint - 0.01, 0.01)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def fetch_spread(config: AppConfig, token_id: str) -> float:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/spread",
            params={"token_id": token_id},
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: spread HTTP {response.status_code} for token {token_id}")
            return 0.0

        payload = response.json()
        return float(payload.get("spread", 0.0) or 0.0)

    except Exception as exc:
        print(f"WARNING: spread fetch failed for token {token_id}: {exc}")
        return 0.0


def fetch_last_trade_price(config: AppConfig, token_id: str) -> dict:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/last-trade-price",
            params={"token_id": token_id},
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: last-trade-price HTTP {response.status_code} for token {token_id}")
            return {"price": 0.0, "side": ""}

        payload = response.json()
        return {
            "price": float(payload.get("price", 0.0) or 0.0),
            "side": str(payload.get("side", "") or ""),
        }

    except Exception as exc:
        print(f"WARNING: last-trade-price fetch failed for token {token_id}: {exc}")
        return {"price": 0.0, "side": ""}


def fetch_prices_history_from_api(
    config: AppConfig,
    token_id: str,
    interval: str = "1d",
    fidelity: int = 60,
) -> list[float]:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/prices-history",
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: prices-history HTTP {response.status_code} for token {token_id}")
            return []

        payload = response.json()
        history = payload.get("history", [])
        if not isinstance(history, list):
            return []

        prices: list[float] = []
        for row in history:
            if not isinstance(row, dict):
                continue
            p = safe_float(row.get("p"), default=-1.0)
            if p > 0:
                prices.append(p)

        return prices

    except Exception as exc:
        print(f"WARNING: prices-history fetch failed for token {token_id}: {exc}")
        return []


def build_market_data_from_api_prices(prices: list[float]) -> Optional[dict]:
    if len(prices) < 35:
        return None

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i, price in enumerate(prices):
        prev_price = prices[i - 1] if i > 0 else price
        next_price = prices[i + 1] if i < len(prices) - 1 else price

        hi = max(price, prev_price, next_price)
        lo = min(price, prev_price, next_price)

        pad = max(0.0005, price * 0.0025)
        high = min(0.999, hi + pad)
        low = max(0.001, lo - pad)

        closes.append(price)
        highs.append(high)
        lows.append(low)
        volumes.append(10.0 + (i % 7))

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def build_position_sizer_config(config: AppConfig) -> PositionSizingConfig:
    mode_raw = (config.position_sizing.mode or "fixed_percent").strip().lower()

    try:
        mode = PositionSizingMode(mode_raw)
    except ValueError:
        mode = PositionSizingMode.FIXED_PERCENT

    return PositionSizingConfig(
        mode=mode,
        starting_balance=config.position_sizing.starting_balance,
        min_order_size=config.position_sizing.min_order_size,
        max_order_size=config.position_sizing.max_order_size,
        max_exposure_pct=config.position_sizing.max_exposure_pct,
        fixed_percent=config.position_sizing.fixed_percent,
        fixed_amount=config.position_sizing.fixed_amount,
        kelly_win_rate=config.position_sizing.kelly_win_rate,
        kelly_reward_ratio=config.position_sizing.kelly_reward_ratio,
        martingale_base_amount=config.position_sizing.martingale_base_amount,
        martingale_multiplier=config.position_sizing.martingale_multiplier,
        martingale_max_steps=config.position_sizing.martingale_max_steps,
        anti_martingale_base_amount=config.position_sizing.anti_martingale_base_amount,
        anti_martingale_multiplier=config.position_sizing.anti_martingale_multiplier,
        anti_martingale_max_steps=config.position_sizing.anti_martingale_max_steps,
        signal_conf_low_pct=config.position_sizing.signal_conf_low_pct,
        signal_conf_medium_pct=config.position_sizing.signal_conf_medium_pct,
        signal_conf_high_pct=config.position_sizing.signal_conf_high_pct,
    )


def build_position_sizing_state(portfolio_snapshot: dict) -> PositionSizingState:
    equity_total = float(portfolio_snapshot.get("equity_total", 0.0) or 0.0)
    market_value = float(portfolio_snapshot.get("market_value", 0.0) or 0.0)

    return PositionSizingState(
        current_balance=equity_total,
        open_exposure=market_value,
        consecutive_losses=0,
        consecutive_wins=0,
    )


def get_signal_strength(result) -> str:
    if not result:
        return "medium"

    metadata = getattr(result, "metadata", {}) or {}
    raw_strength = str(metadata.get("signal_strength", "")).strip().lower()

    if raw_strength in {"low", "medium", "high"}:
        return raw_strength

    return "medium"


def load_candidates_from_json(max_candidates: int = 10) -> list[CandidateToken]:
    if not TOKEN_ANALYSIS_JSON.exists():
        print(f"WARNING: {TOKEN_ANALYSIS_JSON.name} não existe.")
        return []

    try:
        data = json.loads(TOKEN_ANALYSIS_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: erro ao ler {TOKEN_ANALYSIS_JSON.name}: {exc}")
        return []

    if not isinstance(data, list):
        print(f"WARNING: {TOKEN_ANALYSIS_JSON.name} não é uma lista.")
        return []

    print(f"Raw candidates in JSON : {len(data)}")

    candidates: list[CandidateToken] = []
    failed = 0

    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            failed += 1
            continue

        try:
            token_id = str(item.get("token_id", "")).strip()
            if not token_id:
                failed += 1
                continue

            market_name = (
                item.get("parent_question")
                or item.get("parent_event_title")
                or item.get("question")
                or item.get("event_title")
                or "Unknown Market"
            )

            outcome = str(item.get("outcome", "") or "").strip().upper()

            candidates.append(
                CandidateToken(
                    token_id=token_id,
                    market_name=str(market_name),
                    outcome=outcome,
                    score=safe_float(item.get("score"), 0.0),
                    midpoint=safe_float(item.get("midpoint"), 0.0),
                    spread=safe_float(item.get("spread"), 0.0),
                    return_pct=safe_float(item.get("return_pct"), 0.0),
                    trend_consistency=safe_float(item.get("trend_consistency"), 0.0),
                    history_points=int(item.get("history_points", 0) or 0),
                )
            )
        except Exception as exc:
            failed += 1
            print(f"WARNING: candidate {idx} inválido: {exc}")

    candidates.sort(key=lambda x: x.score, reverse=True)

    print(f"Parsed candidates      : {len(candidates)}")
    print(f"Failed candidates      : {failed}")

    if max_candidates > 0:
        candidates = candidates[:max_candidates]

    return candidates


def basic_buy_candidate_filter(candidate: CandidateToken) -> tuple[bool, str]:
    if candidate.midpoint <= 0:
        return False, "missing_midpoint"

    if candidate.midpoint < 0.10 or candidate.midpoint > 0.90:
        return False, "midpoint_outside_buy_range"

    if candidate.spread <= 0:
        return False, "missing_spread"

    if candidate.spread > 0.02:
        return False, "spread_too_wide"

    if candidate.history_points < 12:
        return False, "not_enough_history"

    if candidate.return_pct < -10:
        return False, "return_too_negative"

    if candidate.trend_consistency > 0 and candidate.trend_consistency < 0.40:
        return False, "trend_consistency_too_low"

    return True, "candidate_ok"


def resolve_open_position_token_id(portfolio) -> Optional[str]:
    positions = getattr(portfolio, "positions", {}) or {}
    if not positions:
        return None

    for token_id, position in positions.items():
        size = float(getattr(position, "size", 0.0) or 0.0)
        if size > 0:
            return str(token_id)

    return None


def resolve_open_position_side(portfolio, token_id: str) -> str:
    positions = getattr(portfolio, "positions", {}) or {}
    position = positions.get(token_id)
    if position is None:
        return ""

    side = getattr(position, "side", "")
    return str(side or "")


def build_trader(config: AppConfig, client: PolymarketClient) -> Trader:
    execution_engine = ExecutionEngine(
        app_config=config,
        polymarket_client=client,
    )
    return Trader(
        strategies=get_strategies(),
        execution_engine=execution_engine,
    )


def evaluate_token(
    *,
    config: AppConfig,
    client: PolymarketClient,
    token_id: str,
    market_name: str,
    outcome: str,
    position_sizer: PositionSizer,
    position_state: PositionSizingState,
) -> dict:
    clob_host = get_public_clob_host(config)

    spread = fetch_spread(config, token_id)
    last_trade = fetch_last_trade_price(config, token_id)
    book = client.get_order_book(token_id)

    history_path = bootstrap_history_file_from_api(
        logs_dir=LOGS_DIR,
        clob_host=clob_host,
        token_id=token_id,
        lookback_hours=24,
    )

    timestamp_utc = datetime.now(timezone.utc).isoformat()

    append_raw_market_snapshot(
        history_path=history_path,
        timestamp_utc=timestamp_utc,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        bid_size=book.bid_size,
        ask_size=book.ask_size,
        spread=spread,
        last_trade_price=last_trade["price"],
        last_trade_side=last_trade["side"],
        keep_last_hours=24,
    )

    api_prices = fetch_prices_history_from_api(
        config=config,
        token_id=token_id,
        interval="1d",
        fidelity=60,
    )

    market_data = build_market_data_from_api_prices(api_prices)
    history_source = "api_prices_history"

    if market_data is None:
        market_data = build_market_data_from_candles(
            history_path=history_path,
            keep_last_hours=24,
            candle_minutes=1,
            min_candles=35,
        )
        history_source = "local_raw+api_bootstrap"

    if market_data is None:
        history_source = "synthetic_fallback"
        market_data = build_fake_history_from_orderbook(book.best_bid, book.best_ask)

    pre_trade_signal_strength = "medium"
    calculated_order_size = position_sizer.calculate_order_size(
        state=position_state,
        signal_strength=pre_trade_signal_strength,
    )

    context = StrategyContext(
        market_id=token_id,
        timestamp="live-paper-snapshot",
        data=market_data,
    )

    result = None
    if calculated_order_size > 0:
        local_trader = build_trader(config, client)
        result = local_trader.process_market(
            strategy_name=config.trading.strategy_name,
            context=context,
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            order_size=calculated_order_size,
            token_id=token_id,
        )
    else:
        local_trader = None

    midpoint = (book.best_bid + book.best_ask) / 2 if book.best_bid > 0 and book.best_ask > 0 else 0.0

    return {
        "token_id": token_id,
        "market_name": market_name,
        "outcome": outcome,
        "spread": spread,
        "last_trade": last_trade,
        "book": book,
        "history_path": history_path,
        "history_source": history_source,
        "api_history_points": len(api_prices),
        "calculated_order_size": calculated_order_size,
        "result": result,
        "midpoint": midpoint,
        "trader": local_trader,
    }


def main() -> None:
    config = load_config()

    starting_cash = config.trading.paper_starting_cash

    portfolio = PaperPortfolio.load(
        "logs/portfolio_state.json",
        starting_cash=starting_cash,
    )

    risk_config = build_position_sizer_config(config)
    position_sizer = PositionSizer(risk_config)

    portfolio_snapshot_before = portfolio.snapshot()
    position_state = build_position_sizing_state(portfolio_snapshot_before)

    print(f"Mode                 : {config.trading.trading_mode}")
    print(f"Dry run              : {config.trading.dry_run}")
    print(f"Strategy             : {config.trading.strategy_name}")
    print(f"Position sizing mode : {risk_config.mode.value}")
    print(f"Default order size   : {config.trading.default_order_size}")
    print(f"Starting cash        : {starting_cash}")
    print(f"Equity before cycle  : {position_state.current_balance}")
    print(f"Open exposure        : {position_state.open_exposure}")
    print()

    client = PolymarketClient(config.polymarket)

    current_open_token_id = resolve_open_position_token_id(portfolio)
    current_open_side = resolve_open_position_side(portfolio, current_open_token_id) if current_open_token_id else ""

    selected_token_id: Optional[str] = None
    selected_market_name: str = ""
    selected_outcome: str = ""
    selected_evaluation: Optional[dict] = None

    if current_open_token_id:
        selected_token_id = current_open_token_id
        selected_market_name = current_open_token_id
        selected_outcome = current_open_side or ""
        print("Open position detected. Managing current position.")
        print(f"Token ID             : {selected_token_id}")
        print()
    else:
        candidates = load_candidates_from_json(max_candidates=10)

        if not candidates:
            if not config.trading.default_token_id:
                print("Nenhum candidato válido no JSON e DEFAULT_TOKEN_ID está vazio.")
                print()
                print("Portfolio")
                print("---------")
                for key, value in portfolio_snapshot_before.items():
                    print(f"{key}: {value}")
                return

            print("Sem candidatos no JSON. A usar DEFAULT_TOKEN_ID como fallback.")
            print()
            selected_token_id = config.trading.default_token_id
            selected_market_name = selected_token_id
            selected_outcome = ""
        else:
            print("Candidate evaluation")
            print("--------------------")

            for idx, candidate in enumerate(candidates, start=1):
                passes_candidate_filter, candidate_reason = basic_buy_candidate_filter(candidate)

                print(f"[{idx}] {candidate.market_name} [{candidate.outcome}]")
                print(f"    Token ID         : {candidate.token_id}")
                print(f"    Score            : {candidate.score}")
                print(f"    Midpoint         : {candidate.midpoint}")
                print(f"    Spread           : {candidate.spread}")
                print(f"    Return %         : {candidate.return_pct}")
                print(f"    Trend consistency: {candidate.trend_consistency}")
                print(f"    History points   : {candidate.history_points}")
                print(f"    Candidate filter : {passes_candidate_filter} ({candidate_reason})")

                if not passes_candidate_filter:
                    print()
                    continue

                evaluation = evaluate_token(
                    config=config,
                    client=client,
                    token_id=candidate.token_id,
                    market_name=candidate.market_name,
                    outcome=candidate.outcome,
                    position_sizer=position_sizer,
                    position_state=position_state,
                )

                result = evaluation["result"]
                book = evaluation["book"]
                spread = evaluation["spread"]
                last_trade = evaluation["last_trade"]

                print(f"    Live best_bid    : {book.best_bid}")
                print(f"    Live best_ask    : {book.best_ask}")
                print(f"    Live bid_size    : {book.bid_size}")
                print(f"    Live ask_size    : {book.ask_size}")
                print(f"    Live spread      : {spread}")
                print(f"    Last trade px    : {last_trade['price']}")
                print(f"    Last trade side  : {last_trade['side']}")
                print(f"    History source   : {evaluation['history_source']}")
                print(f"    API hist points  : {evaluation['api_history_points']}")
                print(f"    History file     : {evaluation['history_path'].name}")
                print(f"    Calc order size  : {evaluation['calculated_order_size']}")

                if result is None:
                    print("    Strategy result  : None")
                    print()
                    continue

                print(f"    Strategy result  : {result}")
                print()

                if result.signal.value == "BUY":
                    selected_evaluation = evaluation
                    break

            if selected_evaluation is None:
                print("Nenhum candidato BUY válido encontrado neste ciclo.")
                print()
                print("Portfolio")
                print("---------")
                for key, value in portfolio_snapshot_before.items():
                    print(f"{key}: {value}")
                return

            selected_token_id = selected_evaluation["token_id"]
            selected_market_name = selected_evaluation["market_name"]
            selected_outcome = selected_evaluation["outcome"]

            print("Selected candidate")
            print("------------------")
            print(f"Market              : {selected_market_name} [{selected_outcome}]")
            print(f"Token ID            : {selected_token_id}")
            print()

    if not selected_token_id:
        print("No token selected.")
        return

    if selected_evaluation is None:
        final_evaluation = evaluate_token(
            config=config,
            client=client,
            token_id=selected_token_id,
            market_name=selected_market_name,
            outcome=selected_outcome,
            position_sizer=position_sizer,
            position_state=position_state,
        )
    else:
        final_evaluation = selected_evaluation

    spread = final_evaluation["spread"]
    last_trade = final_evaluation["last_trade"]
    book = final_evaluation["book"]
    result = final_evaluation["result"]
    midpoint = final_evaluation["midpoint"]
    trader_for_final = final_evaluation["trader"]

    print(f"spread   : {spread}")
    print(f"last_px  : {last_trade['price']}")
    print(f"last_side: {last_trade['side']}")
    print()

    if final_evaluation["history_source"] == "synthetic_fallback":
        print("WARNING: insufficient real history. Falling back to synthetic history for this cycle.")
    else:
        print(
            f"History source      : {final_evaluation['history_source']}\n"
            f"API hist points     : {final_evaluation['api_history_points']}\n"
            f"History file        : {final_evaluation['history_path'].name}\n"
            f"History window      : 24h"
        )
    print()

    print("Live order book snapshot")
    print("------------------------")
    print(f"best_bid : {book.best_bid}")
    print(f"best_ask : {book.best_ask}")
    print(f"bid_size : {book.bid_size}")
    print(f"ask_size : {book.ask_size}")
    print()

    calculated_order_size = final_evaluation["calculated_order_size"]

    if calculated_order_size <= 0:
        print("Calculated order size is 0. No available exposure for a new trade.")
        print()
        print("Portfolio")
        print("---------")
        for key, value in portfolio_snapshot_before.items():
            print(f"{key}: {value}")
        return

    print(f"Calculated order size: {calculated_order_size}")
    print()

    print("Trader decision")
    print("---------------")
    print(result)
    print()

    print("Open orders")
    print("-----------")
    if trader_for_final is not None:
        for order in trader_for_final.order_manager.orders.values():
            print(order)

    print()
    print("Positions")
    print("---------")
    if trader_for_final is not None:
        for market_id, position in trader_for_final.state.positions.items():
            print(market_id, position)

    signal_strength = get_signal_strength(result)

    metadata = result.metadata if result else {}
    order_status = metadata.get("order_status", "")
    position_side = metadata.get("position_side", metadata.get("side", ""))
    limit_price = float(metadata.get("limit_price", 0.0) or 0.0)
    order_size = float(metadata.get("closed_size", calculated_order_size) or 0.0)

    if order_status == "FILLED" and position_side and limit_price > 0 and order_size > 0:
        portfolio.apply_fill(
            token_id=selected_token_id,
            side=position_side,
            size=order_size,
            price=limit_price,
        )

    if position_side and midpoint > 0:
        portfolio.mark_position(
            token_id=selected_token_id,
            side=position_side,
            mark_price=midpoint,
        )

    portfolio.save("logs/portfolio_state.json")
    portfolio_snapshot = portfolio.snapshot()

    timestamp_utc = datetime.now(timezone.utc).isoformat()

    cycle_fields = [
        "market_name",
        "outcome",
        "spread",
        "last_trade_price",
        "last_trade_side",
        "timestamp",
        "token_id",
        "strategy",
        "position_sizing_mode",
        "signal_strength",
        "best_bid",
        "best_ask",
        "bid_size",
        "ask_size",
        "midpoint",
        "signal",
        "reason",
        "position_side",
        "limit_price",
        "order_size",
        "order_status",
        "starting_cash",
        "cash_balance",
        "invested_value",
        "market_value",
        "realized_pnl",
        "unrealized_pnl",
        "equity_total",
        "total_pnl",
        "return_pct",
    ]

    append_csv_row(
        "logs/cycles.csv",
        cycle_fields,
        {
            "market_name": selected_market_name,
            "outcome": selected_outcome,
            "spread": spread,
            "last_trade_price": last_trade["price"],
            "last_trade_side": last_trade["side"],
            "timestamp": timestamp_utc,
            "token_id": selected_token_id,
            "strategy": config.trading.strategy_name,
            "position_sizing_mode": risk_config.mode.value,
            "signal_strength": signal_strength,
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "bid_size": book.bid_size,
            "ask_size": book.ask_size,
            "midpoint": midpoint,
            "signal": result.signal.value if result else "HOLD",
            "reason": result.reason if result else "no_trade_available_exposure_blocked",
            "position_side": position_side,
            "limit_price": limit_price,
            "order_size": order_size,
            "order_status": order_status,
            **portfolio_snapshot,
        },
    )

    trade_fields = [
        "timestamp",
        "market_name",
        "outcome",
        "token_id",
        "side",
        "price",
        "size",
        "position_sizing_mode",
        "signal_strength",
        "order_status",
        "cash_balance",
        "invested_value",
        "market_value",
        "unrealized_pnl",
        "equity_total",
        "return_pct",
    ]

    if order_status == "FILLED":
        append_csv_row(
            "logs/trades.csv",
            trade_fields,
            {
                "timestamp": timestamp_utc,
                "market_name": selected_market_name,
                "outcome": selected_outcome,
                "token_id": selected_token_id,
                "side": position_side,
                "price": limit_price,
                "size": order_size,
                "position_sizing_mode": risk_config.mode.value,
                "signal_strength": signal_strength,
                "order_status": order_status,
                "cash_balance": portfolio_snapshot["cash_balance"],
                "invested_value": portfolio_snapshot["invested_value"],
                "market_value": portfolio_snapshot["market_value"],
                "unrealized_pnl": portfolio_snapshot["unrealized_pnl"],
                "equity_total": portfolio_snapshot["equity_total"],
                "return_pct": portfolio_snapshot["return_pct"],
            },
        )

    portfolio_fields = [
        "timestamp",
        "starting_cash",
        "cash_balance",
        "invested_value",
        "market_value",
        "realized_pnl",
        "unrealized_pnl",
        "equity_total",
        "total_pnl",
        "return_pct",
    ]

    append_csv_row(
        "logs/portfolio.csv",
        portfolio_fields,
        {
            "timestamp": timestamp_utc,
            **portfolio_snapshot,
        },
    )

    print()
    print("Portfolio")
    print("---------")
    for key, value in portfolio_snapshot.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()