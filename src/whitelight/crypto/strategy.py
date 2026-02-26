"""Crypto strategy — adapts the 7 White Light sub-strategies for 4-hour timeframes.

Since the equity sub-strategies use daily bars with lookback periods calibrated
for ~252 trading days/year, the crypto adaptation scales periods for 4h bars
(6 bars/day × 365 days = ~2190 bars/year).

The strategy produces a composite score in [-1, +1] and a target allocation
with volatility targeting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from whitelight.strategy.indicators import (
    sma, roc, rsi, bollinger_bands, realized_volatility,
    linear_regression_slope, zscore,
)

logger = logging.getLogger(__name__)

# Scale factor: 6 bars per day (4h candles, crypto trades 24/7)
BARS_PER_DAY = 6
ANNUALIZATION_FACTOR = np.sqrt(BARS_PER_DAY * 365)


@dataclass
class CryptoSignal:
    """Output of the crypto strategy."""
    symbol: str
    composite_score: float
    target_allocation: float  # 0.0 to 1.0 (fraction of base allocation)
    signal_details: dict
    realized_vol: float


class CryptoStrategy:
    """7 sub-strategy ensemble adapted for 4h crypto data.

    Parameters
    ----------
    target_vol : float
        Target annualized volatility for position sizing. Default 0.15 (15%).
    bull_threshold : float
        Composite score above which to go long.
    bear_threshold : float
        Composite score below which to go flat (no shorting crypto).
    """

    def __init__(
        self,
        target_vol: float = 0.15,
        bull_threshold: float = 0.15,
        bear_threshold: float = -0.10,
    ):
        self.target_vol = target_vol
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold

    def evaluate(self, df: pd.DataFrame, symbol: str = "BTC/USD") -> CryptoSignal:
        """Run all sub-strategies on 4h OHLCV data and return a CryptoSignal.

        Parameters
        ----------
        df : pd.DataFrame
            Must have columns: open, high, low, close, volume.
            Should have at least 1500 bars (~250 days of 4h data).
        symbol : str
            Symbol name for logging.
        """
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        signals = {}

        # S1: Primary Trend (50d→300bar / 250d→1500bar SMA)
        sma_fast = sma(close, 300)
        sma_slow = sma(close, 1500)
        if pd.notna(sma_fast.iloc[-1]) and pd.notna(sma_slow.iloc[-1]):
            above_fast = close.iloc[-1] > sma_fast.iloc[-1]
            above_slow = close.iloc[-1] > sma_slow.iloc[-1]
            if above_fast and above_slow:
                s1 = 1.0
            elif above_slow:
                s1 = 0.3
            elif above_fast:
                s1 = 0.1
            else:
                s1 = -0.5
        else:
            s1 = 0.0
        signals["s1_primary_trend"] = s1

        # S2: Intermediate Trend (20d→120bar / 100d→600bar)
        sma_20 = sma(close, 120)
        sma_100 = sma(close, 600)
        if pd.notna(sma_20.iloc[-1]) and pd.notna(sma_100.iloc[-1]):
            above_20 = close.iloc[-1] > sma_20.iloc[-1]
            above_100 = close.iloc[-1] > sma_100.iloc[-1]
            if above_20 and above_100:
                s2 = 0.8
            elif above_100:
                s2 = 0.2
            elif above_20:
                s2 = 0.0
            else:
                s2 = -0.5
        else:
            s2 = 0.0
        signals["s2_intermediate_trend"] = s2

        # S3: Short-Term Trend (10d→60bar / 30d→180bar)
        sma_10 = sma(close, 60)
        sma_30 = sma(close, 180)
        if pd.notna(sma_10.iloc[-1]) and pd.notna(sma_30.iloc[-1]):
            above_10 = close.iloc[-1] > sma_10.iloc[-1]
            above_30 = close.iloc[-1] > sma_30.iloc[-1]
            if above_10 and above_30:
                s3 = 0.7
            elif above_30:
                s3 = 0.1
            elif above_10:
                s3 = -0.1
            else:
                s3 = -0.5
        else:
            s3 = 0.0
        signals["s3_short_term_trend"] = s3

        # S4: Trend Strength (regression slope z-score, 60d→360bar, z over 252d→1512bar)
        slope = linear_regression_slope(close, 360)
        if pd.notna(slope.iloc[-1]):
            z = zscore(slope, 1512)
            z_val = z.iloc[-1] if pd.notna(z.iloc[-1]) else 0.0
            z_val = float(z_val)
            s4 = max(-1.0, min(1.0, z_val / 2.0))
        else:
            s4 = 0.0
        signals["s4_trend_strength"] = s4

        # S5: Momentum Velocity (14d→84bar ROC, 3d→18bar smooth)
        roc_14 = roc(close, 84)
        roc_smooth = sma(roc_14, 18)
        if pd.notna(roc_smooth.iloc[-1]):
            velocity = roc_smooth.diff().iloc[-1]
            if pd.notna(velocity):
                s5 = max(-1.0, min(1.0, float(velocity) / 5.0))
            else:
                s5 = 0.0
            # Crash penalty: 5d→30bar ROC
            roc_5 = roc(close, 30)
            if pd.notna(roc_5.iloc[-1]) and float(roc_5.iloc[-1]) < -10.0:
                s5 = max(-1.0, s5 - 0.3)
        else:
            s5 = 0.0
        signals["s5_momentum_velocity"] = s5

        # S6: Mean Reversion Bollinger (20d→120bar, 200d→1200bar filter)
        _, _, pct_b = bollinger_bands(close, 120, 2.0)
        sma_200 = sma(close, 1200)
        if pd.notna(pct_b.iloc[-1]) and pd.notna(sma_200.iloc[-1]):
            b = float(pct_b.iloc[-1])
            in_uptrend = close.iloc[-1] > sma_200.iloc[-1]
            if in_uptrend:
                if b < 0.2:
                    s6 = 0.8  # oversold in uptrend = buy
                elif b > 0.8:
                    s6 = -0.2  # overbought in uptrend = mild caution
                else:
                    s6 = 0.3
            else:
                if b < 0.2:
                    s6 = 0.2  # oversold in downtrend = slight buy
                elif b > 0.8:
                    s6 = -0.6  # overbought in downtrend = sell
                else:
                    s6 = -0.2
        else:
            s6 = 0.0
        signals["s6_mean_rev_bollinger"] = s6

        # S7: Volatility Regime (20d→120bar / 60d→360bar vol ratio)
        vol_short = realized_volatility(close, 120)
        vol_long = realized_volatility(close, 360)
        if pd.notna(vol_short.iloc[-1]) and pd.notna(vol_long.iloc[-1]) and float(vol_long.iloc[-1]) > 0:
            vol_ratio = float(vol_short.iloc[-1]) / float(vol_long.iloc[-1])
            sma_filter = sma(close, 600)
            in_uptrend = pd.notna(sma_filter.iloc[-1]) and close.iloc[-1] > sma_filter.iloc[-1]
            if vol_ratio < 0.8:
                s7 = 0.5 if in_uptrend else 0.0  # low vol
            elif vol_ratio > 1.3:
                s7 = -0.5 if not in_uptrend else -0.2  # high vol
            else:
                s7 = 0.2 if in_uptrend else -0.1
        else:
            s7 = 0.0
        signals["s7_volatility_regime"] = s7

        # Composite (same weights as equity strategy)
        weights = {
            "s1_primary_trend": 0.25,
            "s2_intermediate_trend": 0.15,
            "s3_short_term_trend": 0.10,
            "s4_trend_strength": 0.10,
            "s5_momentum_velocity": 0.15,
            "s6_mean_rev_bollinger": 0.15,
            "s7_volatility_regime": 0.10,
        }
        composite = sum(weights[k] * signals[k] for k in weights)

        # Realized vol for position sizing (annualized from 4h returns)
        returns_4h = close.pct_change().dropna()
        if len(returns_4h) >= 120:
            realized_vol = float(returns_4h.tail(120).std()) * ANNUALIZATION_FACTOR
        else:
            realized_vol = 0.50  # default high vol for crypto

        # Target allocation via vol targeting
        if composite >= self.bull_threshold and realized_vol > 0:
            raw_alloc = self.target_vol / realized_vol
            target_alloc = min(raw_alloc, 1.0)
        elif composite <= self.bear_threshold:
            target_alloc = 0.0
        else:
            target_alloc = 0.0

        logger.info(
            "[%s] composite=%.4f realized_vol=%.2f target_alloc=%.2f",
            symbol, composite, realized_vol, target_alloc,
        )

        return CryptoSignal(
            symbol=symbol,
            composite_score=round(composite, 6),
            target_allocation=round(target_alloc, 4),
            signal_details=signals,
            realized_vol=round(realized_vol, 4),
        )
