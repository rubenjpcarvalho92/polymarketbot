from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class Signal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class StrategyResult:
    signal: Signal
    reason: str
    metadata: Dict[str, Any]


@dataclass
class CandidateMarket:
    market_id: str
    token_id: str
    question: str
    side: str
    score: float
    days_to_resolution: float
    spread: Optional[float]
    liquidity: Optional[float]
    midpoint: Optional[float]


class Trader:
    def __init__(
        self,
        switch_improvement_ratio: float = 1.25,
        force_exit_days: float = 7.0,
        hold_max_spread: float = 0.08,
        hold_min_liquidity: float = 500.0,
    ) -> None:
        self.switch_improvement_ratio = switch_improvement_ratio
        self.force_exit_days = force_exit_days
        self.hold_max_spread = hold_max_spread
        self.hold_min_liquidity = hold_min_liquidity

        self.current_market_id: Optional[str] = None
        self.current_token_id: Optional[str] = None
        self.current_market_score: float = 0.0
        self.has_open_position: bool = False

    def reset_current_market(self) -> None:
        self.current_market_id = None
        self.current_token_id = None
        self.current_market_score = 0.0

    def should_hold_market(self, market: CandidateMarket) -> bool:
        if market.days_to_resolution <= self.force_exit_days:
            return False

        if market.spread is None or market.spread > self.hold_max_spread:
            return False

        if market.liquidity is None or market.liquidity < self.hold_min_liquidity:
            return False

        return True

    def should_switch_market(self, current_market: CandidateMarket, candidate_market: CandidateMarket) -> bool:
        if candidate_market.market_id == current_market.market_id:
            return False

        if current_market.score <= 0:
            return True

        return candidate_market.score >= current_market.score * self.switch_improvement_ratio

    def select_best_market(self, markets: List[CandidateMarket]) -> Optional[CandidateMarket]:
        if not markets:
            return None
        return max(markets, key=lambda m: m.score)

    def get_current_market(self, markets: List[CandidateMarket]) -> Optional[CandidateMarket]:
        if self.current_market_id is None:
            return None

        for market in markets:
            if market.market_id == self.current_market_id:
                return market

        return None

    def choose_active_market(self, markets: List[CandidateMarket]) -> Optional[CandidateMarket]:
        best_market = self.select_best_market(markets)
        if best_market is None:
            return None

        current_market = self.get_current_market(markets)

        if current_market is None:
            self.current_market_id = best_market.market_id
            self.current_token_id = best_market.token_id
            self.current_market_score = best_market.score
            return best_market

        if not self.should_hold_market(current_market):
            self.current_market_id = best_market.market_id
            self.current_token_id = best_market.token_id
            self.current_market_score = best_market.score
            return best_market

        if self.should_switch_market(current_market, best_market):
            self.current_market_id = best_market.market_id
            self.current_token_id = best_market.token_id
            self.current_market_score = best_market.score
            return best_market

        self.current_market_score = current_market.score
        return current_market

    def evaluate_position_management(
        self,
        market: CandidateMarket,
        technical_signal: Signal,
        technical_reason: str,
    ) -> StrategyResult:
        if market.days_to_resolution <= self.force_exit_days:
            return StrategyResult(
                signal=Signal.SELL,
                reason="force_exit_near_resolution",
                metadata={
                    "market_id": market.market_id,
                    "token_id": market.token_id,
                    "days_to_resolution": market.days_to_resolution,
                },
            )

        if market.spread is None or market.spread > self.hold_max_spread:
            return StrategyResult(
                signal=Signal.SELL,
                reason="force_exit_spread_too_wide",
                metadata={
                    "market_id": market.market_id,
                    "token_id": market.token_id,
                    "spread": market.spread,
                },
            )

        if market.liquidity is None or market.liquidity < self.hold_min_liquidity:
            return StrategyResult(
                signal=Signal.SELL,
                reason="force_exit_low_liquidity",
                metadata={
                    "market_id": market.market_id,
                    "token_id": market.token_id,
                    "liquidity": market.liquidity,
                },
            )

        return StrategyResult(
            signal=technical_signal,
            reason=technical_reason,
            metadata={
                "market_id": market.market_id,
                "token_id": market.token_id,
                "score": market.score,
                "side": market.side,
                "days_to_resolution": market.days_to_resolution,
                "spread": market.spread,
                "liquidity": market.liquidity,
                "midpoint": market.midpoint,
            },
        )

    def process(
        self,
        markets: List[CandidateMarket],
        technical_signal: Signal,
        technical_reason: str,
    ) -> StrategyResult:
        active_market = self.choose_active_market(markets)

        if active_market is None:
            return StrategyResult(
                signal=Signal.HOLD,
                reason="no_valid_btc_market",
                metadata={},
            )

        return self.evaluate_position_management(
            market=active_market,
            technical_signal=technical_signal,
            technical_reason=technical_reason,
        )