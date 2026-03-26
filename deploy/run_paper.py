from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import load_config
from bot.execution import ExecutionEngine
from bot.polymarket_client import PolymarketClient
from bot.trader import Trader
from strategies.base_strategy import StrategyContext
from strategies.macd_classic import MacdClassicStrategy
from strategies.macd_refined import MacdRefinedStrategy
from strategies.rsi_vwap import RsiVwapStrategy


def build_fake_history_from_orderbook(best_bid: float, best_ask: float) -> dict:
    """
    Temporary bridge:
    until we have real candle history, create synthetic rolling series
    around the current midpoint so the strategies can run.
    """

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

    # force last point to reflect real market
    closes[-1] = midpoint
    highs[-1] = min(midpoint + 0.01, 0.99)
    lows[-1] = max(midpoint - 0.01, 0.01)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def get_strategies():
    return {
        "macd_classic": MacdClassicStrategy(),
        "macd_refined": MacdRefinedStrategy(),
        "rsi_vwap": RsiVwapStrategy(),
    }


def main() -> None:
    config = load_config()

    if not config.trading.default_token_id:
        print("DEFAULT_TOKEN_ID is empty in .env")
        print("Set a real token id first.")
        return

    print(f"Mode        : {config.trading.trading_mode}")
    print(f"Dry run     : {config.trading.dry_run}")
    print(f"Strategy    : {config.trading.strategy_name}")
    print(f"Token ID    : {config.trading.default_token_id}")
    print(f"Order size  : {config.trading.default_order_size}")
    print()

    client = PolymarketClient(config.polymarket)
    book = client.get_order_book(config.trading.default_token_id)

    print("Live order book snapshot")
    print("------------------------")
    print(f"best_bid : {book.best_bid}")
    print(f"best_ask : {book.best_ask}")
    print(f"bid_size : {book.bid_size}")
    print(f"ask_size : {book.ask_size}")
    print()

    strategies = get_strategies()
    if config.trading.strategy_name not in strategies:
        print(f"Unknown strategy in .env: {config.trading.strategy_name}")
        return

    execution_engine = ExecutionEngine(
        app_config=config,
        polymarket_client=client,
    )

    trader = Trader(
        strategies=strategies,
        execution_engine=execution_engine,
    )

    market_data = build_fake_history_from_orderbook(book.best_bid, book.best_ask)

    context = StrategyContext(
        market_id=config.trading.default_token_id,
        timestamp="live-paper-snapshot",
        data=market_data,
    )

    result = trader.process_market(
        strategy_name=config.trading.strategy_name,
        context=context,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        order_size=config.trading.default_order_size,
        token_id=config.trading.default_token_id,
    )

    print("Trader decision")
    print("---------------")
    print(result)
    print()

    print("Open orders")
    print("-----------")
    for order in trader.order_manager.orders.values():
        print(order)

    print()
    print("Positions")
    print("---------")
    for market_id, position in trader.state.positions.items():
        print(market_id, position)


if __name__ == "__main__":
    main()