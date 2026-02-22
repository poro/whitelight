"""Signal combiner v2 -- volatility-adaptive allocation with ATR position sizing.

Improvements over v1 combiner:
1. Volatility-adaptive signal weighting (fast signals in calm, slow in volatile)
2. ATR-based entry/exit thresholds (replace fixed vol targeting)
3. RSI confirmation filter (avoid extreme entries)
4. Trailing ATR stop loss
5. Position sizing by volatility percentile

The v2 combiner can be activated via config: strategy.combiner_version: 2
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

import numpy as np
import pandas as pd

from whitelight.models import SubStrategySignal, TargetAllocation
from whitelight.strategy.indicators import atr, atr_percentile, ema, rsi, sma

logger = logging.getLogger(__name__)


class SignalCombinerV2:
    """Volatility-adaptive TQQQ/SQQQ allocation with ATR-based risk management.

    Key differences from v1:
    - Sub-strategy weights shift based on volatility regime
    - ATR trailing stop triggers cash exit (no reversal)
    - Position size scales inversely with volatility
    - RSI filter prevents entering at extremes
    """

    # Volatility regime thresholds (ATR percentile)
    VOL_LOW = 0.30      # below this = low vol → favor fast signals
    VOL_HIGH = 0.70     # above this = high vol → favor slow signals

    # Sub-strategy weight profiles by regime
    # Keys are strategy name prefixes, values are (low_vol, mid_vol, high_vol) weights
    WEIGHT_PROFILES = {
        "S1_": (0.10, 0.20, 0.35),  # Primary trend (slow) — heavier in high vol
        "S2_": (0.15, 0.15, 0.15),  # Intermediate — stable
        "S3_": (0.25, 0.15, 0.05),  # Short-term (fast) — heavier in low vol
        "S4_": (0.10, 0.10, 0.10),  # Trend strength — stable
        "S5_": (0.20, 0.15, 0.10),  # Momentum — slightly heavier in low vol
        "S6_": (0.10, 0.15, 0.15),  # Mean reversion — slightly heavier in high vol
        "S7_": (0.10, 0.10, 0.10),  # Volatility regime — stable
    }

    # ATR trailing stop
    ATR_STOP_MULT = 2.5          # exit if price drops this many ATRs from peak

    # RSI filter
    RSI_BULL_MIN = 35
    RSI_BULL_MAX = 75
    RSI_BEAR_MIN = 25
    RSI_BEAR_MAX = 65

    # Position sizing
    MIN_POSITION_SIZE = 0.50     # never go below 50% of target
    MAX_POSITION_SIZE = 1.00

    # SQQQ sprint (inherited from v1)
    SQQQ_SPRINT_ENABLED = True
    SQQQ_SPRINT_MAX_DAYS = 15
    SQQQ_SPRINT_VOL_MIN = 0.25
    SQQQ_SPRINT_BASE_PCT = Decimal("0.30")

    # SMA for bear detection
    SMA_PERIOD = 200

    def __init__(self) -> None:
        self._previous_allocation: Optional[TargetAllocation] = None
        self._days_below_sma: int = 0
        self._peak_equity_proxy: float = 0.0
        self._trough_equity_proxy: float = float("inf")
        self._in_position: str = "cash"  # "tqqq", "sqqq", "cash"

    def combine(
        self,
        signals: list[SubStrategySignal],
        ndx_data: Optional[pd.DataFrame] = None,
    ) -> TargetAllocation:
        """Compute target allocation with v2 improvements."""

        # ---- Extract indicators from NDX data ----
        vol_pct = 0.5  # default mid
        atr_val = 0.0
        rsi_val = 50.0
        current_price = 0.0
        vol20 = 0.20

        if ndx_data is not None and len(ndx_data) >= 252:
            close = ndx_data["close"]
            high = ndx_data["high"]
            low = ndx_data["low"]
            current_price = float(close.iloc[-1])

            # ATR percentile
            vp = atr_percentile(high, low, close)
            if not np.isnan(vp.iloc[-1]):
                vol_pct = float(vp.iloc[-1])

            # Current ATR
            a = atr(high, low, close, 14)
            if not np.isnan(a.iloc[-1]):
                atr_val = float(a.iloc[-1])

            # RSI
            r = rsi(close, 14)
            if not np.isnan(r.iloc[-1]):
                rsi_val = float(r.iloc[-1])

            # Realized vol for base targeting
            vol20 = float(
                close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
            )
            if np.isnan(vol20):
                vol20 = 0.20
        elif ndx_data is not None and len(ndx_data) >= 21:
            close = ndx_data["close"]
            current_price = float(close.iloc[-1])
            vol20 = float(
                close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)
            )
            if np.isnan(vol20):
                vol20 = 0.20

        # ---- Improvement 1: Volatility-adaptive signal weighting ----
        adapted_signals = self._adapt_weights(signals, vol_pct)
        composite = sum(s.weight * s.raw_score for s in adapted_signals)

        # ---- Base allocation from composite signal ----
        # Positive composite → TQQQ, negative → SQQQ, near-zero → cash
        if composite > 0.15:
            intent = "tqqq"
        elif composite < -0.15:
            intent = "sqqq"
        else:
            intent = "cash"

        # ---- Improvement 3: RSI filter ----
        if intent == "tqqq" and not (self.RSI_BULL_MIN < rsi_val < self.RSI_BULL_MAX):
            logger.info("RSI filter: blocking TQQQ entry (RSI=%.1f)", rsi_val)
            intent = "cash"
        if intent == "sqqq" and not (self.RSI_BEAR_MIN < rsi_val < self.RSI_BEAR_MAX):
            logger.info("RSI filter: blocking SQQQ entry (RSI=%.1f)", rsi_val)
            intent = "cash"

        # ---- Improvement 4: Trailing ATR stop ----
        if current_price > 0 and atr_val > 0:
            if self._in_position == "tqqq":
                self._peak_equity_proxy = max(self._peak_equity_proxy, current_price)
                if current_price < self._peak_equity_proxy - self.ATR_STOP_MULT * atr_val:
                    logger.info(
                        "ATR trailing stop hit: price %.2f < peak %.2f - %.1f*ATR %.2f",
                        current_price, self._peak_equity_proxy, self.ATR_STOP_MULT, atr_val,
                    )
                    intent = "cash"  # stop to cash, don't reverse
            elif self._in_position == "sqqq":
                self._trough_equity_proxy = min(self._trough_equity_proxy, current_price)
                if current_price > self._trough_equity_proxy + self.ATR_STOP_MULT * atr_val:
                    logger.info("ATR trailing stop hit for SQQQ position")
                    intent = "cash"

        # ---- Volatility-targeted sizing ----
        if vol20 > 0:
            raw_size = 0.20 / vol20  # target 20% annual vol
        else:
            raw_size = 1.0
        base_size = min(raw_size, 1.0)

        # ---- Improvement 5: ATR percentile position sizing ----
        # Scale down in high vol environments
        if vol_pct > self.VOL_HIGH:
            vol_scalar = max(self.MIN_POSITION_SIZE, 1.0 - (vol_pct - self.VOL_HIGH))
        elif vol_pct < self.VOL_LOW:
            vol_scalar = self.MAX_POSITION_SIZE
        else:
            vol_scalar = 1.0 - 0.5 * (vol_pct - self.VOL_LOW) / (self.VOL_HIGH - self.VOL_LOW)
            vol_scalar = max(self.MIN_POSITION_SIZE, vol_scalar)

        position_size = Decimal(str(round(base_size * vol_scalar, 4)))
        position_size = min(position_size, Decimal("1.0"))

        # ---- SQQQ sprint override (from v1) ----
        below_sma, days_below = self._get_sma_status(signals, ndx_data)
        sprint_active = (
            self.SQQQ_SPRINT_ENABLED
            and below_sma
            and days_below <= self.SQQQ_SPRINT_MAX_DAYS
            and vol20 >= self.SQQQ_SPRINT_VOL_MIN
        )

        # ---- Final allocation ----
        tqqq_pct = Decimal("0")
        sqqq_pct = Decimal("0")

        if sprint_active:
            sqqq_pct = min(self.SQQQ_SPRINT_BASE_PCT * Decimal(str(vol_scalar)), Decimal("1.0"))
            intent = "sqqq"
        elif intent == "tqqq":
            tqqq_pct = position_size
        elif intent == "sqqq":
            sqqq_pct = position_size

        # ---- No direct flip rule ----
        if self._previous_allocation is not None:
            prev = self._previous_allocation
            if (prev.tqqq_pct > 0 and sqqq_pct > 0) or (prev.sqqq_pct > 0 and tqqq_pct > 0):
                logger.info("No-flip rule: forcing cash for 1 day")
                tqqq_pct = Decimal("0")
                sqqq_pct = Decimal("0")
                intent = "cash"

        cash_pct = Decimal("1.0") - tqqq_pct - sqqq_pct

        # Track position state
        if tqqq_pct > 0:
            if self._in_position != "tqqq":
                self._peak_equity_proxy = current_price
            self._in_position = "tqqq"
        elif sqqq_pct > 0:
            if self._in_position != "sqqq":
                self._trough_equity_proxy = current_price
            self._in_position = "sqqq"
        else:
            self._in_position = "cash"
            self._peak_equity_proxy = 0.0
            self._trough_equity_proxy = float("inf")

        allocation = TargetAllocation(
            tqqq_pct=tqqq_pct,
            sqqq_pct=sqqq_pct,
            cash_pct=cash_pct,
            signals=list(adapted_signals),
            composite_score=round(composite, 6),
        )

        logger.info(
            "v2: vol_pct=%.2f rsi=%.1f atr=%.2f → %s size=%s (TQQQ %s / SQQQ %s / Cash %s) composite=%.4f",
            vol_pct, rsi_val, atr_val, intent, position_size,
            tqqq_pct, sqqq_pct, cash_pct, composite,
        )

        self._previous_allocation = allocation
        return allocation

    def _adapt_weights(
        self, signals: list[SubStrategySignal], vol_pct: float,
    ) -> list[SubStrategySignal]:
        """Re-weight signals based on volatility regime."""
        adapted = []
        for s in signals:
            # Find matching weight profile
            new_weight = s.weight
            for prefix, (low_w, mid_w, high_w) in self.WEIGHT_PROFILES.items():
                if s.strategy_name.startswith(prefix):
                    if vol_pct < self.VOL_LOW:
                        new_weight = low_w
                    elif vol_pct > self.VOL_HIGH:
                        new_weight = high_w
                    else:
                        # Linear interpolation
                        t = (vol_pct - self.VOL_LOW) / (self.VOL_HIGH - self.VOL_LOW)
                        new_weight = low_w + t * (mid_w - low_w) if t < 0.5 else mid_w + (t - 0.5) * 2 * (high_w - mid_w)
                    break

            adapted.append(SubStrategySignal(
                strategy_name=s.strategy_name,
                signal=s.signal,
                weight=new_weight,
                raw_score=s.raw_score,
                metadata=s.metadata,
            ))

        # Normalize weights to sum to 1.0
        total = sum(s.weight for s in adapted)
        if total > 0 and abs(total - 1.0) > 0.01:
            adapted = [
                SubStrategySignal(
                    strategy_name=s.strategy_name,
                    signal=s.signal,
                    weight=s.weight / total,
                    raw_score=s.raw_score,
                    metadata=s.metadata,
                )
                for s in adapted
            ]

        return adapted

    def _get_sma_status(
        self,
        signals: list[SubStrategySignal],
        ndx_data: Optional[pd.DataFrame],
    ) -> tuple[bool, int]:
        """Return (below_200_sma, consecutive_days_below)."""
        below_sma = False

        if ndx_data is not None and len(ndx_data) >= self.SMA_PERIOD:
            close = ndx_data["close"]
            sma_val = sma(close, self.SMA_PERIOD)
            below_sma = bool(close.iloc[-1] < sma_val.iloc[-1])
        else:
            for s in signals:
                if s.strategy_name.startswith("S4_") and "above_200" in s.metadata:
                    below_sma = not s.metadata["above_200"]
                    break

        if below_sma:
            self._days_below_sma += 1
        else:
            self._days_below_sma = 0

        return below_sma, self._days_below_sma
