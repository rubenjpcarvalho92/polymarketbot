from __future__ import annotations

import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


RAW_FIELDS = [
    "timestamp",
    "source",
    "midpoint",
    "best_bid",
    "best_ask",
    "bid_size",
    "ask_size",
    "spread",
    "last_trade_price",
    "last_trade_side",
    "volume_proxy",
]


def get_history_file_path(logs_dir: Path, token_id: str) -> Path:
    safe_token = str(token_id).strip()
    return logs_dir / f"price_history_{safe_token}.csv"


def _empty_history_df() -> pd.DataFrame:
    return pd.DataFrame(columns=RAW_FIELDS)


def _fetch_api_history_points(
    clob_host: str,
    token_id: str,
    lookback_hours: int = 24,
) -> list[dict]:
    end_ts = int(time.time())
    start_ts = end_ts - (lookback_hours * 3600)

    attempts = [
        {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": "1m",
            "fidelity": 1,
        },
        {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": "5m",
            "fidelity": 5,
        },
        {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": "15m",
            "fidelity": 15,
        },
        {
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": "1h",
            "fidelity": 60,
        },
        {
            "market": token_id,
            "interval": "max",
            "fidelity": 60,
        },
    ]

    last_error = None

    for params in attempts:
        try:
            response = requests.get(
                f"{clob_host.rstrip('/')}/prices-history",
                params=params,
                timeout=20,
            )

            if response.status_code != 200:
                last_error = f"HTTP {response.status_code} for params={params}"
                continue

            payload = response.json()
            history = payload.get("history", [])

            cleaned: list[dict] = []
            for item in history:
                if "p" not in item:
                    continue

                try:
                    cleaned.append(
                        {
                            "t": int(item.get("t", 0)),
                            "p": float(item["p"]),
                        }
                    )
                except (TypeError, ValueError):
                    continue

            if cleaned:
                return cleaned

        except Exception as exc:
            last_error = exc

    print(f"WARNING: bootstrap API history failed for token {token_id}: {last_error}")
    return []


def bootstrap_history_file_from_api(
    logs_dir: Path,
    clob_host: str,
    token_id: str,
    lookback_hours: int = 24,
) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    history_path = get_history_file_path(logs_dir, token_id)

    if history_path.exists() and history_path.stat().st_size > 0:
        return history_path

    points = _fetch_api_history_points(
        clob_host=clob_host,
        token_id=token_id,
        lookback_hours=lookback_hours,
    )

    if not points:
        _empty_history_df().to_csv(history_path, index=False)
        return history_path

    rows: list[dict] = []
    for point in points:
        ts = datetime.fromtimestamp(int(point["t"]), tz=timezone.utc).isoformat()
        px = float(point["p"])

        rows.append(
            {
                "timestamp": ts,
                "source": "api_bootstrap",
                "midpoint": px,
                "best_bid": px,
                "best_ask": px,
                "bid_size": 0.0,
                "ask_size": 0.0,
                "spread": 0.0,
                "last_trade_price": px,
                "last_trade_side": "",
                "volume_proxy": 1.0,
            }
        )

    df = pd.DataFrame(rows, columns=RAW_FIELDS)
    df.to_csv(history_path, index=False)
    return history_path


def append_raw_market_snapshot(
    history_path: Path,
    timestamp_utc: str,
    best_bid: float,
    best_ask: float,
    bid_size: float,
    ask_size: float,
    spread: float,
    last_trade_price: float,
    last_trade_side: str,
    keep_last_hours: int = 24,
) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)

    midpoint = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0
    volume_proxy = max(float(bid_size or 0.0) + float(ask_size or 0.0), 1.0)

    file_exists = history_path.exists() and history_path.stat().st_size > 0

    with history_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FIELDS)

        if not file_exists:
            writer.writeheader()

        writer.writerow(
            {
                "timestamp": timestamp_utc,
                "source": "raw_cycle",
                "midpoint": midpoint,
                "best_bid": float(best_bid or 0.0),
                "best_ask": float(best_ask or 0.0),
                "bid_size": float(bid_size or 0.0),
                "ask_size": float(ask_size or 0.0),
                "spread": float(spread or 0.0),
                "last_trade_price": float(last_trade_price or 0.0),
                "last_trade_side": str(last_trade_side or ""),
                "volume_proxy": volume_proxy,
            }
        )

    prune_history_file(history_path, keep_last_hours=keep_last_hours)


def prune_history_file(history_path: Path, keep_last_hours: int = 24) -> None:
    if not history_path.exists() or history_path.stat().st_size == 0:
        return

    try:
        df = pd.read_csv(history_path, on_bad_lines="skip")
    except Exception:
        return

    if df.empty or "timestamp" not in df.columns:
        return

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=keep_last_hours)
    df = df[df["timestamp"] >= cutoff]

    if df.empty:
        df = _empty_history_df()

    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"])
        df["timestamp"] = df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S%z")

    df.to_csv(history_path, index=False)


def _load_history_df(
    history_path: Path,
    keep_last_hours: int = 24,
) -> pd.DataFrame | None:
    if not history_path.exists() or history_path.stat().st_size == 0:
        return None

    try:
        df = pd.read_csv(history_path, on_bad_lines="skip")
    except Exception:
        return None

    if df.empty or "timestamp" not in df.columns or "midpoint" not in df.columns:
        return None

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["midpoint"] = pd.to_numeric(df["midpoint"], errors="coerce")
    df["best_bid"] = pd.to_numeric(df.get("best_bid"), errors="coerce")
    df["best_ask"] = pd.to_numeric(df.get("best_ask"), errors="coerce")
    df["volume_proxy"] = pd.to_numeric(df.get("volume_proxy"), errors="coerce").fillna(1.0)

    df = df.dropna(subset=["timestamp", "midpoint"]).sort_values("timestamp")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=keep_last_hours)
    df = df[df["timestamp"] >= cutoff]

    if df.empty:
        return None

    return df


def build_market_data_from_local_history(
    history_path: Path,
    keep_last_hours: int = 24,
    min_points: int = 35,
) -> dict | None:
    df = _load_history_df(history_path=history_path, keep_last_hours=keep_last_hours)
    if df is None or len(df) < min_points:
        return None

    closes = df["midpoint"].astype(float).tolist()

    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    rolling_window = 5
    for i, _close in enumerate(closes):
        start = max(0, i - rolling_window + 1)
        window_prices = closes[start : i + 1]
        highs.append(max(window_prices))
        lows.append(min(window_prices))
        volumes.append(float(df.iloc[i]["volume_proxy"]))

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def build_candles_from_local_history(
    history_path: Path,
    keep_last_hours: int = 24,
    candle_minutes: int = 1,
) -> pd.DataFrame:
    df = _load_history_df(history_path=history_path, keep_last_hours=keep_last_hours)
    if df is None or df.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume_proxy"])

    rule = f"{int(candle_minutes)}min"

    candles = (
        df.set_index("timestamp")
        .resample(rule)
        .agg(
            open=("midpoint", "first"),
            high=("midpoint", "max"),
            low=("midpoint", "min"),
            close=("midpoint", "last"),
            volume_proxy=("volume_proxy", "sum"),
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )

    return candles


def build_market_data_from_candles(
    history_path: Path,
    keep_last_hours: int = 24,
    candle_minutes: int = 1,
    min_candles: int = 35,
) -> dict | None:
    candles = build_candles_from_local_history(
        history_path=history_path,
        keep_last_hours=keep_last_hours,
        candle_minutes=candle_minutes,
    )

    if candles.empty or len(candles) < min_candles:
        return None

    return {
        "closes": candles["close"].astype(float).tolist(),
        "highs": candles["high"].astype(float).tolist(),
        "lows": candles["low"].astype(float).tolist(),
        "volumes": candles["volume_proxy"].astype(float).tolist(),
    }