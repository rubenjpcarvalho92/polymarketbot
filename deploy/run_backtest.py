from __future__ import annotations

import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtesting.engine import BacktestEngine
from data.candles import Candle
from data.metrics.report import format_report
from data.metrics.storage import MetricsStorage
from strategies.macd_classic import MacdClassicStrategy
from strategies.macd_refined import MacdRefinedStrategy
from strategies.rsi_vwap import RsiVwapStrategy


def generate_fake_candles(n: int = 240) -> list[Candle]:
    candles: list[Candle] = []
    price = 0.40

    for i in range(n):
        # Série artificial com blocos de tendência e pullbacks
        block = i % 24

        if block < 8:
            price += 0.008
        elif block < 12:
            price -= 0.004
        elif block < 18:
            price += 0.005
        else:
            price -= 0.006

        price = max(0.08, min(0.92, price))

        high = min(price + 0.012, 0.99)
        low = max(price - 0.012, 0.01)
        open_price = max(0.01, min(0.99, price - 0.002))
        close_price = price

        candles.append(
            Candle(
                timestamp=f"2026-01-{1 + (i // 60):02d}T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00",
                open=open_price,
                high=high,
                low=low,
                close=close_price,
                volume=10.0 + (i % 7),
            )
        )

    return candles


def run_single_strategy(strategy, candles: list[Candle], storage: MetricsStorage) -> dict:
    engine = BacktestEngine(strategy=strategy)
    metrics_obj = engine.run("m1", candles)

    metrics = asdict(metrics_obj)
    metrics["strategy_name"] = strategy.name

    saved_path = storage.save(strategy.name, metrics)

    print(format_report(metrics))
    print(f"Saved to: {saved_path}\n")

    return metrics


def print_comparison(results: list[dict]) -> None:
    if not results:
        return

    print("\n==== STRATEGY COMPARISON ====\n")

    headers = [
        "strategy",
        "trades",
        "win_rate",
        "pnl",
        "drawdown",
        "sharpe",
        "profit_factor",
        "expectancy",
    ]

    rows: list[list[str]] = []
    for result in results:
        rows.append(
            [
                str(result.get("strategy_name", "unknown")),
                str(result.get("total_trades", 0)),
                f"{float(result.get('win_rate', 0.0)):.2f}",
                f"{float(result.get('total_pnl', 0.0)):.2f}",
                f"{float(result.get('max_drawdown', 0.0)):.2f}",
                f"{float(result.get('sharpe_ratio', 0.0)):.2f}",
                f"{float(result.get('profit_factor', 0.0)):.2f}",
                f"{float(result.get('expectancy', 0.0)):.2f}",
            ]
        )

    col_widths: list[int] = []
    for i, header in enumerate(headers):
        width = len(header)
        for row in rows:
            width = max(width, len(row[i]))
        col_widths.append(width)

    header_line = " | ".join(header.ljust(col_widths[i]) for i, header in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))

    print(header_line)
    print(separator)
    for row in rows:
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))

    best_pnl = max(results, key=lambda x: float(x.get("total_pnl", 0.0)))
    best_sharpe = max(results, key=lambda x: float(x.get("sharpe_ratio", 0.0)))
    best_expectancy = max(results, key=lambda x: float(x.get("expectancy", 0.0)))

    print("\nBest by PnL       :", best_pnl.get("strategy_name"), f"({float(best_pnl.get('total_pnl', 0.0)):.2f})")
    print("Best by Sharpe    :", best_sharpe.get("strategy_name"), f"({float(best_sharpe.get('sharpe_ratio', 0.0)):.2f})")
    print("Best by Expectancy:", best_expectancy.get("strategy_name"), f"({float(best_expectancy.get('expectancy', 0.0)):.2f})")
    print()


def main() -> None:
    candles = generate_fake_candles(240)
    storage = MetricsStorage()

    strategies = [
        MacdClassicStrategy(),
        MacdRefinedStrategy(),
        RsiVwapStrategy(),
    ]

    results: list[dict] = []

    for strategy in strategies:
        print(f"\nRunning strategy: {strategy.name}")
        print("-" * 40)
        metrics = run_single_strategy(strategy, candles, storage)
        results.append(metrics)

    print_comparison(results)


if __name__ == "__main__":
    main()