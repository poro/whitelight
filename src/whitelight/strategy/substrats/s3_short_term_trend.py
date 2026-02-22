"""S3 -- Short-Term Trend sub-strategy.

Uses the 10-day and 30-day SMA to capture near-term directional shifts.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import sma


class S3ShortTermTrend(SubStrategy):
    """Short-Term Trend (10 / 30 SMA)."""

    DEFAULT_WEIGHT = 0.10

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S3_ShortTermTrend"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]
        sma10 = sma(close, 10)
        sma30 = sma(close, 30)

        last_close = float(close.iloc[-1])
        last_sma10 = float(sma10.iloc[-1])
        last_sma30 = float(sma30.iloc[-1])

        sma10_above_30 = last_sma10 > last_sma30
        above_sma10 = last_close > last_sma10

        if sma10_above_30 and above_sma10:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif sma10_above_30 and not above_sma10:
            raw_score = 0.5
            signal = SignalStrength.BULL
        elif not sma10_above_30 and above_sma10:
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        else:  # 10 < 30 AND price < 10
            raw_score = -0.3
            signal = SignalStrength.BEAR

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "sma10": round(last_sma10, 2),
                "sma30": round(last_sma30, 2),
                "sma10_above_30": sma10_above_30,
                "above_sma10": above_sma10,
            },
        )
