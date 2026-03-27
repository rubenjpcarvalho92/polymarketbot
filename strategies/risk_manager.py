from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PositionSizingMode(str, Enum):
    FIXED_PERCENT = "fixed_percent"
    FIXED_AMOUNT = "fixed_amount"
    KELLY = "kelly"
    HALF_KELLY = "half_kelly"
    QUARTER_KELLY = "quarter_kelly"
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"
    SIGNAL_CONFIDENCE = "signal_confidence"


@dataclass
class PositionSizingConfig:
    mode: PositionSizingMode = PositionSizingMode.FIXED_PERCENT

    starting_balance: float = 100.0

    min_order_size: float = 1.0
    max_order_size: float = 1000.0
    max_exposure_pct: float = 15.0

    fixed_percent: float = 2.0
    fixed_amount: float = 10.0

    kelly_win_rate: float = 0.55
    kelly_reward_ratio: float = 1.0

    martingale_base_amount: float = 2.0
    martingale_multiplier: float = 2.0
    martingale_max_steps: int = 5

    anti_martingale_base_amount: float = 2.0
    anti_martingale_multiplier: float = 1.5
    anti_martingale_max_steps: int = 4

    signal_conf_low_pct: float = 1.0
    signal_conf_medium_pct: float = 2.0
    signal_conf_high_pct: float = 4.0


@dataclass
class PositionSizingState:
    current_balance: float
    open_exposure: float = 0.0
    consecutive_losses: int = 0
    consecutive_wins: int = 0


def _get_env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def load_position_sizing_config_from_env() -> PositionSizingConfig:
    mode_raw = _get_env_str("POSITION_SIZING_MODE", "fixed_percent").lower()

    try:
        mode = PositionSizingMode(mode_raw)
    except ValueError:
        mode = PositionSizingMode.FIXED_PERCENT

    return PositionSizingConfig(
        mode=mode,
        starting_balance=_get_env_float("STARTING_BALANCE", 100.0),
        min_order_size=_get_env_float("MIN_ORDER_SIZE", 1.0),
        max_order_size=_get_env_float("MAX_ORDER_SIZE", 1000.0),
        max_exposure_pct=_get_env_float("MAX_EXPOSURE_PCT", 15.0),
        fixed_percent=_get_env_float("FIXED_PERCENT", 2.0),
        fixed_amount=_get_env_float("FIXED_AMOUNT", 10.0),
        kelly_win_rate=_get_env_float("KELLY_WIN_RATE", 0.55),
        kelly_reward_ratio=_get_env_float("KELLY_REWARD_RATIO", 1.0),
        martingale_base_amount=_get_env_float("MARTINGALE_BASE_AMOUNT", 2.0),
        martingale_multiplier=_get_env_float("MARTINGALE_MULTIPLIER", 2.0),
        martingale_max_steps=_get_env_int("MARTINGALE_MAX_STEPS", 5),
        anti_martingale_base_amount=_get_env_float("ANTI_MARTINGALE_BASE_AMOUNT", 2.0),
        anti_martingale_multiplier=_get_env_float("ANTI_MARTINGALE_MULTIPLIER", 1.5),
        anti_martingale_max_steps=_get_env_int("ANTI_MARTINGALE_MAX_STEPS", 4),
        signal_conf_low_pct=_get_env_float("SIGNAL_CONF_LOW_PCT", 1.0),
        signal_conf_medium_pct=_get_env_float("SIGNAL_CONF_MEDIUM_PCT", 2.0),
        signal_conf_high_pct=_get_env_float("SIGNAL_CONF_HIGH_PCT", 4.0),
    )


class PositionSizer:
    def __init__(self, config: PositionSizingConfig):
        self.config = config

    def calculate_order_size(
        self,
        state: PositionSizingState,
        signal_strength: str = "medium",
        estimated_win_rate: Optional[float] = None,
        estimated_reward_ratio: Optional[float] = None,
    ) -> float:
        available_exposure = self._available_exposure(state)
        if available_exposure <= 0:
            return 0.0

        mode = self.config.mode

        if mode == PositionSizingMode.FIXED_PERCENT:
            size = state.current_balance * (self.config.fixed_percent / 100.0)

        elif mode == PositionSizingMode.FIXED_AMOUNT:
            size = self.config.fixed_amount

        elif mode == PositionSizingMode.KELLY:
            size = state.current_balance * self._kelly_fraction(
                win_rate=estimated_win_rate or self.config.kelly_win_rate,
                reward_ratio=estimated_reward_ratio or self.config.kelly_reward_ratio,
                fraction_multiplier=1.0,
            )

        elif mode == PositionSizingMode.HALF_KELLY:
            size = state.current_balance * self._kelly_fraction(
                win_rate=estimated_win_rate or self.config.kelly_win_rate,
                reward_ratio=estimated_reward_ratio or self.config.kelly_reward_ratio,
                fraction_multiplier=0.5,
            )

        elif mode == PositionSizingMode.QUARTER_KELLY:
            size = state.current_balance * self._kelly_fraction(
                win_rate=estimated_win_rate or self.config.kelly_win_rate,
                reward_ratio=estimated_reward_ratio or self.config.kelly_reward_ratio,
                fraction_multiplier=0.25,
            )

        elif mode == PositionSizingMode.MARTINGALE:
            step = min(state.consecutive_losses, self.config.martingale_max_steps)
            size = self.config.martingale_base_amount * (
                self.config.martingale_multiplier ** step
            )

        elif mode == PositionSizingMode.ANTI_MARTINGALE:
            step = min(state.consecutive_wins, self.config.anti_martingale_max_steps)
            size = self.config.anti_martingale_base_amount * (
                self.config.anti_martingale_multiplier ** step
            )

        elif mode == PositionSizingMode.SIGNAL_CONFIDENCE:
            strength = signal_strength.strip().lower()
            if strength == "low":
                pct = self.config.signal_conf_low_pct
            elif strength == "high":
                pct = self.config.signal_conf_high_pct
            else:
                pct = self.config.signal_conf_medium_pct

            size = state.current_balance * (pct / 100.0)

        else:
            size = state.current_balance * (self.config.fixed_percent / 100.0)

        size = self._clamp(size, self.config.min_order_size, self.config.max_order_size)
        size = min(size, available_exposure, state.current_balance)

        return round(max(size, 0.0), 2)

    def register_open_position(
        self,
        state: PositionSizingState,
        size: float,
    ) -> PositionSizingState:
        return PositionSizingState(
            current_balance=state.current_balance,
            open_exposure=round(state.open_exposure + size, 2),
            consecutive_losses=state.consecutive_losses,
            consecutive_wins=state.consecutive_wins,
        )

    def close_position(
        self,
        state: PositionSizingState,
        pnl: float,
        closed_size: float,
    ) -> PositionSizingState:
        new_balance = round(state.current_balance + pnl, 2)
        new_open_exposure = round(max(0.0, state.open_exposure - closed_size), 2)

        if pnl > 0:
            return PositionSizingState(
                current_balance=new_balance,
                open_exposure=new_open_exposure,
                consecutive_losses=0,
                consecutive_wins=state.consecutive_wins + 1,
            )

        if pnl < 0:
            return PositionSizingState(
                current_balance=new_balance,
                open_exposure=new_open_exposure,
                consecutive_losses=state.consecutive_losses + 1,
                consecutive_wins=0,
            )

        return PositionSizingState(
            current_balance=new_balance,
            open_exposure=new_open_exposure,
            consecutive_losses=state.consecutive_losses,
            consecutive_wins=state.consecutive_wins,
        )

    def _available_exposure(self, state: PositionSizingState) -> float:
        max_exposure_value = state.current_balance * (self.config.max_exposure_pct / 100.0)
        remaining = max_exposure_value - state.open_exposure
        return max(0.0, remaining)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(value, high))

    @staticmethod
    def _kelly_fraction(
        win_rate: float,
        reward_ratio: float,
        fraction_multiplier: float,
    ) -> float:
        p = max(0.0, min(win_rate, 1.0))
        q = 1.0 - p
        b = max(reward_ratio, 1e-9)

        raw_fraction = ((p * b) - q) / b
        raw_fraction = max(0.0, raw_fraction)

        final_fraction = raw_fraction * fraction_multiplier
        return min(final_fraction, 1.0)