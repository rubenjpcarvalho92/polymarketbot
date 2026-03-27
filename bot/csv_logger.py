from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def append_csv_row(path: str, fieldnames: list[str], row: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    file_exists = file_path.exists()

    with file_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)