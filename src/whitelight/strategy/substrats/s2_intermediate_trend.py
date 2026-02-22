"""S2 -- Intermediate Trend sub-strategy.

Uses the 20-day and 100-day SMA to assess the intermediate-term trend.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import sma


class S2IntermediateTrend(SubStrategy):
    """Intermediate Trend (20 / 100 SMA)."""

    DEFAULT_WEIGHT = 0.15

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S2_IntermediateTrend"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]
        sma20 = sma(close, 20)
        sma100 = sma(close, 100)

        last_close = float(close.iloc[-1])
        last_sma20 = float(sma20.iloc[-1])
        last_sma100 = float(sma100.iloc[-1])

        above_20 = last_close > last_sma20
        sma20_above_100 = last_sma20 > last_sma100

        if above_20 and sma20_above_100:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif above_20 and not sma20_above_100:
            raw_score = 0.3
            signal = SignalStrength.BULL
        elif not above_20 and sma20_above_100:
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        else:  # below 20 AND 20 < 100
            raw_score = -0.5
            signal = SignalStrength.BEAR

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "sma20": round(last_sma20, 2),
                "sma100": round(last_sma100, 2),
                "above_20": above_20,
                "sma20_above_100": sma20_above_100,
            },
        )
