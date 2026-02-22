"""Unit tests for whitelight.execution.reconciler.check_rebalance_needed."""

from __future__ import annotations

from decimal import Decimal

import pytest

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    PortfolioSnapshot,
    Position,
    SubStrategySignal,
    TargetAllocation,
    SignalStrength,
)
from whitelight.execution.reconciler import check_rebalance_needed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(
    equity: Decimal = Decimal("100000"),
    cash: Decimal = Decimal("70000"),
    positions_by_symbol: dict[str, Decimal] | None = None,
) -> PortfolioSnapshot:
    """Create a minimal PortfolioSnapshot."""
    if positions_by_symbol is None:
        positions_by_symbol = {}
    return PortfolioSnapshot(
        accounts=[
            AccountInfo(
                brokerage=BrokerageID.PAPER,
                equity=equity,
                cash=cash,
                buying_power=cash,
            )
        ],
        positions=[],
        total_equity=equity,
        total_cash=cash,
        positions_by_symbol=positions_by_symbol,
    )


def _target(
    tqqq_pct: Decimal = Decimal("0"),
    sqqq_pct: Decimal = Decimal("0"),
) -> TargetAllocation:
    """Create a minimal TargetAllocation."""
    cash_pct = Decimal("1.0") - tqqq_pct - sqqq_pct
    return TargetAllocation(
        tqqq_pct=tqqq_pct,
        sqqq_pct=sqqq_pct,
        cash_pct=cash_pct,
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestCheckRebalanceNeeded:
    def test_returns_true_when_delta_exceeds_threshold(self):
        """TQQQ: current 0% vs target 30% -> delta 30% > 5%."""
        snap = _snapshot(positions_by_symbol={})
        target = _target(tqqq_pct=Decimal("0.30"))
        assert check_rebalance_needed(snap, target, threshold=0.05) is True

    def test_returns_false_when_within_threshold(self):
        """TQQQ: current ~30% vs target 30% -> delta ~0% < 5%."""
        snap = _snapshot(
            equity=Decimal("100000"),
            positions_by_symbol={"TQQQ": Decimal("30000")},
        )
        target = _target(tqqq_pct=Decimal("0.30"))
        assert check_rebalance_needed(snap, target, threshold=0.05) is False

    def test_handles_zero_equity(self):
        """Zero equity should return False (cannot divide)."""
        snap = _snapshot(equity=Decimal("0"), cash=Decimal("0"))
        target = _target(tqqq_pct=Decimal("0.50"))
        assert check_rebalance_needed(snap, target, threshold=0.05) is False

    def test_sqqq_delta_triggers_rebalance(self):
        """Check SQQQ position is also evaluated."""
        snap = _snapshot(
            equity=Decimal("100000"),
            positions_by_symbol={"SQQQ": Decimal("5000")},
        )
        # Current SQQQ = 5000/100000 = 5%, target = 20% -> delta = 15% > 5%
        target = _target(sqqq_pct=Decimal("0.20"))
        assert check_rebalance_needed(snap, target, threshold=0.05) is True

    def test_small_delta_returns_false(self):
        """Both TQQQ and SQQQ deltas below threshold."""
        snap = _snapshot(
            equity=Decimal("100000"),
            positions_by_symbol={"TQQQ": Decimal("29000")},
        )
        # Current TQQQ pct = 29000/100000 = 0.29, target = 0.30 -> delta = 0.01 < 0.05
        target = _target(tqqq_pct=Decimal("0.30"))
        assert check_rebalance_needed(snap, target, threshold=0.05) is False

    def test_custom_threshold(self):
        """A stricter threshold should trigger rebalance on smaller deltas."""
        snap = _snapshot(
            equity=Decimal("100000"),
            positions_by_symbol={"TQQQ": Decimal("28000")},
        )
        # Delta = |0.30 - 0.28| = 0.02
        target = _target(tqqq_pct=Decimal("0.30"))
        # With threshold=0.01 -> 0.02 >= 0.01 -> True
        assert check_rebalance_needed(snap, target, threshold=0.01) is True
        # With threshold=0.05 -> 0.02 < 0.05 -> False
        assert check_rebalance_needed(snap, target, threshold=0.05) is False

    def test_no_positions_vs_cash_target_no_rebalance(self):
        """If target is 100% cash and we hold 100% cash, no rebalance needed."""
        snap = _snapshot(
            equity=Decimal("100000"),
            positions_by_symbol={},
        )
        target = _target()  # All cash
        assert check_rebalance_needed(snap, target, threshold=0.05) is False

    def test_uses_mock_portfolio_fixture(self, mock_portfolio_snapshot):
        """Use the conftest fixture to verify integration."""
        # mock_portfolio_snapshot has TQQQ qty=500, positions_by_symbol={"TQQQ": 500}
        # But positions_by_symbol stores qty, not market_value.
        # The reconciler computes current_pct = positions_by_symbol[sym] / total_equity
        # = 500 / 100000 = 0.005 (0.5%)
        # Target TQQQ at 40% -> delta = 0.395 -> rebalance needed
        target = _target(tqqq_pct=Decimal("0.40"))
        result = check_rebalance_needed(mock_portfolio_snapshot, target, threshold=0.05)
        assert result is True
