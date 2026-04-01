from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import AppConfig, load_config
from bot.csv_logger import append_csv_row
from bot.execution import ExecutionEngine
from bot.paper_portfolio import PaperPortfolio
from bot.polymarket_client import PolymarketClient
from bot.price_history import (
    append_raw_market_snapshot,
    bootstrap_history_file_from_api,
    build_market_data_from_candles,
)
from bot.trader import Trader
from strategies.base_strategy import StrategyContext
from strategies.macd_classic import MacdClassicStrategy
from strategies.macd_refined import MacdRefinedStrategy
from strategies.position_sizing import (
    PositionSizingConfig,
    PositionSizingMode,
    PositionSizingState,
    PositionSizer,
)
from strategies.rsi_vwap import RsiVwapStrategy


LOGS_DIR = PROJECT_ROOT / "logs"
TOKEN_ANALYSIS_JSON = PROJECT_ROOT / "token_analysis_results.json"
WATCH_STATE_PATH = LOGS_DIR / "watch_state.json"

MIN_API_HISTORY_POINTS = 20
API_HISTORY_FIDELITY = 5
TOKEN_ANALYSIS_MAX_AGE_SECONDS = 300

BTC_KEYWORDS = [
    "bitcoin",
    "btc",
    "xbt",
    "satoshi",
    "ath",
    "all time high",
]

NEW_ENTRY_MIN_DAYS = 15.0
NEW_ENTRY_MAX_DAYS = 60.0
FORCE_EXIT_DAYS = 7.0
MAX_SWITCH_SCORE_RATIO = 1.25


@dataclass
class WatchState:
    watched_token_id: str = ""
    watched_market_name: str = ""
    watched_outcome: str = ""
    watched_score: float = 0.0
    updated_at: str = ""


@dataclass
class CandidateToken:
    token_id: str
    market_name: str
    outcome: str
    score: float
    midpoint: float
    spread: float
    return_pct: float
    trend_consistency: float
    history_points: int
    end_date: str = ""
    days_to_resolution: float = 9999.0
    liquidity: float = 0.0
    volume: float = 0.0
    btc_relevance_score: float = 0.0
    final_score: float = 0.0


def get_strategies() -> dict:
    return {
        "macd_classic": MacdClassicStrategy(),
        "macd_refined": MacdRefinedStrategy(),
        "rsi_vwap": RsiVwapStrategy(),
    }


def get_public_clob_host(config: AppConfig) -> str:
    raw_host = getattr(config.polymarket, "host", None) or "https://clob.polymarket.com"
    return str(raw_host).rstrip("/")


def is_file_stale(path: Path, max_age_seconds: int) -> bool:
    if not path.exists():
        return True
    try:
        age_seconds = time.time() - path.stat().st_mtime
        return age_seconds > max_age_seconds
    except Exception:
        return True


def ensure_token_analysis_exists(force_refresh: bool = False) -> None:
    should_refresh = force_refresh or is_file_stale(
        TOKEN_ANALYSIS_JSON,
        max_age_seconds=TOKEN_ANALYSIS_MAX_AGE_SECONDS,
    )

    if not should_refresh:
        return

    print("Refreshing market scan files...")
    print("-------------------------------")

    python_exec = sys.executable

    try:
        subprocess.run(
            [python_exec, "scripts/gamma_scanner_standalone.py"],
            cwd=PROJECT_ROOT,
            check=True,
        )
        subprocess.run(
            [python_exec, "scripts/clob_market_analyzer_standalone.py"],
            cwd=PROJECT_ROOT,
            check=True,
        )
        print("Market scan refreshed successfully.")
        print()
    except subprocess.CalledProcessError as exc:
        print(f"WARNING: failed to refresh market scan files: {exc}")
        print("Continuing with existing files if available.")
        print()


def build_fake_history_from_orderbook(best_bid: float, best_ask: float) -> dict:
    midpoint = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.5

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    base = midpoint - 0.03

    for i in range(220):
        value = base + (i * 0.00025)

        if i % 13 in (0, 1, 2):
            value -= 0.002
        elif i % 13 in (7, 8):
            value += 0.0015

        value = max(0.05, min(0.95, value))

        high = min(value + 0.01, 0.99)
        low = max(value - 0.01, 0.01)

        closes.append(value)
        highs.append(high)
        lows.append(low)
        volumes.append(10.0 + (i % 5))

    closes[-1] = midpoint
    highs[-1] = min(midpoint + 0.01, 0.99)
    lows[-1] = max(midpoint - 0.01, 0.01)

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def parse_iso_datetime(raw_value: str) -> Optional[datetime]:
    text = str(raw_value or "").strip()
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def compute_days_to_resolution(raw_end_date: str) -> float:
    parsed = parse_iso_datetime(raw_end_date)
    if parsed is None:
        return 9999.0

    now = datetime.now(timezone.utc)
    return (parsed - now).total_seconds() / 86400.0


def is_btc_market_name(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in BTC_KEYWORDS)


def compute_btc_relevance_score(market_name: str) -> float:
    normalized = str(market_name or "").strip().lower()
    if not normalized:
        return 0.0

    score = 0.0
    if "bitcoin" in normalized:
        score += 0.50
    if "btc" in normalized:
        score += 0.40
    if "ath" in normalized or "all time high" in normalized:
        score += 0.15
    if "above" in normalized or "below" in normalized:
        score += 0.10
    if "reach" in normalized or "hit" in normalized:
        score += 0.10
    if "price" in normalized or "$" in normalized:
        score += 0.10

    return min(score, 1.0)


def compute_time_score(days_to_resolution: float) -> float:
    if NEW_ENTRY_MIN_DAYS <= days_to_resolution <= 45:
        return 1.0
    if 45 < days_to_resolution <= NEW_ENTRY_MAX_DAYS:
        return 0.8
    if FORCE_EXIT_DAYS < days_to_resolution < NEW_ENTRY_MIN_DAYS:
        return 0.4
    return 0.0


def compute_price_zone_score(midpoint: float) -> float:
    if 0.35 <= midpoint <= 0.80:
        return 1.0
    if 0.20 <= midpoint < 0.35:
        return 0.7
    if 0.80 < midpoint <= 0.90:
        return 0.5
    if 0.10 <= midpoint < 0.20:
        return 0.2
    return 0.0


def compute_spread_score(spread: float) -> float:
    if spread <= 0:
        return 0.0
    if spread <= 0.01:
        return 1.0
    if spread <= 0.02:
        return 0.8
    if spread <= 0.03:
        return 0.5
    if spread <= 0.05:
        return 0.2
    return 0.0


def compute_liquidity_score(liquidity: float, volume: float) -> float:
    liquidity_score = min(max(liquidity / 10000.0, 0.0), 1.0)
    volume_score = min(max(volume / 10000.0, 0.0), 1.0)
    return (liquidity_score * 0.7) + (volume_score * 0.3)


def compute_candidate_final_score(candidate: CandidateToken) -> float:
    time_score = compute_time_score(candidate.days_to_resolution)
    price_score = compute_price_zone_score(candidate.midpoint)
    spread_score = compute_spread_score(candidate.spread)
    liquidity_score = compute_liquidity_score(candidate.liquidity, candidate.volume)
    btc_score = candidate.btc_relevance_score

    base_json_score = max(candidate.score, 0.0)
    normalized_json_score = min(base_json_score / 100.0, 1.0) if base_json_score > 1 else min(base_json_score, 1.0)

    outcome_bias_penalty = 0.03 if candidate.outcome == "YES" and candidate.days_to_resolution >= NEW_ENTRY_MIN_DAYS else 0.0

    final_score = (
        btc_score * 0.20
        + time_score * 0.20
        + spread_score * 0.15
        + price_score * 0.15
        + liquidity_score * 0.10
        + normalized_json_score * 0.10
        + max(candidate.trend_consistency, 0.0) * 0.05
        + min(max(candidate.return_pct / 20.0, 0.0), 1.0) * 0.05
    ) - outcome_bias_penalty

    return round(max(final_score, 0.0), 6)


def load_watch_state(path: Path = WATCH_STATE_PATH) -> WatchState:
    if not path.exists():
        return WatchState()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return WatchState(
            watched_token_id=str(data.get("watched_token_id", "") or ""),
            watched_market_name=str(data.get("watched_market_name", "") or ""),
            watched_outcome=str(data.get("watched_outcome", "") or ""),
            watched_score=float(data.get("watched_score", 0.0) or 0.0),
            updated_at=str(data.get("updated_at", "") or ""),
        )
    except Exception:
        return WatchState()


def save_watch_state(state: WatchState, path: Path = WATCH_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), ensure_ascii=False, indent=2), encoding="utf-8")


def clear_watch_state(path: Path = WATCH_STATE_PATH) -> None:
    save_watch_state(WatchState(), path=path)


def split_position_key(raw_key: str) -> tuple[str, str]:
    text = str(raw_key or "").strip()
    if ":" in text:
        token_id, side = text.rsplit(":", 1)
        return token_id.strip(), side.strip().upper()
    return text, ""


def fetch_spread(config: AppConfig, token_id: str) -> float:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/spread",
            params={"token_id": token_id},
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: spread HTTP {response.status_code} for token {token_id}")
            return 0.0

        payload = response.json()
        return float(payload.get("spread", 0.0) or 0.0)

    except Exception as exc:
        print(f"WARNING: spread fetch failed for token {token_id}: {exc}")
        return 0.0


def fetch_last_trade_price(config: AppConfig, token_id: str) -> dict:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/last-trade-price",
            params={"token_id": token_id},
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: last-trade-price HTTP {response.status_code} for token {token_id}")
            return {"price": 0.0, "side": ""}

        payload = response.json()
        return {
            "price": float(payload.get("price", 0.0) or 0.0),
            "side": str(payload.get("side", "") or ""),
        }

    except Exception as exc:
        print(f"WARNING: last-trade-price fetch failed for token {token_id}: {exc}")
        return {"price": 0.0, "side": ""}


def fetch_order_book_safe(client: PolymarketClient, token_id: str):
    try:
        return client.get_order_book(token_id)
    except Exception as exc:
        print(f"WARNING: order book fetch failed for token {token_id}: {exc}")
        return None


def fetch_prices_history_from_api(
    config: AppConfig,
    token_id: str,
    interval: str = "1d",
    fidelity: int = API_HISTORY_FIDELITY,
) -> list[float]:
    host = get_public_clob_host(config)

    try:
        response = requests.get(
            f"{host}/prices-history",
            params={
                "market": token_id,
                "interval": interval,
                "fidelity": fidelity,
            },
            timeout=20,
        )

        if response.status_code != 200:
            print(f"WARNING: prices-history HTTP {response.status_code} for token {token_id}")
            return []

        payload = response.json()
        history = payload.get("history", [])
        if not isinstance(history, list):
            return []

        prices: list[float] = []
        for row in history:
            if not isinstance(row, dict):
                continue
            p = safe_float(row.get("p"), default=-1.0)
            if p > 0:
                prices.append(p)

        return prices

    except Exception as exc:
        print(f"WARNING: prices-history fetch failed for token {token_id}: {exc}")
        return []


def build_market_data_from_api_prices(prices: list[float]) -> Optional[dict]:
    if len(prices) < MIN_API_HISTORY_POINTS:
        return None

    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    volumes: list[float] = []

    for i, price in enumerate(prices):
        prev_price = prices[i - 1] if i > 0 else price
        next_price = prices[i + 1] if i < len(prices) - 1 else price

        hi = max(price, prev_price, next_price)
        lo = min(price, prev_price, next_price)

        pad = max(0.0005, price * 0.0025)
        high = min(0.999, hi + pad)
        low = max(0.001, lo - pad)

        closes.append(price)
        highs.append(high)
        lows.append(low)
        volumes.append(10.0 + (i % 7))

    return {
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "volumes": volumes,
    }


def build_position_sizer_config(config: AppConfig) -> PositionSizingConfig:
    mode_raw = (config.position_sizing.mode or "fixed_percent").strip().lower()

    try:
        mode = PositionSizingMode(mode_raw)
    except ValueError:
        mode = PositionSizingMode.FIXED_PERCENT

    return PositionSizingConfig(
        mode=mode,
        starting_balance=config.position_sizing.starting_balance,
        min_order_size=config.position_sizing.min_order_size,
        max_order_size=config.position_sizing.max_order_size,
        max_exposure_pct=config.position_sizing.max_exposure_pct,
        fixed_percent=config.position_sizing.fixed_percent,
        fixed_amount=config.position_sizing.fixed_amount,
        kelly_win_rate=config.position_sizing.kelly_win_rate,
        kelly_reward_ratio=config.position_sizing.kelly_reward_ratio,
        martingale_base_amount=config.position_sizing.martingale_base_amount,
        martingale_multiplier=config.position_sizing.martingale_multiplier,
        martingale_max_steps=config.position_sizing.martingale_max_steps,
        anti_martingale_base_amount=config.position_sizing.anti_martingale_base_amount,
        anti_martingale_multiplier=config.position_sizing.anti_martingale_multiplier,
        anti_martingale_max_steps=config.position_sizing.anti_martingale_max_steps,
        signal_conf_low_pct=config.position_sizing.signal_conf_low_pct,
        signal_conf_medium_pct=config.position_sizing.signal_conf_medium_pct,
        signal_conf_high_pct=config.position_sizing.signal_conf_high_pct,
    )


def build_position_sizing_state(portfolio_snapshot: dict) -> PositionSizingState:
    equity_total = float(portfolio_snapshot.get("equity_total", 0.0) or 0.0)
    market_value = float(portfolio_snapshot.get("market_value", 0.0) or 0.0)

    return PositionSizingState(
        current_balance=equity_total,
        open_exposure=market_value,
        consecutive_losses=0,
        consecutive_wins=0,
    )


def get_signal_strength(result) -> str:
    if not result:
        return "medium"

    metadata = getattr(result, "metadata", {}) or {}
    raw_strength = str(metadata.get("signal_strength", "")).strip().lower()

    if raw_strength in {"low", "medium", "high"}:
        return raw_strength

    return "medium"


def load_candidates_from_json(max_candidates: int = 10) -> list[CandidateToken]:
    if not TOKEN_ANALYSIS_JSON.exists():
        print(f"WARNING: {TOKEN_ANALYSIS_JSON.name} não existe.")
        return []

    try:
        data = json.loads(TOKEN_ANALYSIS_JSON.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARNING: erro ao ler {TOKEN_ANALYSIS_JSON.name}: {exc}")
        return []

    if not isinstance(data, list):
        print(f"WARNING: {TOKEN_ANALYSIS_JSON.name} não é uma lista.")
        return []

    print(f"Raw candidates in JSON : {len(data)}")

    candidates: list[CandidateToken] = []
    failed = 0

    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            failed += 1
            continue

        try:
            token_id = str(item.get("token_id", "")).strip()
            if not token_id:
                failed += 1
                continue

            market_name = (
                item.get("parent_question")
                or item.get("parent_event_title")
                or item.get("question")
                or item.get("event_title")
                or "Unknown Market"
            )

            outcome = str(item.get("outcome", "") or "").strip().upper()
            end_date = (
                item.get("end_date")
                or item.get("endDate")
                or item.get("end_date_iso")
                or item.get("resolve_date")
                or ""
            )

            liquidity = safe_float(item.get("liquidity"), 0.0)
            volume = safe_float(item.get("volume"), 0.0)
            days_to_resolution = compute_days_to_resolution(end_date)
            btc_relevance_score = compute_btc_relevance_score(str(market_name))

            candidate = CandidateToken(
                token_id=token_id,
                market_name=str(market_name),
                outcome=outcome,
                score=safe_float(item.get("score"), 0.0),
                midpoint=safe_float(item.get("midpoint"), 0.0),
                spread=safe_float(item.get("spread"), 0.0),
                return_pct=safe_float(item.get("return_pct"), 0.0),
                trend_consistency=safe_float(item.get("trend_consistency"), 0.0),
                history_points=int(item.get("history_points", 0) or 0),
                end_date=str(end_date or ""),
                days_to_resolution=days_to_resolution,
                liquidity=liquidity,
                volume=volume,
                btc_relevance_score=btc_relevance_score,
                final_score=0.0,
            )
            candidate.final_score = compute_candidate_final_score(candidate)
            candidates.append(candidate)

        except Exception as exc:
            failed += 1
            print(f"WARNING: candidate {idx} inválido: {exc}")

    candidates.sort(key=lambda x: x.final_score, reverse=True)

    print(f"Parsed candidates      : {len(candidates)}")
    print(f"Failed candidates      : {failed}")

    if max_candidates > 0:
        candidates = candidates[:max_candidates]

    return candidates


def is_candidate_still_watchable(candidate: Optional[CandidateToken]) -> tuple[bool, str]:
    if candidate is None:
        return False, "missing_candidate"
    if not is_btc_market_name(candidate.market_name):
        return False, "not_btc_market"
    if candidate.days_to_resolution <= FORCE_EXIT_DAYS:
        return False, "too_close_to_resolution"
    if candidate.days_to_resolution > NEW_ENTRY_MAX_DAYS:
        return False, "too_far_from_resolution"
    if candidate.midpoint <= 0:
        return False, "missing_midpoint"
    if candidate.midpoint < 0.10 or candidate.midpoint > 0.90:
        return False, "midpoint_outside_range"
    if candidate.spread <= 0 or candidate.spread > 0.02:
        return False, "spread_invalid"
    if candidate.final_score <= 0:
        return False, "score_too_low"
    return True, "watchable"


def resolve_open_position_token_id(portfolio) -> Optional[str]:
    positions = getattr(portfolio, "positions", {}) or {}
    if not positions:
        return None

    for raw_key, position in positions.items():
        size = float(getattr(position, "size", 0.0) or 0.0)
        if size > 0:
            token_id, _ = split_position_key(str(raw_key))
            return token_id

    return None


def resolve_open_position_side(portfolio, token_id: str) -> str:
    positions = getattr(portfolio, "positions", {}) or {}
    if not positions:
        return ""

    for raw_key, position in positions.items():
        size = float(getattr(position, "size", 0.0) or 0.0)
        if size <= 0:
            continue

        parsed_token_id, parsed_side = split_position_key(str(raw_key))
        if parsed_token_id == token_id:
            if parsed_side:
                return parsed_side

            side = getattr(position, "side", "")
            return str(side or "").strip().upper()

    return ""


def build_trader(config: AppConfig, client: PolymarketClient) -> Trader:
    execution_engine = ExecutionEngine(
        app_config=config,
        polymarket_client=client,
    )
    return Trader(
        strategies=get_strategies(),
        execution_engine=execution_engine,
    )


def find_candidate_by_token_id(token_id: str, candidates: list[CandidateToken]) -> Optional[CandidateToken]:
    for candidate in candidates:
        if candidate.token_id == token_id:
            return candidate
    return None


def choose_watched_candidate(
    *,
    watch_state: WatchState,
    candidates: list[CandidateToken],
) -> tuple[Optional[CandidateToken], WatchState, str]:
    if not candidates:
        new_state = WatchState()
        return None, new_state, "no_candidates"

    best_candidate = candidates[0]
    watched_candidate = find_candidate_by_token_id(watch_state.watched_token_id, candidates)

    if watched_candidate is None:
        new_state = WatchState(
            watched_token_id=best_candidate.token_id,
            watched_market_name=best_candidate.market_name,
            watched_outcome=best_candidate.outcome,
            watched_score=best_candidate.final_score,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return best_candidate, new_state, "watch_initialized"

    still_watchable, reason = is_candidate_still_watchable(watched_candidate)
    if not still_watchable:
        new_state = WatchState(
            watched_token_id=best_candidate.token_id,
            watched_market_name=best_candidate.market_name,
            watched_outcome=best_candidate.outcome,
            watched_score=best_candidate.final_score,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return best_candidate, new_state, f"watch_replaced_{reason}"

    if best_candidate.token_id != watched_candidate.token_id:
        if best_candidate.final_score >= watched_candidate.final_score * MAX_SWITCH_SCORE_RATIO:
            new_state = WatchState(
                watched_token_id=best_candidate.token_id,
                watched_market_name=best_candidate.market_name,
                watched_outcome=best_candidate.outcome,
                watched_score=best_candidate.final_score,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            return best_candidate, new_state, "watch_switched_better_candidate"

    new_state = WatchState(
        watched_token_id=watched_candidate.token_id,
        watched_market_name=watched_candidate.market_name,
        watched_outcome=watched_candidate.outcome,
        watched_score=watched_candidate.final_score,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    return watched_candidate, new_state, "watch_kept"


def evaluate_token(
    *,
    config: AppConfig,
    client: PolymarketClient,
    token_id: str,
    market_name: str,
    outcome: str,
    position_sizer: PositionSizer,
    position_state: PositionSizingState,
) -> Optional[dict]:
    clob_host = get_public_clob_host(config)

    spread = fetch_spread(config, token_id)
    last_trade = fetch_last_trade_price(config, token_id)
    book = fetch_order_book_safe(client, token_id)

    if book is None:
        print(f"WARNING: skipping token without order book: {token_id}")
        return None

    history_path = bootstrap_history_file_from_api(
        logs_dir=LOGS_DIR,
        clob_host=clob_host,
        token_id=token_id,
        lookback_hours=24,
    )

    timestamp_utc = datetime.now(timezone.utc).isoformat()

    append_raw_market_snapshot(
        history_path=history_path,
        timestamp_utc=timestamp_utc,
        best_bid=book.best_bid,
        best_ask=book.best_ask,
        bid_size=book.bid_size,
        ask_size=book.ask_size,
        spread=spread,
        last_trade_price=last_trade["price"],
        last_trade_side=last_trade["side"],
        keep_last_hours=24,
    )

    api_prices = fetch_prices_history_from_api(
        config=config,
        token_id=token_id,
        interval="1d",
        fidelity=API_HISTORY_FIDELITY,
    )

    market_data = build_market_data_from_api_prices(api_prices)
    history_source = "api_prices_history"

    if market_data is None:
        market_data = build_market_data_from_candles(
            history_path=history_path,
            keep_last_hours=24,
            candle_minutes=1,
            min_candles=35,
        )
        history_source = "local_raw+api_bootstrap"

    if market_data is None:
        history_source = "synthetic_fallback"
        market_data = build_fake_history_from_orderbook(book.best_bid, book.best_ask)

    calculated_order_size = position_sizer.calculate_order_size(
        state=position_state,
        signal_strength="medium",
    )

    context = StrategyContext(
        market_id=token_id,
        timestamp="live-paper-snapshot",
        data=market_data,
    )

    result = None
    local_trader = None

    if calculated_order_size > 0:
        local_trader = build_trader(config, client)
        result = local_trader.process_market(
            strategy_name=config.trading.strategy_name,
            context=context,
            best_bid=book.best_bid,
            best_ask=book.best_ask,
            order_size=calculated_order_size,
            token_id=token_id,
        )

    midpoint = (book.best_bid + book.best_ask) / 2 if book.best_bid > 0 and book.best_ask > 0 else 0.0

    return {
        "token_id": token_id,
        "market_name": market_name,
        "outcome": outcome,
        "spread": spread,
        "last_trade": last_trade,
        "book": book,
        "history_path": history_path,
        "history_source": history_source,
        "api_history_points": len(api_prices),
        "api_history_enough": len(api_prices) >= MIN_API_HISTORY_POINTS,
        "api_history_fidelity": API_HISTORY_FIDELITY,
        "calculated_order_size": calculated_order_size,
        "result": result,
        "midpoint": midpoint,
        "trader": local_trader,
    }


def maybe_force_exit_near_resolution(
    result,
    candidate: Optional[CandidateToken],
    current_open_side: str,
):
    if result is None or candidate is None:
        return result

    if candidate.days_to_resolution > FORCE_EXIT_DAYS:
        return result

    metadata = dict(getattr(result, "metadata", {}) or {})
    existing_signal = getattr(result, "signal", None)

    if existing_signal and getattr(existing_signal, "value", "") == "SELL":
        return result

    metadata["position_side"] = current_open_side or metadata.get("position_side", "")
    metadata["side"] = current_open_side or metadata.get("side", "")
    metadata["forced_exit"] = True
    metadata["days_to_resolution"] = candidate.days_to_resolution

    result.signal = type(result.signal).SELL
    result.reason = f"force_exit_near_resolution({candidate.days_to_resolution:.2f}d)"
    result.metadata = metadata

    print("FORCED EXIT           : True")
    print(f"Force exit reason     : near resolution ({candidate.days_to_resolution:.2f} days)")
    print()

    return result


def print_portfolio_snapshot(portfolio_snapshot: dict) -> None:
    print("Portfolio")
    print("---------")
    for key, value in portfolio_snapshot.items():
        print(f"{key}: {value}")


def print_open_orders_and_positions(trader_for_final) -> None:
    print("Open orders")
    print("-----------")
    if (
        trader_for_final is not None
        and getattr(trader_for_final, "order_manager", None) is not None
        and getattr(trader_for_final.order_manager, "orders", None) is not None
    ):
        for order in trader_for_final.order_manager.orders.values():
            print(order)
    else:
        print("No order manager / no open orders")

    print()
    print("Positions")
    print("---------")
    if (
        trader_for_final is not None
        and getattr(trader_for_final, "state", None) is not None
        and getattr(trader_for_final.state, "positions", None) is not None
    ):
        for market_id, position in trader_for_final.state.positions.items():
            print(market_id, position)
    else:
        print("No trader state / no positions")


def main() -> None:
    config = load_config()

    portfolio = PaperPortfolio.load(
        "logs/portfolio_state.json",
        starting_cash=config.trading.paper_starting_cash,
    )

    risk_config = build_position_sizer_config(config)
    position_sizer = PositionSizer(risk_config)

    portfolio_snapshot_before = portfolio.snapshot()
    position_state = build_position_sizing_state(portfolio_snapshot_before)
    watch_state = load_watch_state()

    print(f"Mode                 : {config.trading.trading_mode}")
    print(f"Dry run              : {config.trading.dry_run}")
    print(f"Strategy             : {config.trading.strategy_name}")
    print(f"Position sizing mode : {risk_config.mode.value}")
    print(f"Default order size   : {config.trading.default_order_size}")
    print(f"Starting cash        : {config.trading.paper_starting_cash}")
    print(f"Equity before cycle  : {position_state.current_balance}")
    print(f"Open exposure        : {position_state.open_exposure}")
    print()

    ensure_token_analysis_exists(force_refresh=True)

    client = PolymarketClient(config.polymarket)

    all_candidates = load_candidates_from_json(max_candidates=20)
    current_open_token_id = resolve_open_position_token_id(portfolio)
    current_open_side = resolve_open_position_side(portfolio, current_open_token_id) if current_open_token_id else ""
    current_open_candidate = find_candidate_by_token_id(current_open_token_id, all_candidates) if current_open_token_id else None

    selected_token_id: Optional[str] = None
    selected_market_name: str = ""
    selected_outcome: str = ""
    selected_evaluation: Optional[dict] = None
    selected_candidate: Optional[CandidateToken] = None

    if current_open_token_id:
        clear_watch_state()

        selected_token_id = current_open_token_id
        selected_market_name = current_open_candidate.market_name if current_open_candidate else current_open_token_id
        selected_outcome = current_open_side or (current_open_candidate.outcome if current_open_candidate else "")
        selected_candidate = current_open_candidate

        print("Open position detected. Managing current position.")
        print(f"Token ID             : {selected_token_id}")
        if current_open_candidate is not None:
            print(f"Market               : {current_open_candidate.market_name} [{current_open_candidate.outcome}]")
            print(f"Days to resolution   : {current_open_candidate.days_to_resolution:.2f}")
            print(f"BTC relevance score  : {current_open_candidate.btc_relevance_score}")
            print(f"Final score          : {current_open_candidate.final_score}")
        print()
    else:
        candidates = all_candidates[:10]

        if not candidates:
            print("Nenhum candidato BTC elegível encontrado neste ciclo.")
            print()
            print_portfolio_snapshot(portfolio_snapshot_before)
            return

        print("Watch candidate selection")
        print("-------------------------")

        watched_candidate, new_watch_state, watch_reason = choose_watched_candidate(
            watch_state=watch_state,
            candidates=candidates,
        )
        save_watch_state(new_watch_state)

        print(f"Watch decision       : {watch_reason}")
        print(f"Watched token ID     : {new_watch_state.watched_token_id}")
        print(f"Watched market       : {new_watch_state.watched_market_name}")
        print(f"Watched outcome      : {new_watch_state.watched_outcome}")
        print(f"Watched score        : {new_watch_state.watched_score}")
        print()

        if watched_candidate is None:
            print("Nenhum mercado observável encontrado neste ciclo.")
            print_portfolio_snapshot(portfolio_snapshot_before)
            return

        selected_candidate = watched_candidate

        selected_evaluation = evaluate_token(
            config=config,
            client=client,
            token_id=selected_candidate.token_id,
            market_name=selected_candidate.market_name,
            outcome=selected_candidate.outcome,
            position_sizer=position_sizer,
            position_state=position_state,
        )

        if selected_evaluation is None:
            print("Mercado observado sem order book válido neste ciclo.")
            print_portfolio_snapshot(portfolio_snapshot_before)
            return

        result = selected_evaluation["result"]
        book = selected_evaluation["book"]
        spread = selected_evaluation["spread"]
        last_trade = selected_evaluation["last_trade"]

        print("Watched market evaluation")
        print("-------------------------")
        print(f"Market               : {selected_candidate.market_name} [{selected_candidate.outcome}]")
        print(f"Token ID             : {selected_candidate.token_id}")
        print(f"Final score          : {selected_candidate.final_score}")
        print(f"Days to resolution   : {selected_candidate.days_to_resolution:.2f}")
        print(f"Midpoint             : {selected_candidate.midpoint}")
        print(f"Spread               : {selected_candidate.spread}")
        print(f"Live best_bid        : {book.best_bid}")
        print(f"Live best_ask        : {book.best_ask}")
        print(f"Live spread          : {spread}")
        print(f"Last trade px        : {last_trade['price']}")
        print(f"Last trade side      : {last_trade['side']}")
        print(f"History source       : {selected_evaluation['history_source']}")
        print(f"API hist points      : {selected_evaluation['api_history_points']}")
        print(f"API hist enough      : {selected_evaluation['api_history_enough']}")
        print(f"API fidelity         : {selected_evaluation['api_history_fidelity']}")
        print(f"History file         : {selected_evaluation['history_path'].name}")
        print(f"Calc order size      : {selected_evaluation['calculated_order_size']}")
        print(f"Strategy result      : {result}")
        print()

        if result is None:
            print("Sem resultado da estratégia neste ciclo.")
            print_portfolio_snapshot(portfolio_snapshot_before)
            return

        if result.signal.value != "BUY":
            print("Mercado observado continua em espera. Ainda sem BUY.")
            print()
            print_portfolio_snapshot(portfolio_snapshot_before)
            return

        selected_token_id = selected_candidate.token_id
        selected_market_name = selected_candidate.market_name
        selected_outcome = selected_candidate.outcome

    if not selected_token_id:
        print("No token selected.")
        return

    if selected_evaluation is None:
        final_evaluation = evaluate_token(
            config=config,
            client=client,
            token_id=selected_token_id,
            market_name=selected_market_name,
            outcome=selected_outcome,
            position_sizer=position_sizer,
            position_state=position_state,
        )
        if final_evaluation is None:
            print("Token selecionado sem order book válido.")
            print_portfolio_snapshot(portfolio_snapshot_before)
            return
    else:
        final_evaluation = selected_evaluation

    spread = final_evaluation["spread"]
    last_trade = final_evaluation["last_trade"]
    book = final_evaluation["book"]
    result = final_evaluation["result"]
    midpoint = final_evaluation["midpoint"]
    trader_for_final = final_evaluation["trader"]

    if current_open_token_id and selected_candidate is not None:
        result = maybe_force_exit_near_resolution(
            result=result,
            candidate=selected_candidate,
            current_open_side=current_open_side,
        )

    print(f"spread   : {spread}")
    print(f"last_px  : {last_trade['price']}")
    print(f"last_side: {last_trade['side']}")
    print()

    if final_evaluation["history_source"] == "synthetic_fallback":
        print("WARNING: insufficient real history. Falling back to synthetic history for this cycle.")
    else:
        print(
            f"History source      : {final_evaluation['history_source']}\n"
            f"API hist points     : {final_evaluation['api_history_points']}\n"
            f"API hist enough     : {final_evaluation['api_history_enough']}\n"
            f"API fidelity        : {final_evaluation['api_history_fidelity']}\n"
            f"Min API hist needed : {MIN_API_HISTORY_POINTS}\n"
            f"History file        : {final_evaluation['history_path'].name}\n"
            f"History window      : 24h"
        )
    print()

    print("Live order book snapshot")
    print("------------------------")
    print(f"best_bid : {book.best_bid}")
    print(f"best_ask : {book.best_ask}")
    print(f"bid_size : {book.bid_size}")
    print(f"ask_size : {book.ask_size}")
    print()

    calculated_order_size = final_evaluation["calculated_order_size"]

    if calculated_order_size <= 0:
        print("Calculated order size is 0. No available exposure for a new trade.")
        print()
        print_portfolio_snapshot(portfolio_snapshot_before)
        return

    print(f"Calculated order size: {calculated_order_size}")
    print()

    print("Trader decision")
    print("---------------")
    print(result)
    print()

    print_open_orders_and_positions(trader_for_final)

    signal_strength = get_signal_strength(result)

    metadata = result.metadata if result else {}
    order_status = metadata.get("order_status", "")
    position_side = metadata.get("position_side", metadata.get("side", ""))
    limit_price = float(metadata.get("limit_price", 0.0) or 0.0)
    order_size = float(metadata.get("closed_size", calculated_order_size) or 0.0)

    if order_status == "FILLED" and position_side and limit_price > 0 and order_size > 0:
        portfolio.apply_fill(
            token_id=selected_token_id,
            side=position_side,
            size=order_size,
            price=limit_price,
        )

        if result and result.signal.value == "BUY":
            clear_watch_state()

    if position_side and midpoint > 0:
        portfolio.mark_position(
            token_id=selected_token_id,
            side=position_side,
            mark_price=midpoint,
        )

    portfolio.save("logs/portfolio_state.json")
    portfolio_snapshot = portfolio.snapshot()

    timestamp_utc = datetime.now(timezone.utc).isoformat()

    append_csv_row(
        "logs/cycles.csv",
        [
            "market_name",
            "outcome",
            "spread",
            "last_trade_price",
            "last_trade_side",
            "timestamp",
            "token_id",
            "strategy",
            "position_sizing_mode",
            "signal_strength",
            "best_bid",
            "best_ask",
            "bid_size",
            "ask_size",
            "midpoint",
            "signal",
            "reason",
            "position_side",
            "limit_price",
            "order_size",
            "order_status",
            "starting_cash",
            "cash_balance",
            "invested_value",
            "market_value",
            "realized_pnl",
            "unrealized_pnl",
            "equity_total",
            "total_pnl",
            "return_pct",
        ],
        {
            "market_name": selected_market_name,
            "outcome": selected_outcome,
            "spread": spread,
            "last_trade_price": last_trade["price"],
            "last_trade_side": last_trade["side"],
            "timestamp": timestamp_utc,
            "token_id": selected_token_id,
            "strategy": config.trading.strategy_name,
            "position_sizing_mode": risk_config.mode.value,
            "signal_strength": signal_strength,
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "bid_size": book.bid_size,
            "ask_size": book.ask_size,
            "midpoint": midpoint,
            "signal": result.signal.value if result else "HOLD",
            "reason": result.reason if result else "no_trade_available_exposure_blocked",
            "position_side": position_side,
            "limit_price": limit_price,
            "order_size": order_size,
            "order_status": order_status,
            **portfolio_snapshot,
        },
    )

    if order_status == "FILLED":
        append_csv_row(
            "logs/trades.csv",
            [
                "timestamp",
                "market_name",
                "outcome",
                "token_id",
                "side",
                "price",
                "size",
                "position_sizing_mode",
                "signal_strength",
                "order_status",
                "cash_balance",
                "invested_value",
                "market_value",
                "unrealized_pnl",
                "equity_total",
                "return_pct",
            ],
            {
                "timestamp": timestamp_utc,
                "market_name": selected_market_name,
                "outcome": selected_outcome,
                "token_id": selected_token_id,
                "side": position_side,
                "price": limit_price,
                "size": order_size,
                "position_sizing_mode": risk_config.mode.value,
                "signal_strength": signal_strength,
                "order_status": order_status,
                "cash_balance": portfolio_snapshot["cash_balance"],
                "invested_value": portfolio_snapshot["invested_value"],
                "market_value": portfolio_snapshot["market_value"],
                "unrealized_pnl": portfolio_snapshot["unrealized_pnl"],
                "equity_total": portfolio_snapshot["equity_total"],
                "return_pct": portfolio_snapshot["return_pct"],
            },
        )

    append_csv_row(
        "logs/portfolio.csv",
        [
            "timestamp",
            "starting_cash",
            "cash_balance",
            "invested_value",
            "market_value",
            "realized_pnl",
            "unrealized_pnl",
            "equity_total",
            "total_pnl",
            "return_pct",
        ],
        {
            "timestamp": timestamp_utc,
            **portfolio_snapshot,
        },
    )

    print()
    print_portfolio_snapshot(portfolio_snapshot)


if __name__ == "__main__":
    main()