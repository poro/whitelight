"""Signal combiner -- volatility-targeted allocation with optional SQQQ sprints."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

from whitelight.models import SubStrategySignal, TargetAllocation

logger = logging.getLogger(__name__)


class SignalCombiner:
    """Volatility-targeted TQQQ allocation with SQQQ crash sprints.

    Primary rule (volatility targeting)
    ------------------------------------
    TQQQ weight = min(target_vol / realized_vol_20d, 1.0)

    When volatility is low the strategy goes up to 100% TQQQ (this is when
    3x leverage compounds best).  When volatility spikes the position is
    automatically reduced, protecting against leveraged decay.

    The remainder goes to cash/bonds -- the execution layer decides which.

    SQQQ sprint (optional)
    ----------------------
    During the **first 15 trading days** after NDX crosses below the 200-day
    SMA *and* realised volatility > 25%, allocate 30% to SQQQ.  This captures
    the initial leg of a crash where SQQQ outperforms cash.  After 15 days,
    SQQQ decays too fast and the strategy goes to cash/bonds instead.

    Override: no direct flip
    ------------------------
    The combiner never outputs TQQQ > 0 and SQQQ > 0 simultaneously.
    If the previous allocation had TQQQ > 0 and the new one would have
    SQQQ > 0 (or vice-versa), force 100% cash for one day.
    """

    # Volatility targeting
    TARGET_VOL = 0.20  # 20% annualised

    # SQQQ sprint parameters
    SQQQ_SPRINT_ENABLED = True
    SQQQ_SPRINT_MAX_DAYS = 15   # max days below 200 SMA to hold SQQQ
    SQQQ_SPRINT_VOL_MIN = 0.25  # min realised vol to trigger sprint
    SQQQ_SPRINT_PCT = Decimal("0.30")  # allocation when sprint is active

    # SMA look-back for bear detection
    SMA_PERIOD = 200

    def __init__(self) -> None:
        self._previous_allocation: Optional[TargetAllocation] = None
        self._days_below_sma: int = 0

    def combine(
        self,
        signals: list[SubStrategySignal],
        ndx_data: Optional[pd.DataFrame] = None,
    ) -> TargetAllocation:
        """Compute target allocation using volatility targeting.

        Parameters
        ----------
        signals:
            Sub-strategy signals (used for reporting and legacy composite score).
        ndx_data:
            NDX OHLCV DataFrame.  Used to compute realised vol and SMA.
            If ``None``, falls back to extracting vol20 from S7 metadata.
        """
        composite = sum(s.weight * s.raw_score for s in signals)

        # ---- Compute indicators ----
        vol20 = self._get_vol20(signals, ndx_data)
        below_sma, days_below = self._get_sma_status(signals, ndx_data)

        # ---- Primary: volatility-targeted TQQQ ----
        if vol20 > 0:
            raw_tqqq = self.TARGET_VOL / vol20
        else:
            raw_tqqq = 1.0  # zero vol → full allocation

        tqqq_pct = Decimal(str(round(min(raw_tqqq, 1.0), 4)))
        sqqq_pct = Decimal("0")

        # ---- SQQQ crash sprint ----
        if (
            self.SQQQ_SPRINT_ENABLED
            and below_sma
            and days_below <= self.SQQQ_SPRINT_MAX_DAYS
            and vol20 >= self.SQQQ_SPRINT_VOL_MIN
        ):
            logger.info(
                "SQQQ sprint active: %d days below SMA, vol20=%.2f",
                days_below, vol20,
            )
            sqqq_pct = self.SQQQ_SPRINT_PCT
            tqqq_pct = Decimal("0")  # no TQQQ during sprint

        # ---- Override: no direct TQQQ <-> SQQQ flip ----
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
            "Vol20 %.2f -> TQQQ %s / SQQQ %s / Cash %s  (composite %.4f)",
            vol20,
            tqqq_pct,
            sqqq_pct,
            cash_pct,
            composite,
        )

        self._previous_allocation = allocation
        return allocation

    # ------------------------------------------------------------------
    # Indicator extraction
    # ------------------------------------------------------------------

    def _get_vol20(
        self,
        signals: list[SubStrategySignal],
        ndx_data: Optional[pd.DataFrame],
    ) -> float:
        """Get 20-day realised volatility, preferring direct computation."""
        if ndx_data is not None and len(ndx_data) >= 21:
            close = ndx_data["close"] if "close" in ndx_data.columns else ndx_data.iloc[:, 3]
            vol = close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
            if not np.isnan(vol):
                return float(vol)

        # Fallback: extract from S7 metadata
        for s in signals:
            if s.strategy_name.startswith("S7_") and "vol20" in s.metadata:
                return float(s.metadata["vol20"])

        logger.warning("Could not determine vol20, defaulting to 0.20")
        return 0.20

    def _get_sma_status(
        self,
        signals: list[SubStrategySignal],
        ndx_data: Optional[pd.DataFrame],
    ) -> tuple[bool, int]:
        """Return (below_200_sma, consecutive_days_below)."""
        below_sma = False

        if ndx_data is not None and len(ndx_data) >= self.SMA_PERIOD:
            close = ndx_data["close"] if "close" in ndx_data.columns else ndx_data.iloc[:, 3]
            sma = close.rolling(self.SMA_PERIOD).mean()
            below_sma = bool(close.iloc[-1] < sma.iloc[-1])
        else:
            # Fallback: check S4 metadata for above_200
            for s in signals:
                if s.strategy_name.startswith("S4_") and "above_200" in s.metadata:
                    below_sma = not s.metadata["above_200"]
                    break

        # Track consecutive days below SMA
        if below_sma:
            self._days_below_sma += 1
        else:
            self._days_below_sma = 0

        return below_sma, self._days_below_sma
