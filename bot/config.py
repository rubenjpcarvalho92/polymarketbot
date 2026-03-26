from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def load_dotenv_file(dotenv_path: str = ".env") -> None:
    path = Path(dotenv_path)
    if not path.exists() or not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


def _get_env(key: str, default: Optional[str] = None, required: bool = False) -> str:
    value = os.getenv(key, default)

    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {key}")

    return "" if value is None else value


def _get_int(key: str, default: int) -> int:
    value = os.getenv(key)
    return int(value) if value not in (None, "") else default


def _get_float(key: str, default: float) -> float:
    value = os.getenv(key)
    return float(value) if value not in (None, "") else default


def _get_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class PolymarketConfig:
    host: str
    chain_id: int
    private_key: str
    api_key: str
    api_secret: str
    api_passphrase: str


@dataclass(slots=True)
class TradingConfig:
    environment: str
    trading_mode: str
    strategy_name: str
    default_market_slug: str
    default_token_id: str
    default_timeframe: str
    dry_run: bool
    max_spread: float
    min_top_book_depth: float
    default_order_size: float


@dataclass(slots=True)
class LoggingConfig:
    level: str
    json_logs: bool


@dataclass(slots=True)
class AppConfig:
    polymarket: PolymarketConfig
    trading: TradingConfig
    logging: LoggingConfig


def load_config(dotenv_path: str = ".env") -> AppConfig:
    load_dotenv_file(dotenv_path)

    polymarket = PolymarketConfig(
        host=_get_env("POLYMARKET_HOST", "https://clob.polymarket.com"),
        chain_id=_get_int("POLYMARKET_CHAIN_ID", 137),
        private_key=_get_env("POLYMARKET_PRIVATE_KEY", ""),
        api_key=_get_env("POLYMARKET_API_KEY", ""),
        api_secret=_get_env("POLYMARKET_API_SECRET", ""),
        api_passphrase=_get_env("POLYMARKET_API_PASSPHRASE", ""),
    )

    trading = TradingConfig(
        environment=_get_env("APP_ENV", "development"),
        trading_mode=_get_env("TRADING_MODE", "paper").lower(),
        strategy_name=_get_env("STRATEGY_NAME", "macd_classic"),
        default_market_slug=_get_env("DEFAULT_MARKET_SLUG", ""),
        default_token_id=_get_env("DEFAULT_TOKEN_ID", ""),
        default_timeframe=_get_env("DEFAULT_TIMEFRAME", "5m"),
        dry_run=_get_bool("DRY_RUN", True),
        max_spread=_get_float("MAX_SPREAD", 0.03),
        min_top_book_depth=_get_float("MIN_TOP_BOOK_DEPTH", 100.0),
        default_order_size=_get_float("DEFAULT_ORDER_SIZE", 10.0),
    )

    logging = LoggingConfig(
        level=_get_env("LOG_LEVEL", "INFO").upper(),
        json_logs=_get_bool("JSON_LOGS", False),
    )

    return AppConfig(
        polymarket=polymarket,
        trading=trading,
        logging=logging,
    )