"""Abstract base class for all White Light sub-strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from whitelight.models import SubStrategySignal


class SubStrategy(ABC):
    """A single sub-strategy that produces a signal from NDX price data.

    Each sub-strategy examines a different facet of market structure (trend,
    momentum, mean-reversion, volatility regime, etc.) and emits a
    :class:`SubStrategySignal` with a continuous ``raw_score`` in [-1.0, +1.0]
    and a discrete :class:`SignalStrength`.

    Parameters
    ----------
    weight:
        Ensemble weight for this strategy (all weights should sum to ~1.0).
        If not provided, uses the subclass default.
    """

    #: Default weight -- subclasses should override this.
    DEFAULT_WEIGHT: float = 0.0

    def __init__(self, weight: float | None = None) -> None:
        self._weight = weight if weight is not None else self.DEFAULT_WEIGHT

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier for this sub-strategy."""
        ...

    @property
    def weight(self) -> float:
        """Weight used when combining signals (should sum to 1.0 across all)."""
        return self._weight

    @abstractmethod
    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        """Evaluate the strategy on the given price history.

        Returns a ``SubStrategySignal`` describing the current market stance.
        """
        ...
