"""S7 -- Volatility Regime sub-strategy.

Compares 20-day and 60-day realized volatility (vol_ratio) to classify the
current volatility regime, then filters by the 100-day SMA trend.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import realized_volatility, sma


class S7VolatilityRegime(SubStrategy):
    """Volatility Regime (20d / 60d vol ratio + 100 SMA)."""

    DEFAULT_WEIGHT = 0.10

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S7_VolatilityRegime"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]

        vol20 = realized_volatility(close, 20)
        vol60 = realized_volatility(close, 60)
        sma100 = sma(close, 100)

        last_vol20 = float(vol20.iloc[-1])
        last_vol60 = float(vol60.iloc[-1])
        last_close = float(close.iloc[-1])
        last_sma100 = float(sma100.iloc[-1])

        vol_ratio = last_vol20 / last_vol60 if last_vol60 != 0 else 1.0
        bullish = last_close > last_sma100

        # Extreme volatility override
        if vol_ratio > 2.0:
            raw_score = -0.3
            signal = SignalStrength.BEAR
        elif vol_ratio > 1.5 and not bullish:
            raw_score = -0.5
            signal = SignalStrength.BEAR
        elif vol_ratio > 1.5 and bullish:
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        elif 0.8 <= vol_ratio <= 1.2 and bullish:
            raw_score = 0.5
            signal = SignalStrength.BULL
        elif vol_ratio < 0.8 and bullish:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif vol_ratio < 0.8 and not bullish:
            raw_score = -0.2
            signal = SignalStrength.BEAR
        else:
            # Catch-all for remaining zones (e.g. 0.8-1.2 bearish, 1.2-1.5)
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "vol20": round(last_vol20, 4),
                "vol60": round(last_vol60, 4),
                "vol_ratio": round(vol_ratio, 4),
                "sma100": round(last_sma100, 2),
                "bullish": bullish,
            },
        )
