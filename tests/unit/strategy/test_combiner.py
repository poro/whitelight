"""Unit tests for whitelight.strategy.combiner.SignalCombiner (vol-targeting)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from whitelight.models import SignalStrength, SubStrategySignal, TargetAllocation
from whitelight.strategy.combiner import SignalCombiner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sig(
    name: str,
    raw_score: float,
    weight: float = 0.15,
    signal: SignalStrength = SignalStrength.NEUTRAL,
    metadata: dict | None = None,
) -> SubStrategySignal:
    return SubStrategySignal(
        strategy_name=name,
        signal=signal,
        weight=weight,
        raw_score=raw_score,
        metadata=metadata or {},
    )


def _make_signals(
    s1: float = 0.0,
    s2: float = 0.0,
    s3: float = 0.0,
    s4: float = 0.0,
    s5: float = 0.0,
    s6: float = 0.0,
    s7: float = 0.0,
    vol20: float = 0.20,
    above_200: bool = True,
) -> list[SubStrategySignal]:
    """Create a full set of 7 signals with the given raw_scores."""
    return [
        _sig("S1_PrimaryTrend", s1, 0.25),
        _sig("S2_IntermediateTrend", s2, 0.15),
        _sig("S3_ShortTermTrend", s3, 0.10),
        _sig("S4_TrendStrength", s4, 0.10, metadata={"above_200": above_200, "sma200": 100}),
        _sig("S5_MomentumVelocity", s5, 0.15),
        _sig("S6_MeanRevBollinger", s6, 0.15),
        _sig("S7_VolatilityRegime", s7, 0.10, metadata={"vol20": vol20, "vol60": 0.15}),
    ]


def _make_ndx(n_days: int = 300, base: float = 20000.0, vol: float = 0.01) -> pd.DataFrame:
    """Create a synthetic NDX DataFrame with controllable volatility."""
    np.random.seed(42)
    dates = pd.bdate_range(end="2026-02-20", periods=n_days)
    returns = np.random.normal(0.0003, vol, n_days)
    prices = base * np.cumprod(1 + returns)
    return pd.DataFrame({
        "date": dates,
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": np.random.randint(1e8, 2e8, n_days),
    })


# ===========================================================================
# Volatility Targeting (core logic)
# ===========================================================================


class TestVolTargeting:
    """TQQQ weight = min(target_vol / realized_vol, 1.0)."""

    def test_low_vol_full_tqqq(self):
        """When vol20 < target_vol (20%), TQQQ should be 100%."""
        signals = _make_signals(vol20=0.15)  # 15% vol < 20% target
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == Decimal("1.0")
        assert alloc.sqqq_pct == 0
        assert alloc.cash_pct == Decimal("0")

    def test_matching_vol_full_tqqq(self):
        """When vol20 == target_vol, TQQQ should be 100%."""
        signals = _make_signals(vol20=0.20)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == Decimal("1.0")

    def test_high_vol_reduces_tqqq(self):
        """When vol20 > target_vol, TQQQ should be reduced proportionally."""
        signals = _make_signals(vol20=0.40)  # 40% vol -> 20/40 = 50%
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == Decimal("0.5")
        assert alloc.cash_pct == Decimal("0.5")

    def test_very_high_vol_minimal_tqqq(self):
        """Extreme volatility should result in minimal TQQQ."""
        signals = _make_signals(vol20=1.0)  # 100% vol -> 20/100 = 20%
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == Decimal("0.2")
        assert alloc.cash_pct == Decimal("0.8")

    def test_vol_scaling_from_ndx_data(self):
        """Combiner should compute vol20 from ndx_data when provided."""
        ndx = _make_ndx(n_days=300, vol=0.01)  # ~16% annualised
        signals = _make_signals(vol20=0.50)  # metadata says 50% but ndx_data should win
        combiner = SignalCombiner()
        alloc = combiner.combine(signals, ndx_data=ndx)
        # Should use ndx_data vol (~16%), not metadata vol (50%)
        # At 16% vol -> 20/16 > 1.0 -> capped at 100%
        assert alloc.tqqq_pct >= Decimal("0.9")  # near full

    def test_vol_fallback_to_s7_metadata(self):
        """When ndx_data is None, falls back to S7 metadata."""
        signals = _make_signals(vol20=0.40)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals, ndx_data=None)
        assert alloc.tqqq_pct == Decimal("0.5")  # 20/40


# ===========================================================================
# Allocations sum to 1.0
# ===========================================================================


class TestAllocationsSumToOne:
    @pytest.mark.parametrize("vol20", [0.10, 0.15, 0.20, 0.30, 0.50, 0.80, 1.0])
    def test_allocations_sum_to_one(self, vol20: float):
        signals = _make_signals(vol20=vol20)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        total = alloc.tqqq_pct + alloc.sqqq_pct + alloc.cash_pct
        assert abs(total - Decimal("1.0")) <= Decimal("0.01")


# ===========================================================================
# SQQQ Sprint
# ===========================================================================


class TestSQQQSprint:
    """SQQQ sprint: 30% SQQQ during first 15 days below 200 SMA + vol > 25%."""

    def test_sprint_activates_below_sma_high_vol(self):
        """SQQQ sprint fires when below 200 SMA with high volatility."""
        signals = _make_signals(vol20=0.35, above_200=False)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct == Decimal("0.30")
        assert alloc.tqqq_pct == 0

    def test_no_sprint_above_sma(self):
        """No SQQQ sprint when above 200 SMA."""
        signals = _make_signals(vol20=0.35, above_200=True)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct == 0
        assert alloc.tqqq_pct > 0

    def test_no_sprint_low_vol(self):
        """No SQQQ sprint when vol < 25% even if below SMA."""
        signals = _make_signals(vol20=0.20, above_200=False)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct == 0
        # Vol targeting still produces TQQQ (20/20 = 100%)
        assert alloc.tqqq_pct == Decimal("1.0")

    def test_sprint_expires_after_max_days(self):
        """SQQQ sprint should stop after SQQQ_SPRINT_MAX_DAYS."""
        combiner = SignalCombiner()

        # Simulate 16 consecutive days below SMA with high vol
        for day in range(16):
            signals = _make_signals(vol20=0.35, above_200=False)
            alloc = combiner.combine(signals)

        # Day 16: days_below_sma == 16 > 15, sprint should be off
        assert alloc.sqqq_pct == 0
        # TQQQ is 0 because no-flip rule fires (previous had SQQQ, now vol-target
        # wants TQQQ). That's correct behavior -- it passes through cash first.
        assert alloc.cash_pct == Decimal("1.0")

    def test_sprint_resets_after_recovery(self):
        """Days counter resets when NDX goes back above SMA."""
        combiner = SignalCombiner()

        # 5 days below -> sprint active
        for _ in range(5):
            alloc = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc.sqqq_pct == Decimal("0.30")

        # Go above SMA for 1 day -> resets
        alloc = combiner.combine(_make_signals(vol20=0.35, above_200=True))
        assert alloc.sqqq_pct == 0

        # Back below -> day count restarts at 1
        alloc = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc.sqqq_pct == Decimal("0.30")  # sprint active again

    def test_sprint_can_be_disabled(self):
        combiner = SignalCombiner()
        combiner.SQQQ_SPRINT_ENABLED = False
        signals = _make_signals(vol20=0.35, above_200=False)
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct == 0


# ===========================================================================
# No Direct TQQQ <-> SQQQ Flip
# ===========================================================================


class TestNoDirectFlip:
    """Combiner must not flip from TQQQ to SQQQ directly; force cash."""

    def test_tqqq_to_sqqq_forces_cash(self):
        combiner = SignalCombiner()

        # Day 1: low vol, above SMA -> TQQQ
        alloc1 = combiner.combine(_make_signals(vol20=0.15, above_200=True))
        assert alloc1.tqqq_pct > 0

        # Day 2: high vol, below SMA -> would be SQQQ sprint
        alloc2 = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        # Should force cash instead of flipping
        assert alloc2.tqqq_pct == 0
        assert alloc2.sqqq_pct == 0
        assert alloc2.cash_pct == Decimal("1.0")

    def test_sqqq_to_tqqq_forces_cash(self):
        combiner = SignalCombiner()

        # Day 1: SQQQ sprint active
        alloc1 = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc1.sqqq_pct > 0

        # Day 2: back above SMA -> would be TQQQ
        alloc2 = combiner.combine(_make_signals(vol20=0.15, above_200=True))
        # Should force cash
        assert alloc2.tqqq_pct == 0
        assert alloc2.sqqq_pct == 0
        assert alloc2.cash_pct == Decimal("1.0")

    def test_cash_to_tqqq_is_allowed(self):
        combiner = SignalCombiner()

        # Day 1: SQQQ sprint
        alloc1 = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc1.sqqq_pct > 0

        # Day 2: above SMA -> would be TQQQ, but no-flip forces cash
        alloc2 = combiner.combine(_make_signals(vol20=0.15, above_200=True))
        assert alloc2.cash_pct == Decimal("1.0")

        # Day 3: previous was cash, TQQQ should now be allowed
        alloc3 = combiner.combine(_make_signals(vol20=0.15, above_200=True))
        assert alloc3.tqqq_pct > 0

    def test_after_forced_cash_sqqq_allowed(self):
        combiner = SignalCombiner()

        # Day 1: TQQQ
        alloc1 = combiner.combine(_make_signals(vol20=0.15, above_200=True))
        assert alloc1.tqqq_pct > 0

        # Day 2: would be SQQQ -> forced cash
        alloc2 = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc2.cash_pct == Decimal("1.0")

        # Day 3: SQQQ now allowed (previous was cash)
        alloc3 = combiner.combine(_make_signals(vol20=0.35, above_200=False))
        assert alloc3.sqqq_pct > 0


# ===========================================================================
# Composite score still computed for reporting
# ===========================================================================


class TestCompositeScore:
    def test_composite_score_calculation(self):
        signals = _make_signals(0.5, 0.3, 0.1, -0.2, 0.4, -0.1, 0.0)
        # composite = 0.25*0.5 + 0.15*0.3 + 0.10*0.1 + 0.10*(-0.2)
        #           + 0.15*0.4 + 0.15*(-0.1) + 0.10*0.0 = 0.205
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.composite_score == pytest.approx(0.205, abs=1e-4)

    def test_fresh_combiner_has_no_previous_allocation(self):
        combiner = SignalCombiner()
        assert combiner._previous_allocation is None
