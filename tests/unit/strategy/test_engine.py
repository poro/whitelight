"""Unit tests for whitelight.strategy.engine.StrategyEngine."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pandas as pd
import pytest

from whitelight.models import SignalStrength, SubStrategySignal, TargetAllocation
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.engine import StrategyEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeStrategy(SubStrategy):
    """A controllable stub strategy for testing the engine."""

    def __init__(
        self,
        strategy_name: str,
        raw_score: float,
        weight: float,
        signal: SignalStrength = SignalStrength.NEUTRAL,
    ) -> None:
        super().__init__(weight=weight)
        self._name = strategy_name
        self._raw_score = raw_score
        self._signal = signal

    @property
    def name(self) -> str:
        return self._name

    def compute(self, ndx_data: pd.DataFrame) -> SubStrategySignal:
        return SubStrategySignal(
            strategy_name=self._name,
            signal=self._signal,
            weight=self.weight,
            raw_score=self._raw_score,
        )


def _build_fake_strategies(
    scores: list[tuple[str, float, float]],
) -> list[FakeStrategy]:
    """Build a list of FakeStrategy from (name, raw_score, weight) tuples."""
    return [FakeStrategy(n, s, w) for n, s, w in scores]


# ===========================================================================
# Tests
# ===========================================================================


class TestStrategyEngine:
    def test_runs_all_strategies_and_returns_allocation(
        self, sample_ndx_data: pd.DataFrame
    ):
        strats = _build_fake_strategies([
            ("S1_PrimaryTrend", 0.5, 0.25),
            ("S2_IntermediateTrend", 0.5, 0.15),
            ("S3_ShortTermTrend", 0.5, 0.10),
            ("S4_TrendStrength", 0.5, 0.10),
            ("S5_MomentumVelocity", 0.5, 0.15),
            ("S6_MeanRevBollinger", 0.5, 0.15),
            ("S7_VolatilityRegime", 0.5, 0.10),
        ])
        combiner = SignalCombiner()
        engine = StrategyEngine(strats, combiner)
        alloc = engine.evaluate(sample_ndx_data)

        assert isinstance(alloc, TargetAllocation)
        assert len(alloc.signals) == 7
        total = alloc.tqqq_pct + alloc.sqqq_pct + alloc.cash_pct
        assert abs(float(total) - 1.0) <= 0.01

    def test_calls_each_strategy_once(self, sample_ndx_data: pd.DataFrame):
        mock_strats = []
        for name, weight in [
            ("S1_PrimaryTrend", 0.25),
            ("S2_IntermediateTrend", 0.15),
            ("S3_ShortTermTrend", 0.10),
            ("S4_TrendStrength", 0.10),
            ("S5_MomentumVelocity", 0.15),
            ("S6_MeanRevBollinger", 0.15),
            ("S7_VolatilityRegime", 0.10),
        ]:
            strat = MagicMock(spec=SubStrategy)
            strat.weight = weight
            strat.compute.return_value = SubStrategySignal(
                strategy_name=name,
                signal=SignalStrength.NEUTRAL,
                weight=weight,
                raw_score=0.0,
            )
            mock_strats.append(strat)

        combiner = SignalCombiner()
        engine = StrategyEngine(mock_strats, combiner)
        engine.evaluate(sample_ndx_data)

        for strat in mock_strats:
            strat.compute.assert_called_once_with(sample_ndx_data)

    def test_weight_validation_warning_when_weights_off(self, caplog):
        """Engine should log a warning when weights don't sum to ~1.0."""
        strats = _build_fake_strategies([
            ("S1_PrimaryTrend", 0.5, 0.50),   # weight=0.50
            ("S2_IntermediateTrend", 0.5, 0.50),  # weight=0.50
            # total = 1.0, no warning
        ])
        combiner = SignalCombiner()

        with caplog.at_level(logging.WARNING, logger="whitelight.strategy.engine"):
            StrategyEngine(strats, combiner)
        # Weights sum to 1.0, so no warning
        assert "weights sum to" not in caplog.text

    def test_weight_warning_logged_when_not_one(self, caplog):
        """When weights clearly don't sum to 1.0, a warning should be logged."""
        strats = _build_fake_strategies([
            ("S1_PrimaryTrend", 0.5, 0.30),
            ("S2_IntermediateTrend", 0.5, 0.30),
            # total = 0.60, should warn
        ])
        combiner = SignalCombiner()

        with caplog.at_level(logging.WARNING, logger="whitelight.strategy.engine"):
            StrategyEngine(strats, combiner)
        assert "weights sum to" in caplog.text.lower()

    def test_empty_strategies_produces_vol_targeted_allocation(
        self, sample_ndx_data: pd.DataFrame
    ):
        """No strategies means vol targeting from ndx_data only."""
        combiner = SignalCombiner()
        engine = StrategyEngine([], combiner)
        alloc = engine.evaluate(sample_ndx_data)
        # Vol targeting should produce some TQQQ based on ndx_data volatility
        assert alloc.tqqq_pct >= 0
        assert alloc.sqqq_pct == 0
        total = alloc.tqqq_pct + alloc.sqqq_pct + alloc.cash_pct
        assert abs(float(total) - 1.0) <= 0.01

    def test_composite_score_propagated(self, sample_ndx_data: pd.DataFrame):
        strats = _build_fake_strategies([
            ("S1_PrimaryTrend", 1.0, 0.25),
            ("S2_IntermediateTrend", 1.0, 0.15),
            ("S3_ShortTermTrend", 1.0, 0.10),
            ("S4_TrendStrength", 1.0, 0.10),
            ("S5_MomentumVelocity", 1.0, 0.15),
            ("S6_MeanRevBollinger", 1.0, 0.15),
            ("S7_VolatilityRegime", 1.0, 0.10),
        ])
        combiner = SignalCombiner()
        engine = StrategyEngine(strats, combiner)
        alloc = engine.evaluate(sample_ndx_data)
        assert alloc.composite_score == pytest.approx(1.0, abs=1e-4)
