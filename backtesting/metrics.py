from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt


@dataclass(slots=True)
class BacktestTrade:
    market_id: str
    strategy_name: str
    side: str
    entry_timestamp: str
    exit_timestamp: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float


@dataclass(slots=True)
class BacktestMetrics:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    equity_curve: list[float] = field(default_factory=list)


class BacktestMetricsCalculator:
    def __init__(self) -> None:
        self.trades: list[BacktestTrade] = []

    def add_trade(self, trade: BacktestTrade) -> None:
        self.trades.append(trade)

    def build(self) -> BacktestMetrics:
        metrics = BacktestMetrics()

        metrics.total_trades = len(self.trades)
        wins = [t for t in self.trades if t.pnl > 0]
        losses = [t for t in self.trades if t.pnl < 0]

        metrics.wins = len(wins)
        metrics.losses = len(losses)

        if metrics.total_trades > 0:
            metrics.win_rate = metrics.wins / metrics.total_trades

        metrics.total_pnl = sum(t.pnl for t in self.trades)

        if wins:
            metrics.avg_win = sum(t.pnl for t in wins) / len(wins)

        if losses:
            metrics.avg_loss = sum(t.pnl for t in losses) / len(losses)

        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))

        if gross_loss > 0:
            metrics.profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            metrics.profit_factor = float("inf")

        metrics.expectancy = (
            (metrics.win_rate * metrics.avg_win)
            - ((1.0 - metrics.win_rate) * abs(metrics.avg_loss))
        )

        metrics.equity_curve = self._build_equity_curve()
        metrics.max_drawdown = self._calculate_max_drawdown(metrics.equity_curve)
        metrics.sharpe_ratio = self._calculate_sharpe_ratio([t.pnl for t in self.trades])

        return metrics

    def _build_equity_curve(self) -> list[float]:
        equity = [0.0]
        for trade in self.trades:
            equity.append(equity[-1] + trade.pnl)
        return equity

    @staticmethod
    def _calculate_max_drawdown(equity_curve: list[float]) -> float:
        if len(equity_curve) < 2:
            return 0.0

        peak = equity_curve[0]
        max_drawdown = 0.0

        for value in equity_curve:
            if value > peak:
                peak = value

            if peak > 0:
                drawdown = (peak - value) / peak
            else:
                drawdown = 0.0 if value >= peak else abs(value - peak)

            max_drawdown = max(max_drawdown, drawdown)

        return max_drawdown

    @staticmethod
    def _calculate_sharpe_ratio(pnls: list[float]) -> float:
        if len(pnls) < 2:
            return 0.0

        mean_return = sum(pnls) / len(pnls)
        variance = sum((x - mean_return) ** 2 for x in pnls) / (len(pnls) - 1)
        std_dev = sqrt(variance) if variance > 0 else 0.0

        if std_dev == 0:
            return 0.0

        return mean_return / std_dev