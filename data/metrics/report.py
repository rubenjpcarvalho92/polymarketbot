from __future__ import annotations

from typing import Any


def format_report(metrics: dict[str, Any]) -> str:
    return f"""
==== BACKTEST REPORT ====

Strategy: {metrics.get("strategy_name")}
Total Trades: {metrics.get("total_trades")}
Win Rate: {metrics.get("win_rate", 0.0):.2f}
Total PnL: {metrics.get("total_pnl", 0.0):.2f}

Avg Win: {metrics.get("avg_win", 0.0):.2f}
Avg Loss: {metrics.get("avg_loss", 0.0):.2f}

Sharpe: {metrics.get("sharpe_ratio", 0.0):.2f}
Max Drawdown: {metrics.get("max_drawdown", 0.0):.2f}

Profit Factor: {metrics.get("profit_factor", 0.0):.2f}
Expectancy: {metrics.get("expectancy", 0.0):.2f}

=========================
"""