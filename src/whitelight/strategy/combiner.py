"""Signal combiner -- translates sub-strategy signals into a target allocation."""

from __future__ import annotations

import logging
from decimal import Decimal

from whitelight.models import SubStrategySignal, TargetAllocation

logger = logging.getLogger(__name__)


class SignalCombiner:
    """Combine weighted sub-strategy signals into a :class:`TargetAllocation`.

    Mapping rules
    -------------
    * composite >= +0.2  --> long TQQQ, no SQQQ
    * composite in (-0.1, +0.2) --> all cash (dead zone)
    * composite <= -0.1  --> long SQQQ, no TQQQ
    """

    # Allocation caps mirror whitelight.constants but are kept here so the
    # combiner is self-contained and easily testable.
    MAX_TQQQ_PCT = Decimal("0.50")
    MAX_SQQQ_PCT = Decimal("0.30")

    BULL_THRESHOLD = 0.2
    BEAR_THRESHOLD = -0.1

    BULL_SCALE = 0.60   # score * scale -> raw tqqq pct
    BEAR_SCALE = 0.40   # |score| * scale -> raw sqqq pct

    def combine(self, signals: list[SubStrategySignal]) -> TargetAllocation:
        """Compute the composite score and derive target percentages."""
        composite = sum(s.weight * s.raw_score for s in signals)

        tqqq_pct = Decimal("0")
        sqqq_pct = Decimal("0")

        if composite >= self.BULL_THRESHOLD:
            raw = composite * self.BULL_SCALE
            tqqq_pct = min(
                Decimal(str(round(raw, 4))),
                self.MAX_TQQQ_PCT,
            )
        elif composite <= self.BEAR_THRESHOLD:
            raw = abs(composite) * self.BEAR_SCALE
            sqqq_pct = min(
                Decimal(str(round(raw, 4))),
                self.MAX_SQQQ_PCT,
            )
        # else: dead zone -- stay fully in cash

        cash_pct = Decimal("1.0") - tqqq_pct - sqqq_pct

        allocation = TargetAllocation(
            tqqq_pct=tqqq_pct,
            sqqq_pct=sqqq_pct,
            cash_pct=cash_pct,
            signals=list(signals),
            composite_score=round(composite, 6),
        )

        logger.info(
            "Composite %.4f -> TQQQ %s / SQQQ %s / Cash %s",
            composite,
            tqqq_pct,
            sqqq_pct,
            cash_pct,
        )

        return allocation
