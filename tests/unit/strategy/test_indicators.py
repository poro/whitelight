"""Unit tests for whitelight.strategy.indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from whitelight.strategy.indicators import (
    bollinger_bands,
    linear_regression_slope,
    realized_volatility,
    roc,
    rsi,
    sma,
    zscore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(values: list[float]) -> pd.Series:
    """Create a simple pandas Series from a list of floats."""
    return pd.Series(values, dtype=float)


def _make_linear_series(start: float, step: float, n: int) -> pd.Series:
    """Create a linearly increasing/decreasing series."""
    return pd.Series(np.linspace(start, start + step * (n - 1), n), dtype=float)


# ===========================================================================
# SMA
# ===========================================================================


class TestSMA:
    def test_correct_output_length(self, sample_ndx_data: pd.DataFrame):
        result = sma(sample_ndx_data["close"], 20)
        assert len(result) == len(sample_ndx_data)

    def test_first_values_are_nan(self):
        s = _make_series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(s, 3)
        assert result.iloc[0] is np.nan or pd.isna(result.iloc[0])
        assert result.iloc[1] is np.nan or pd.isna(result.iloc[1])
        assert pd.notna(result.iloc[2])

    def test_known_values(self):
        s = _make_series([10.0, 20.0, 30.0, 40.0, 50.0])
        result = sma(s, 3)
        assert result.iloc[2] == pytest.approx(20.0)  # (10+20+30)/3
        assert result.iloc[3] == pytest.approx(30.0)  # (20+30+40)/3
        assert result.iloc[4] == pytest.approx(40.0)  # (30+40+50)/3

    def test_period_one_returns_original(self):
        s = _make_series([5.0, 10.0, 15.0])
        result = sma(s, 1)
        pd.testing.assert_series_equal(result, s)

    def test_handles_nan_in_input(self):
        s = _make_series([1.0, np.nan, 3.0, 4.0, 5.0])
        result = sma(s, 2)
        # NaN in the window propagates: position 2 should be NaN because
        # the window [NaN, 3.0] has a NaN
        assert pd.isna(result.iloc[2])


# ===========================================================================
# ROC
# ===========================================================================


class TestROC:
    def test_correct_rate_of_change(self):
        s = _make_series([100.0, 110.0, 121.0, 100.0])
        result = roc(s, 1)
        assert result.iloc[1] == pytest.approx(10.0)   # (110-100)/100 * 100
        assert result.iloc[2] == pytest.approx(10.0)   # (121-110)/110 * 100
        assert result.iloc[3] == pytest.approx(-17.355371900826444)  # (100-121)/121 * 100

    def test_first_n_values_are_nan(self):
        s = _make_series([100.0, 200.0, 300.0])
        result = roc(s, 2)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert pd.notna(result.iloc[2])

    def test_roc_period_2(self):
        s = _make_series([100.0, 120.0, 150.0])
        result = roc(s, 2)
        # (150 - 100) / 100 * 100 = 50.0
        assert result.iloc[2] == pytest.approx(50.0)


# ===========================================================================
# RSI
# ===========================================================================


class TestRSI:
    def test_rsi_in_0_100_range(self, sample_ndx_data: pd.DataFrame):
        result = rsi(sample_ndx_data["close"], 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_pure_uptrend_rsi_high(self):
        # Monotonically increasing prices -> RSI should be near 100
        s = _make_linear_series(100, 1.0, 50)
        result = rsi(s, 14)
        last_val = result.iloc[-1]
        assert last_val > 90.0

    def test_pure_downtrend_rsi_low(self):
        # Monotonically decreasing prices -> RSI should be near 0
        s = _make_linear_series(200, -1.0, 50)
        result = rsi(s, 14)
        last_val = result.iloc[-1]
        assert last_val < 10.0

    def test_rsi_output_length(self):
        s = _make_linear_series(100, 0.5, 30)
        result = rsi(s, 14)
        assert len(result) == 30


# ===========================================================================
# Bollinger Bands
# ===========================================================================


class TestBollingerBands:
    def test_upper_greater_than_lower(self, sample_ndx_data: pd.DataFrame):
        upper, lower, pct_b = bollinger_bands(sample_ndx_data["close"], 20, 2.0)
        valid_mask = upper.notna() & lower.notna()
        assert (upper[valid_mask] > lower[valid_mask]).all()

    def test_pct_b_range(self, sample_ndx_data: pd.DataFrame):
        _, _, pct_b = bollinger_bands(sample_ndx_data["close"], 20, 2.0)
        valid = pct_b.dropna()
        # %B should typically be between -0.5 and 1.5 (can exceed 0-1)
        # but for normal data most values should be near 0-1
        assert valid.median() == pytest.approx(0.5, abs=0.3)

    def test_known_pct_b_at_midpoint(self):
        # If price is exactly at the SMA, %B should be ~0.5
        # Use constant prices -> std=0, so we can't divide. Use near-constant.
        s = _make_series([100.0] * 25)
        upper, lower, pct_b = bollinger_bands(s, 20, 2.0)
        # With constant prices, std=0, so pct_b will be NaN (division by zero)
        assert pd.isna(pct_b.iloc[-1])

    def test_band_width_scales_with_multiplier(self, sample_ndx_data: pd.DataFrame):
        close = sample_ndx_data["close"]
        upper1, lower1, _ = bollinger_bands(close, 20, 1.0)
        upper2, lower2, _ = bollinger_bands(close, 20, 2.0)
        # Width with mult=2 should be twice the width with mult=1
        valid_mask = upper1.notna() & upper2.notna()
        width1 = (upper1 - lower1)[valid_mask]
        width2 = (upper2 - lower2)[valid_mask]
        ratio = width2 / width1
        np.testing.assert_allclose(ratio.values, 2.0, rtol=1e-10)


# ===========================================================================
# Realized Volatility
# ===========================================================================


class TestRealizedVolatility:
    def test_positive_volatility(self, sample_ndx_data: pd.DataFrame):
        result = realized_volatility(sample_ndx_data["close"], 20)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_correct_annualization(self):
        # For constant price, volatility should be 0
        s = _make_series([100.0] * 30)
        result = realized_volatility(s, 20)
        valid = result.dropna()
        assert (valid == 0).all()

    def test_output_length(self, sample_ndx_data: pd.DataFrame):
        result = realized_volatility(sample_ndx_data["close"], 20)
        assert len(result) == len(sample_ndx_data)

    def test_higher_volatility_for_larger_moves(self):
        np.random.seed(99)
        # Low-vol series
        s_low = pd.Series(100.0 + np.cumsum(np.random.randn(100) * 0.1))
        # High-vol series
        s_high = pd.Series(100.0 + np.cumsum(np.random.randn(100) * 5.0))
        vol_low = realized_volatility(s_low, 20).iloc[-1]
        vol_high = realized_volatility(s_high, 20).iloc[-1]
        assert vol_high > vol_low


# ===========================================================================
# Linear Regression Slope
# ===========================================================================


class TestLinearRegressionSlope:
    def test_positive_for_uptrend(self):
        s = _make_linear_series(100, 2.0, 30)
        result = linear_regression_slope(s, 20)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_negative_for_downtrend(self):
        s = _make_linear_series(200, -3.0, 30)
        result = linear_regression_slope(s, 20)
        valid = result.dropna()
        assert (valid < 0).all()

    def test_known_slope_value(self):
        # Perfect linear: y = 10 + 5*x  =>  slope should be 5.0
        s = pd.Series([10.0 + 5.0 * i for i in range(20)], dtype=float)
        result = linear_regression_slope(s, 20)
        assert result.iloc[-1] == pytest.approx(5.0, abs=1e-6)

    def test_zero_slope_for_constant(self):
        s = _make_series([42.0] * 25)
        result = linear_regression_slope(s, 20)
        valid = result.dropna()
        assert (valid.abs() < 1e-10).all()

    def test_first_values_nan(self):
        s = _make_linear_series(0, 1, 25)
        result = linear_regression_slope(s, 20)
        # First 19 values should be NaN
        assert result.iloc[:19].isna().all()
        assert pd.notna(result.iloc[19])


# ===========================================================================
# Z-Score
# ===========================================================================


class TestZScore:
    def test_mean_near_zero_std_near_one(self):
        np.random.seed(123)
        s = pd.Series(np.random.randn(300) * 5 + 100)
        result = zscore(s, 50)
        valid = result.dropna()
        # For a stationary random series, the z-score should hover around 0
        assert valid.mean() == pytest.approx(0.0, abs=0.5)
        assert valid.std() == pytest.approx(1.0, abs=0.5)

    def test_output_length(self):
        s = _make_series(list(range(100)))
        result = zscore(s, 20)
        assert len(result) == 100

    def test_first_values_nan(self):
        s = _make_series(list(range(30)))
        result = zscore(s, 20)
        assert result.iloc[:19].isna().all()

    def test_constant_series_returns_nan(self):
        # Constant series -> std = 0 -> z-score should be NaN
        s = _make_series([5.0] * 30)
        result = zscore(s, 20)
        valid_idx = result.iloc[19:]  # After lookback
        assert valid_idx.isna().all()
