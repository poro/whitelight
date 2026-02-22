"""S4 -- Trend Strength sub-strategy.

Measures the 60-day linear regression slope of NDX close, z-scored against
its own 252-day distribution, then cross-references with the 200-day SMA
to confirm the trend.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import linear_regression_slope, sma, zscore


class S4TrendStrength(SubStrategy):
    """Trend Strength (regression slope z-score)."""

    DEFAULT_WEIGHT = 0.10

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S4_TrendStrength"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]

        slope = linear_regression_slope(close, 60)
        slope_z = zscore(slope, 252)
        sma200 = sma(close, 200)

        last_slope = float(slope.iloc[-1])
        last_z = float(slope_z.iloc[-1])
        last_close = float(close.iloc[-1])
        last_sma200 = float(sma200.iloc[-1])

        above_200 = last_close > last_sma200

        if last_slope > 0 and last_z > 0.5 and above_200:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif last_slope > 0 and 0.0 <= last_z <= 0.5:
            raw_score = 0.5
            signal = SignalStrength.BULL
        elif last_slope > 0 and not above_200:
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        elif last_slope < 0 and last_z < -0.5:
            raw_score = -0.5
            signal = SignalStrength.BEAR
        elif last_slope < 0 and -0.5 <= last_z < 0:
            raw_score = -0.2
            signal = SignalStrength.BEAR
        else:
            # Edge: slope exactly 0, or z in unusual range -- default neutral
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "slope": round(last_slope, 6),
                "slope_z": round(last_z, 4),
                "sma200": round(last_sma200, 2),
                "above_200": above_200,
            },
        )
