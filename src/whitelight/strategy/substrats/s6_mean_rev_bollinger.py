"""S6 -- Bollinger Mean Reversion sub-strategy.

Uses the 20-day Bollinger Band %B indicator to detect overbought/oversold
conditions, filtered by the 200-day SMA macro trend.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import bollinger_bands, sma


class S6MeanRevBollinger(SubStrategy):
    """Bollinger Mean Reversion (%B + 200 SMA filter)."""

    DEFAULT_WEIGHT = 0.15

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S6_MeanRevBollinger"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]

        _, _, pct_b = bollinger_bands(close, period=20, std_mult=2.0)
        sma200 = sma(close, 200)

        last_pctb = float(pct_b.iloc[-1])
        last_close = float(close.iloc[-1])
        last_sma200 = float(sma200.iloc[-1])

        macro_bullish = last_close > last_sma200

        # Determine signal based on %B and macro trend
        if last_pctb < 0.05:
            # Extreme crash -- tactical bounce trade regardless of trend
            raw_score = 0.5
            signal = SignalStrength.BULL
        elif last_pctb < 0.2 and macro_bullish:
            # Oversold in a bull trend -> buy the dip
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif last_pctb < 0.2 and not macro_bullish:
            # Oversold in a bear trend -> don't catch the knife
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        elif 0.2 <= last_pctb <= 0.5 and not macro_bullish:
            raw_score = -0.5
            signal = SignalStrength.BEAR
        elif 0.3 <= last_pctb <= 0.8 and macro_bullish:
            raw_score = 0.8
            signal = SignalStrength.BULL
        elif last_pctb > 0.95 and macro_bullish:
            # Overbought but trending up -- mildly bullish
            raw_score = 0.3
            signal = SignalStrength.BULL
        elif last_pctb > 0.95 and not macro_bullish:
            # Overbought in a bear trend -- fade the rally
            raw_score = -0.3
            signal = SignalStrength.BEAR
        else:
            # Catch-all: moderate range, no strong view
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "pct_b": round(last_pctb, 4),
                "sma200": round(last_sma200, 2),
                "macro_bullish": macro_bullish,
            },
        )
