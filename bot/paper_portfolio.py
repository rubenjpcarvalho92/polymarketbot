from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class PortfolioPosition:
    token_id: str
    side: str
    size: float
    average_price: float
    last_mark_price: float = 0.0

    @property
    def invested_value(self) -> float:
        return self.size * self.average_price

    @property
    def market_value(self) -> float:
        return self.size * self.last_mark_price

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.invested_value


@dataclass(slots=True)
class PaperPortfolio:
    starting_cash: float
    cash_balance: float
    realized_pnl: float = 0.0
    positions: dict[str, PortfolioPosition] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str, starting_cash: float) -> "PaperPortfolio":
        file_path = Path(path)

        if not file_path.exists():
            return cls(
                starting_cash=starting_cash,
                cash_balance=starting_cash,
                realized_pnl=0.0,
                positions={},
            )

        data = json.loads(file_path.read_text(encoding="utf-8"))

        positions = {
            key: PortfolioPosition(**value)
            for key, value in data.get("positions", {}).items()
        }

        return cls(
            starting_cash=float(data.get("starting_cash", starting_cash)),
            cash_balance=float(data.get("cash_balance", starting_cash)),
            realized_pnl=float(data.get("realized_pnl", 0.0)),
            positions=positions,
        )

    def save(self, path: str) -> None:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "starting_cash": self.starting_cash,
            "cash_balance": self.cash_balance,
            "realized_pnl": self.realized_pnl,
            "positions": {
                key: asdict(value)
                for key, value in self.positions.items()
            },
        }

        file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def _position_key(token_id: str, side: str) -> str:
        return f"{token_id}:{side}"

    def apply_fill(self, token_id: str, side: str, size: float, price: float) -> None:
        """
        Regista uma execução FILLED como aumento de posição.
        Para já esta versão assume acumulação de posição no mesmo lado.
        """
        if size <= 0 or price <= 0:
            return

        key = self._position_key(token_id, side)
        cost = size * price

        self.cash_balance -= cost

        if key not in self.positions:
            self.positions[key] = PortfolioPosition(
                token_id=token_id,
                side=side,
                size=size,
                average_price=price,
                last_mark_price=price,
            )
            return

        position = self.positions[key]
        new_total_size = position.size + size
        new_total_cost = (position.size * position.average_price) + cost

        position.size = new_total_size
        position.average_price = new_total_cost / new_total_size if new_total_size > 0 else 0.0
        position.last_mark_price = price

    def mark_position(self, token_id: str, side: str, mark_price: float) -> None:
        key = self._position_key(token_id, side)
        if key in self.positions and mark_price > 0:
            self.positions[key].last_mark_price = mark_price

    @property
    def invested_value(self) -> float:
        return sum(position.invested_value for position in self.positions.values())

    @property
    def market_value(self) -> float:
        return sum(position.market_value for position in self.positions.values())

    @property
    def unrealized_pnl(self) -> float:
        return sum(position.unrealized_pnl for position in self.positions.values())

    @property
    def equity_total(self) -> float:
        return self.cash_balance + self.market_value

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    @property
    def return_pct(self) -> float:
        if self.starting_cash <= 0:
            return 0.0
        return (self.equity_total - self.starting_cash) / self.starting_cash * 100.0

    def snapshot(self) -> dict[str, float]:
        return {
            "starting_cash": round(self.starting_cash, 6),
            "cash_balance": round(self.cash_balance, 6),
            "invested_value": round(self.invested_value, 6),
            "market_value": round(self.market_value, 6),
            "realized_pnl": round(self.realized_pnl, 6),
            "unrealized_pnl": round(self.unrealized_pnl, 6),
            "equity_total": round(self.equity_total, 6),
            "total_pnl": round(self.total_pnl, 6),
            "return_pct": round(self.return_pct, 6),
        }