"""Shared indicator calculations for the White Light trading system.

All functions operate on pandas Series and return pandas Series, making them
composable and easy to test in isolation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def roc(series: pd.Series, period: int) -> pd.Series:
    """Rate of Change as a percentage.

    ROC = (current - N periods ago) / N periods ago * 100
    """
    return series.pct_change(periods=period) * 100.0


def rsi(series: pd.Series, period: int) -> pd.Series:
    """Relative Strength Index (Wilder smoothing).

    Returns values in [0, 100].
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def bollinger_bands(
    series: pd.Series,
    period: int,
    std_mult: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns:
        (upper_band, lower_band, pct_b) where pct_b = (price - lower) / (upper - lower).
    """
    mid = sma(series, period)
    std = series.rolling(window=period, min_periods=period).std()

    upper = mid + std_mult * std
    lower = mid - std_mult * std

    band_width = upper - lower
    pct_b = (series - lower) / band_width.replace(0, np.nan)

    return upper, lower, pct_b


def realized_volatility(series: pd.Series, period: int) -> pd.Series:
    """Annualized realized volatility from log returns.

    vol = std(log_returns, period) * sqrt(252)
    """
    log_ret = np.log(series / series.shift(1))
    return log_ret.rolling(window=period, min_periods=period).std() * np.sqrt(252)


def linear_regression_slope(series: pd.Series, period: int) -> pd.Series:
    """Rolling ordinary-least-squares slope over *period* observations.

    Uses the analytical formula for slope to avoid per-window matrix ops:
        slope = (N * sum(x*y) - sum(x)*sum(y)) / (N * sum(x^2) - sum(x)^2)
    where x = 0, 1, ..., N-1 within each window.
    """
    n = period
    # x values are constant: 0..n-1
    sum_x = n * (n - 1) / 2.0
    sum_x2 = n * (n - 1) * (2 * n - 1) / 6.0

    # Rolling sums of y and x*y
    # x_i within the window = 0, 1, ..., n-1 for the oldest..newest value.
    # We need sum(x_i * y_i).  We compute this via: sum(i * y_{t-n+1+i}) for i in 0..n-1.
    # Trick: sum(i * y_i) = sum(cumulative_y) - n * y_oldest_sum  ... but a simpler
    # approach is to use the identity:
    #   sum(i * y_i) = (n-1)*sum(y) - sum( (n-1-i)*y_i ) = (n-1)*sum(y) - sum(reversed_cum)
    # Instead, just use rolling apply for clarity and correctness at moderate period sizes.

    def _slope(window: np.ndarray) -> float:
        x = np.arange(len(window), dtype=np.float64)
        y = window.astype(np.float64)
        n_w = len(window)
        sx = x.sum()
        sy = y.sum()
        sxy = (x * y).sum()
        sx2 = (x * x).sum()
        denom = n_w * sx2 - sx * sx
        if denom == 0:
            return np.nan
        return (n_w * sxy - sx * sy) / denom

    return series.rolling(window=period, min_periods=period).apply(
        _slope, raw=True,
    )


def zscore(series: pd.Series, lookback: int) -> pd.Series:
    """Rolling z-score normalization.

    z = (x - mean(x, lookback)) / std(x, lookback)
    """
    rolling_mean = series.rolling(window=lookback, min_periods=lookback).mean()
    rolling_std = series.rolling(window=lookback, min_periods=lookback).std()
    return (series - rolling_mean) / rolling_std.replace(0, np.nan)
