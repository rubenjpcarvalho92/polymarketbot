from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PositionSizingMode(str, Enum):
    FIXED_PERCENT = "fixed_percent"
    FIXED_AMOUNT = "fixed_amount"
    KELLY = "kelly"
    HALF_KELLY = "half_kelly"
    QUARTER_KELLY = "quarter_kelly"
    MARTINGALE = "martingale"
    ANTI_MARTINGALE = "anti_martingale"
    SIGNAL_CONFIDENCE = "signal_confidence"


@dataclass(slots=True)
class PositionSizingConfig:
    mode: PositionSizingMode = PositionSizingMode.FIXED_PERCENT
    starting_balance: float = 100.0
    min_order_size: float = 1.0
    max_order_size: float = 1000.0
    max_exposure_pct: float = 15.0

    fixed_percent: float = 5.0
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


@dataclass(slots=True)
class PositionSizingState:
    current_balance: float
    open_exposure: float = 0.0
    consecutive_losses: int = 0
    consecutive_wins: int = 0


class PositionSizer:
    def __init__(self, config: PositionSizingConfig):
        self.config = config

    def calculate_order_size(
        self,
        state: PositionSizingState,
        signal_strength: str = "medium",
        estimated_win_rate: float | None = None,
        estimated_reward_ratio: float | None = None,
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
                estimated_win_rate or self.config.kelly_win_rate,
                estimated_reward_ratio or self.config.kelly_reward_ratio,
                1.0,
            )

        elif mode == PositionSizingMode.HALF_KELLY:
            size = state.current_balance * self._kelly_fraction(
                estimated_win_rate or self.config.kelly_win_rate,
                estimated_reward_ratio or self.config.kelly_reward_ratio,
                0.5,
            )

        elif mode == PositionSizingMode.QUARTER_KELLY:
            size = state.current_balance * self._kelly_fraction(
                estimated_win_rate or self.config.kelly_win_rate,
                estimated_reward_ratio or self.config.kelly_reward_ratio,
                0.25,
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

        size = max(self.config.min_order_size, min(size, self.config.max_order_size))
        size = min(size, available_exposure, state.current_balance)

        return round(max(size, 0.0), 2)

    def _available_exposure(self, state: PositionSizingState) -> float:
        max_exposure_value = state.current_balance * (self.config.max_exposure_pct / 100.0)
        remaining = max_exposure_value - state.open_exposure
        return max(0.0, remaining)

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