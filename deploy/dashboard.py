from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


METRICS_DIR = Path("data/metrics")


def load_metrics() -> list[dict[str, Any]]:
    if not METRICS_DIR.exists():
        return []

    rows: list[dict[str, Any]] = []

    for file in sorted(METRICS_DIR.glob("*.json")):
        try:
            with file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
                payload["_filename"] = file.name
                rows.append(payload)
        except Exception as exc:
            print(f"Skipping invalid file {file.name}: {exc}")

    return rows


def format_float(value: Any, decimals: int = 2) -> str:
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def print_table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No metrics found.")
        return

    headers = [
        "file",
        "strategy",
        "trades",
        "win_rate",
        "pnl",
        "drawdown",
        "sharpe",
        "profit_factor",
        "expectancy",
    ]

    table: list[list[str]] = []
    for row in rows:
        table.append(
            [
                row.get("_filename", ""),
                row.get("strategy_name", "unknown"),
                str(row.get("total_trades", 0)),
                format_float(row.get("win_rate", 0.0)),
                format_float(row.get("total_pnl", 0.0)),
                format_float(row.get("max_drawdown", 0.0)),
                format_float(row.get("sharpe_ratio", 0.0)),
                format_float(row.get("profit_factor", 0.0)),
                format_float(row.get("expectancy", 0.0)),
            ]
        )

    col_widths = []
    for i, header in enumerate(headers):
        width = len(header)
        for row in table:
            width = max(width, len(row[i]))
        col_widths.append(width)

    header_line = " | ".join(header.ljust(col_widths[i]) for i, header in enumerate(headers))
    separator = "-+-".join("-" * col_widths[i] for i in range(len(headers)))

    print(header_line)
    print(separator)

    for row in table:
        print(" | ".join(row[i].ljust(col_widths[i]) for i in range(len(headers))))


def print_summary(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    best = max(rows, key=lambda r: float(r.get("total_pnl", 0.0)))
    worst = min(rows, key=lambda r: float(r.get("total_pnl", 0.0)))

    print("\nSummary")
    print("-------")
    print(
        f"Best run : {best.get('_filename')} | "
        f"{best.get('strategy_name', 'unknown')} | "
        f"PnL={format_float(best.get('total_pnl', 0.0))}"
    )
    print(
        f"Worst run: {worst.get('_filename')} | "
        f"{worst.get('strategy_name', 'unknown')} | "
        f"PnL={format_float(worst.get('total_pnl', 0.0))}"
    )

    by_strategy: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        strategy = row.get("strategy_name", "unknown")
        by_strategy.setdefault(strategy, []).append(row)

    print("\nBy strategy")
    print("-----------")
    for strategy, items in by_strategy.items():
        avg_pnl = sum(float(x.get("total_pnl", 0.0)) for x in items) / len(items)
        avg_win_rate = sum(float(x.get("win_rate", 0.0)) for x in items) / len(items)
        print(
            f"{strategy}: runs={len(items)} | "
            f"avg_pnl={format_float(avg_pnl)} | "
            f"avg_win_rate={format_float(avg_win_rate)}"
        )


def main() -> None:
    rows = load_metrics()

    if len(sys.argv) > 1:
        strategy_filter = sys.argv[1].strip().lower()
        rows = [
            row
            for row in rows
            if str(row.get("strategy_name", "")).strip().lower() == strategy_filter
        ]

    print("\n==== DASHBOARD ====\n")
    print_table(rows)
    print_summary(rows)


if __name__ == "__main__":
    main()