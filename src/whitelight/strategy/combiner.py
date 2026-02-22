"""Signal combiner -- translates sub-strategy signals into a target allocation."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from whitelight.models import SubStrategySignal, TargetAllocation

logger = logging.getLogger(__name__)


class SignalCombiner:
    """Combine weighted sub-strategy signals into a :class:`TargetAllocation`.

    Mapping rules
    -------------
    * composite >= +0.1  --> long TQQQ up to 90%, no SQQQ
    * composite in (-0.1, +0.1) --> all cash (dead zone)
    * composite <= -0.1  --> long SQQQ up to 20%, no TQQQ

    Override rules
    --------------
    * **Strong bull floor:** If all 4 trend strategies (S1-S4) have raw_score >= +0.8,
      TQQQ allocation is floored at 50% (don't fight a strong bull).
    * **Crisis mode cap:** If S5 (momentum) <= -0.5 AND S7 (volatility) <= -0.3,
      TQQQ is hard-capped at 20% (protect against leveraged decay in crisis).
    * **No direct flip:** The combiner never outputs TQQQ > 0 and SQQQ > 0
      simultaneously. If the previous allocation had TQQQ > 0 and the new
      allocation would have SQQQ > 0 (or vice versa), force 100% cash instead.
    """

    MAX_TQQQ_PCT = Decimal("0.90")
    MAX_SQQQ_PCT = Decimal("0.20")

    BULL_THRESHOLD = 0.1
    BEAR_THRESHOLD = -0.1

    BULL_SCALE = 1.20
    BEAR_SCALE = 0.30

    # Override thresholds
    STRONG_BULL_FLOOR = Decimal("0.50")
    STRONG_BULL_SIGNAL_THRESHOLD = 0.8
    CRISIS_TQQQ_CAP = Decimal("0.20")
    CRISIS_S5_THRESHOLD = -0.5
    CRISIS_S7_THRESHOLD = -0.3

    # Strategy name prefixes used for override lookups
    _TREND_PREFIXES = ("S1_", "S2_", "S3_", "S4_")

    def __init__(self) -> None:
        self._previous_allocation: Optional[TargetAllocation] = None

    def combine(self, signals: list[SubStrategySignal]) -> TargetAllocation:
        """Compute the composite score and derive target percentages."""
        composite = sum(s.weight * s.raw_score for s in signals)

        # Build signal lookup by name prefix
        by_prefix: dict[str, SubStrategySignal] = {}
        for s in signals:
            for prefix in ("S1_", "S2_", "S3_", "S4_", "S5_", "S6_", "S7_"):
                if s.strategy_name.startswith(prefix):
                    by_prefix[prefix] = s
                    break

        # ---- Base allocation from composite score ----
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

        # ---- Override 1: Strong bull floor ----
        trend_signals = [by_prefix[p] for p in self._TREND_PREFIXES if p in by_prefix]
        if (
            len(trend_signals) == 4
            and all(s.raw_score >= self.STRONG_BULL_SIGNAL_THRESHOLD for s in trend_signals)
            and tqqq_pct < self.STRONG_BULL_FLOOR
        ):
            logger.info(
                "Override: strong bull floor applied (all trend signals >= %.1f). "
                "TQQQ raised from %s to %s",
                self.STRONG_BULL_SIGNAL_THRESHOLD,
                tqqq_pct,
                self.STRONG_BULL_FLOOR,
            )
            tqqq_pct = self.STRONG_BULL_FLOOR
            sqqq_pct = Decimal("0")

        # ---- Override 2: Crisis mode cap ----
        s5 = by_prefix.get("S5_")
        s7 = by_prefix.get("S7_")
        if (
            s5 is not None
            and s7 is not None
            and s5.raw_score <= self.CRISIS_S5_THRESHOLD
            and s7.raw_score <= self.CRISIS_S7_THRESHOLD
            and tqqq_pct > self.CRISIS_TQQQ_CAP
        ):
            logger.info(
                "Override: crisis mode cap applied (S5=%.2f, S7=%.2f). "
                "TQQQ capped from %s to %s",
                s5.raw_score,
                s7.raw_score,
                tqqq_pct,
                self.CRISIS_TQQQ_CAP,
            )
            tqqq_pct = self.CRISIS_TQQQ_CAP

        # ---- Override 3: No direct TQQQ <-> SQQQ flip ----
        if self._previous_allocation is not None:
            prev = self._previous_allocation
            flipping_long_to_short = prev.tqqq_pct > 0 and sqqq_pct > 0
            flipping_short_to_long = prev.sqqq_pct > 0 and tqqq_pct > 0
            if flipping_long_to_short or flipping_short_to_long:
                direction = "TQQQ->SQQQ" if flipping_long_to_short else "SQQQ->TQQQ"
                logger.info(
                    "Override: no direct flip (%s). Forcing 100%% cash for 1 day.",
                    direction,
                )
                tqqq_pct = Decimal("0")
                sqqq_pct = Decimal("0")

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

        self._previous_allocation = allocation
        return allocation
