from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class MetricsStorage:
    def __init__(self, base_path: str = "data/metrics") -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, strategy_name: str, metrics: dict[str, Any]) -> str:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{strategy_name}_{timestamp}.json"
        filepath = self.base_path / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        return str(filepath)

    def load_all(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for file in self.base_path.glob("*.json"):
            with open(file, "r", encoding="utf-8") as f:
                results.append(json.load(f))

        return results