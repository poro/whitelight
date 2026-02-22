"""S5 -- Momentum Velocity sub-strategy.

Examines the 14-day Rate of Change smoothed with a 3-day SMA, then derives
its first derivative (velocity) to distinguish accelerating from decelerating
momentum.  A sharp 5-day drawdown adds a bearish penalty.
"""

from __future__ import annotations

import pandas as pd

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.indicators import roc, sma


class S5MomentumVelocity(SubStrategy):
    """Momentum Velocity (ROC + first derivative)."""

    DEFAULT_WEIGHT = 0.15
    CRASH_ROC_THRESHOLD = -5.0   # 5-day ROC below this triggers penalty
    CRASH_PENALTY = -0.2

    def __init__(self, weight: float | None = None, **kwargs: object) -> None:
        super().__init__(weight=weight)

    @property
    def name(self) -> str:
        return "S5_MomentumVelocity"

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        close = ndx_data["close"]

        roc14 = roc(close, 14)
        smoothed = sma(roc14, 3)

        # First derivative of smoothed ROC (day-over-day change)
        velocity = smoothed.diff()

        last_roc = float(smoothed.iloc[-1])
        last_vel = float(velocity.iloc[-1])

        if last_roc > 0 and last_vel > 0:
            raw_score = 1.0
            signal = SignalStrength.STRONG_BULL
        elif last_roc > 0 and last_vel <= 0:
            raw_score = 0.3
            signal = SignalStrength.BULL
        elif last_roc <= 0 and last_vel > 0:
            raw_score = 0.0
            signal = SignalStrength.NEUTRAL
        else:  # roc <= 0 and velocity <= 0
            raw_score = -0.7
            signal = SignalStrength.BEAR

        # 5-day crash penalty
        roc5 = roc(close, 5)
        last_roc5 = float(roc5.iloc[-1])
        crash_applied = False
        if last_roc5 < self.CRASH_ROC_THRESHOLD:
            raw_score = max(raw_score + self.CRASH_PENALTY, -1.0)
            crash_applied = True
            # Downgrade signal if it was neutral or above
            if raw_score <= -0.5:
                signal = SignalStrength.STRONG_BEAR
            elif raw_score < 0:
                signal = SignalStrength.BEAR

        return SubStrategySignal(
            strategy_name=self.name,
            signal=signal,
            weight=self.weight,
            raw_score=raw_score,
            metadata={
                "smoothed_roc14": round(last_roc, 4),
                "velocity": round(last_vel, 4),
                "roc5": round(last_roc5, 4),
                "crash_penalty_applied": crash_applied,
            },
        )
