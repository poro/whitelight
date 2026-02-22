"""S1 -- Primary Trend sub-strategy.

Evaluates the long-term trend using the 50-day and 250-day SMA of the NDX
close.  A hysteresis band (0.5 % beyond each SMA for 2 consecutive days)
prevents whipsaw signals near the crossover.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import sma


class S1PrimaryTrend(SubStrategy):
    """Primary Trend (50 / 250 SMA)."""

    DEFAULT_WEIGHT = 0.25
    HYSTERESIS_PCT = 0.005   # 0.5 %
    CONFIRM_DAYS = 2

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S1_PrimaryTrend"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]
        sma50 = sma(close, 50)
        sma250 = sma(close, 250)

        # Apply hysteresis: price must exceed SMA by 0.5% for 2 consecutive days
        above_50 = self._confirmed_above(close, sma50)
        below_50 = self._confirmed_below(close, sma50)
        above_250 = self._confirmed_above(close, sma250)
        below_250 = self._confirmed_below(close, sma250)

        if above_50 and above_250:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif not above_50 and above_250:
            raw_score = 0.3
            signal = SignalStrength.BULL
        elif above_50 and not above_250:
            raw_score = 0.1
            signal = SignalStrength.NEUTRAL
        else:  # below_50 and below_250
            raw_score = -0.5
            signal = SignalStrength.STRONG_BEAR

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "sma50": round(float(sma50.iloc[-1]), 2) if pd.notna(sma50.iloc[-1]) else None,
                "sma250": round(float(sma250.iloc[-1]), 2) if pd.notna(sma250.iloc[-1]) else None,
                "above_50": above_50,
                "above_250": above_250,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _confirmed_above(self, price: pd.Series, ma: pd.Series) -> bool:
        """True when the last *CONFIRM_DAYS* closes are all > SMA * (1 + hysteresis)."""
        threshold = ma * (1.0 + self.HYSTERESIS_PCT)
        tail = (price > threshold).iloc[-self.CONFIRM_DAYS :]
        return bool(tail.all())

    def _confirmed_below(self, price: pd.Series, ma: pd.Series) -> bool:
        """True when the last *CONFIRM_DAYS* closes are all < SMA * (1 - hysteresis)."""
        threshold = ma * (1.0 - self.HYSTERESIS_PCT)
        tail = (price < threshold).iloc[-self.CONFIRM_DAYS :]
        return bool(tail.all())
