"""Strategy engine -- orchestrates all sub-strategies and produces a target allocation."""

from __future__ import annotations

import logging

import pandas as pd

from whitelight.models import TargetAllocation
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.combiner import SignalCombiner

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Run every registered :class:`SubStrategy` and combine the results.

    Parameters
    ----------
    strategies:
        Ordered list of sub-strategies to evaluate.
    combiner:
        Signal combiner that maps weighted signals to a target allocation.
    """

    def __init__(
        self,
        strategies: list[SubStrategy],
        combiner: SignalCombiner,
    ) -> None:
        self._strategies = strategies
        self._combiner = combiner

        total_weight = sum(s.weight for s in strategies)
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(
                "Sub-strategy weights sum to %.4f (expected ~1.0)", total_weight,
            )

    def evaluate(self, ndx_data: pd.DataFrame) -> TargetAllocation:
        """Evaluate all sub-strategies against *ndx_data* and return a combined allocation.

        Parameters
        ----------
        ndx_data:
            DataFrame indexed by date with columns: open, high, low, close, volume.
            Must contain enough history for the longest look-back window (typically 252+ rows).
        """
        signals = []
        for strat in self._strategies:
            signal = strat.compute(ndx_data)
            logger.info(
                "[%s] signal=%s  raw_score=%.4f  weight=%.2f  meta=%s",
                signal.strategy_name,
                signal.signal.name,
                signal.raw_score,
                signal.weight,
                signal.metadata,
            )
            signals.append(signal)

        return self._combiner.combine(signals, ndx_data=ndx_data)
