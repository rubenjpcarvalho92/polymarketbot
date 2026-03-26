from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


@dataclass(slots=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class CandleBuilder:
    """
    Builds candles from midpoint samples.

    This is intentionally simple for phase 2.
    It groups incoming midpoint samples into fixed buckets.
    """

    def __init__(self, timeframe_seconds: int) -> None:
        if timeframe_seconds <= 0:
            raise ValueError("timeframe_seconds must be > 0")
        self.timeframe_seconds = timeframe_seconds

    def build_from_midpoints(
        self,
        samples: Iterable[tuple[str, float, float]],
    ) -> list[Candle]:
        """
        samples: iterable of (timestamp_iso, midpoint, volume)
        volume may be synthetic if real trade volume is not available
        """
        buckets: dict[int, list[tuple[float, float]]] = {}

        for timestamp_str, midpoint, volume in samples:
            if midpoint <= 0:
                continue

            dt = self._parse_timestamp(timestamp_str)
            bucket_key = int(dt.timestamp()) // self.timeframe_seconds

            if bucket_key not in buckets:
                buckets[bucket_key] = []

            buckets[bucket_key].append((midpoint, volume))

        candles: list[Candle] = []

        for bucket_key in sorted(buckets.keys()):
            values = buckets[bucket_key]
            prices = [price for price, _ in values]
            volumes = [volume for _, volume in values]

            bucket_dt = datetime.fromtimestamp(
                bucket_key * self.timeframe_seconds,
                tz=timezone.utc,
            )

            candles.append(
                Candle(
                    timestamp=bucket_dt.isoformat(),
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=sum(volumes),
                )
            )

        return candles

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> datetime:
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt