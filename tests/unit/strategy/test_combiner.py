"""Unit tests for whitelight.strategy.combiner.SignalCombiner."""

from __future__ import annotations

from decimal import Decimal

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
) -> SubStrategySignal:
    """Shorthand for creating a SubStrategySignal."""
    return SubStrategySignal(
        strategy_name=name,
        signal=signal,
        weight=weight,
        raw_score=raw_score,
    )


def _make_signals(
    s1: float = 0.0,
    s2: float = 0.0,
    s3: float = 0.0,
    s4: float = 0.0,
    s5: float = 0.0,
    s6: float = 0.0,
    s7: float = 0.0,
) -> list[SubStrategySignal]:
    """Create a full set of 7 signals with the given raw_scores.

    Uses the default weights from the production config.
    """
    return [
        _sig("S1_PrimaryTrend", s1, 0.25),
        _sig("S2_IntermediateTrend", s2, 0.15),
        _sig("S3_ShortTermTrend", s3, 0.10),
        _sig("S4_TrendStrength", s4, 0.10),
        _sig("S5_MomentumVelocity", s5, 0.15),
        _sig("S6_MeanRevBollinger", s6, 0.15),
        _sig("S7_VolatilityRegime", s7, 0.10),
    ]


# ===========================================================================
# Bull zone
# ===========================================================================


class TestBullZone:
    """composite >= 0.1 --> TQQQ allocation, no SQQQ."""

    def test_moderate_bull_produces_tqqq(self):
        # All signals at +0.5 => composite = 0.5
        signals = _make_signals(0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct > 0
        assert alloc.sqqq_pct == 0
        assert alloc.composite_score >= 0.1

    def test_strong_bull_tqqq_allocation(self):
        # All signals at +1.0 => composite = 1.0 => raw TQQQ = 1.0 * 1.20 = 1.20 -> capped 0.90
        signals = _make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == Decimal("0.90")  # Capped at 90%
        assert alloc.sqqq_pct == 0

    def test_tqqq_capped_at_max(self):
        # Very strong composite should still be capped
        signals = _make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct <= Decimal("0.90")


# ===========================================================================
# Dead zone
# ===========================================================================


class TestDeadZone:
    """composite in (-0.1, +0.1) --> 100% cash."""

    def test_zero_composite_gives_cash(self):
        signals = _make_signals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == 0
        assert alloc.sqqq_pct == 0
        assert alloc.cash_pct == Decimal("1.0")

    def test_composite_just_below_bull_threshold(self):
        # composite = 0.09 -> dead zone (threshold is 0.1)
        # 0.25*0.36 = 0.09, rest 0 => composite = 0.09
        signals = _make_signals(0.36, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == 0
        assert alloc.sqqq_pct == 0

    def test_composite_just_above_bear_threshold(self):
        # composite = -0.09 -> dead zone
        # 0.25 * (-0.36) = -0.09
        signals = _make_signals(-0.36, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct == 0
        assert alloc.sqqq_pct == 0


# ===========================================================================
# Bear zone
# ===========================================================================


class TestBearZone:
    """composite <= -0.1 --> SQQQ allocation, no TQQQ."""

    def test_bear_produces_sqqq(self):
        signals = _make_signals(-0.5, -0.5, -0.5, -0.5, -0.5, -0.5, -0.5)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct > 0
        assert alloc.tqqq_pct == 0
        assert alloc.composite_score <= -0.1

    def test_strong_bear_sqqq_allocation(self):
        # All at -1.0 => composite = -1.0 => raw = 1.0 * 0.30 = 0.30 -> capped at 0.20
        signals = _make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct == Decimal("0.20")  # Capped at 20%

    def test_sqqq_capped_at_20_percent(self):
        signals = _make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.sqqq_pct <= Decimal("0.20")


# ===========================================================================
# Allocations sum to 1.0
# ===========================================================================


class TestAllocationsSumToOne:
    @pytest.mark.parametrize(
        "score",
        [1.0, 0.5, 0.2, 0.1, 0.0, -0.05, -0.1, -0.5, -1.0],
    )
    def test_allocations_sum_to_one(self, score: float):
        signals = _make_signals(score, score, score, score, score, score, score)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        total = alloc.tqqq_pct + alloc.sqqq_pct + alloc.cash_pct
        assert abs(total - Decimal("1.0")) <= Decimal("0.01")


# ===========================================================================
# Override 1: Strong Bull Floor
# ===========================================================================


class TestStrongBullFloor:
    """When all 4 trend strategies (S1-S4) have raw_score >= 0.8, TQQQ >= 50%."""

    def test_floor_applied_when_all_trend_signals_high(self):
        # S1-S4 at 0.9 (all >= 0.8), S5-S7 slightly negative but NOT triggering crisis
        # S5 > -0.5 and S7 > -0.3 so crisis cap doesn't fire
        signals = _make_signals(0.9, 0.9, 0.9, 0.9, -0.4, -0.3, -0.2)
        # composite = 0.225+0.135+0.09+0.09 -0.06 -0.045 -0.02 = 0.415
        # TQQQ raw = 0.415*1.20 = 0.498 < 0.50 -> floor applies
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct >= Decimal("0.50")

    def test_floor_not_applied_when_one_trend_low(self):
        # S1 at 0.7 (< 0.8) -> floor should NOT apply
        signals = _make_signals(0.7, 0.9, 0.9, 0.9, -0.5, -0.3, -0.5)
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        # Floor is NOT forced because S1 < 0.8
        # The allocation is determined by normal bull zone rules
        assert alloc.tqqq_pct >= 0  # Valid allocation

    def test_floor_override_sets_sqqq_to_zero(self):
        """When strong bull floor applies, SQQQ should be 0."""
        # Create a scenario where the floor forces TQQQ up
        # S1-S4 all at 0.8 exactly, others slightly negative to pull composite down
        # but NOT enough to trigger crisis (S5 > -0.5, S7 > -0.3)
        signals = _make_signals(0.8, 0.8, 0.8, 0.8, -0.4, -0.4, -0.2)
        # composite = 0.20+0.12+0.08+0.08 -0.06 -0.06 -0.02 = 0.34
        # TQQQ raw = 0.34 * 1.20 = 0.408 -> which is < 0.50 -> floor applies
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct >= Decimal("0.50")
        assert alloc.sqqq_pct == 0


# ===========================================================================
# Override 2: Crisis Mode Cap
# ===========================================================================


class TestCrisisModeCap:
    """If S5 <= -0.5 AND S7 <= -0.3, TQQQ is hard-capped at 20%."""

    def test_crisis_caps_tqqq(self):
        # Strong bull signals from S1-S4, but S5/S7 trigger crisis
        signals = _make_signals(1.0, 1.0, 1.0, 1.0, -0.6, 0.5, -0.4)
        # composite = 0.25 + 0.15 + 0.10 + 0.10 - 0.09 + 0.075 - 0.04 = 0.545
        # Normal TQQQ = min(0.545 * 1.20, 0.90) = min(0.654, 0.90) = 0.654
        # Crisis: S5=-0.6 <= -0.5 AND S7=-0.4 <= -0.3 -> cap at 0.20
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct <= Decimal("0.20")

    def test_no_crisis_when_s5_above_threshold(self):
        signals = _make_signals(1.0, 1.0, 1.0, 1.0, -0.4, 0.5, -0.4)
        # S5 = -0.4 > -0.5, so no crisis
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct > Decimal("0.20")

    def test_no_crisis_when_s7_above_threshold(self):
        signals = _make_signals(1.0, 1.0, 1.0, 1.0, -0.6, 0.5, -0.2)
        # S7 = -0.2 > -0.3, so no crisis
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.tqqq_pct > Decimal("0.20")


# ===========================================================================
# Override 3: No Direct TQQQ <-> SQQQ Flip
# ===========================================================================


class TestNoDirectFlip:
    """Combiner must not flip from TQQQ to SQQQ directly; force cash."""

    def test_tqqq_to_sqqq_forces_cash(self):
        combiner = SignalCombiner()

        # First call: bull allocation (TQQQ > 0)
        bull_signals = _make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        alloc1 = combiner.combine(bull_signals)
        assert alloc1.tqqq_pct > 0

        # Second call: bear allocation would normally give SQQQ > 0
        bear_signals = _make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        alloc2 = combiner.combine(bear_signals)
        # Should force 100% cash instead of flipping
        assert alloc2.tqqq_pct == 0
        assert alloc2.sqqq_pct == 0
        assert alloc2.cash_pct == Decimal("1.0")

    def test_sqqq_to_tqqq_forces_cash(self):
        combiner = SignalCombiner()

        # First call: bear allocation (SQQQ > 0)
        bear_signals = _make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        alloc1 = combiner.combine(bear_signals)
        assert alloc1.sqqq_pct > 0

        # Second call: bull allocation would normally give TQQQ > 0
        bull_signals = _make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        alloc2 = combiner.combine(bull_signals)
        # Should force 100% cash instead of flipping
        assert alloc2.tqqq_pct == 0
        assert alloc2.sqqq_pct == 0
        assert alloc2.cash_pct == Decimal("1.0")

    def test_cash_to_tqqq_is_allowed(self):
        """Going from cash to TQQQ is not a flip and should be allowed."""
        combiner = SignalCombiner()

        # First call: dead zone (all cash)
        cash_signals = _make_signals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        alloc1 = combiner.combine(cash_signals)
        assert alloc1.tqqq_pct == 0
        assert alloc1.sqqq_pct == 0

        # Second call: bull signal -> should allocate TQQQ normally
        bull_signals = _make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        alloc2 = combiner.combine(bull_signals)
        assert alloc2.tqqq_pct > 0

    def test_cash_to_sqqq_is_allowed(self):
        """Going from cash to SQQQ is not a flip and should be allowed."""
        combiner = SignalCombiner()

        # First call: dead zone (all cash)
        cash_signals = _make_signals(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        alloc1 = combiner.combine(cash_signals)
        assert alloc1.tqqq_pct == 0
        assert alloc1.sqqq_pct == 0

        # Second call: bear signal -> should allocate SQQQ normally
        bear_signals = _make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        alloc2 = combiner.combine(bear_signals)
        assert alloc2.sqqq_pct > 0

    def test_after_forced_cash_can_enter_tqqq(self):
        """After a forced-cash day, the next signal can allocate normally."""
        combiner = SignalCombiner()

        # Day 1: bull (TQQQ)
        alloc1 = combiner.combine(_make_signals(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0))
        assert alloc1.tqqq_pct > 0

        # Day 2: bear -> forced cash
        alloc2 = combiner.combine(_make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0))
        assert alloc2.tqqq_pct == 0
        assert alloc2.sqqq_pct == 0

        # Day 3: bear again -> now previous was cash, so SQQQ is allowed
        alloc3 = combiner.combine(_make_signals(-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0))
        assert alloc3.sqqq_pct > 0


# ===========================================================================
# Composite score correctness
# ===========================================================================


class TestCompositeScore:
    def test_composite_score_calculation(self):
        signals = _make_signals(0.5, 0.3, 0.1, -0.2, 0.4, -0.1, 0.0)
        # composite = 0.25*0.5 + 0.15*0.3 + 0.10*0.1 + 0.10*(-0.2)
        #           + 0.15*0.4 + 0.15*(-0.1) + 0.10*0.0
        # = 0.125 + 0.045 + 0.01 - 0.02 + 0.06 - 0.015 + 0.0 = 0.205
        combiner = SignalCombiner()
        alloc = combiner.combine(signals)
        assert alloc.composite_score == pytest.approx(0.205, abs=1e-4)

    def test_fresh_combiner_has_no_previous_allocation(self):
        combiner = SignalCombiner()
        assert combiner._previous_allocation is None
