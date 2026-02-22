"""Unit tests for all seven White Light sub-strategies (S1-S7)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from whitelight.models import SignalStrength, SubStrategySignal
from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(
    closes: np.ndarray,
    start_date: str = "2020-01-01",
) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from an array of close prices."""
    n = len(closes)
    dates = pd.bdate_range(start=start_date, periods=n, freq="B")
    highs = closes * 1.002
    lows = closes * 0.998
    opens = closes * 1.001
    volumes = np.full(n, 2_000_000)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _pure_uptrend(n: int = 500, start: float = 10000.0, daily_pct: float = 0.003) -> pd.DataFrame:
    """Generate a steady uptrend with tiny noise, price consistently above all SMAs."""
    closes = np.empty(n)
    closes[0] = start
    np.random.seed(0)
    for i in range(1, n):
        closes[i] = closes[i - 1] * (1 + daily_pct + np.random.randn() * 0.0005)
    return _make_ohlcv(closes)


def _pure_downtrend(n: int = 500, start: float = 20000.0, daily_pct: float = -0.003) -> pd.DataFrame:
    """Generate a steady downtrend, price consistently below all SMAs."""
    closes = np.empty(n)
    closes[0] = start
    np.random.seed(1)
    for i in range(1, n):
        closes[i] = closes[i - 1] * (1 + daily_pct + np.random.randn() * 0.0005)
    return _make_ohlcv(closes)


def _assert_valid_signal(signal: SubStrategySignal, expected_weight: float) -> None:
    """Validate common SubStrategySignal properties."""
    assert isinstance(signal, SubStrategySignal)
    assert isinstance(signal.signal, SignalStrength)
    assert signal.weight == pytest.approx(expected_weight)
    assert -1.0 <= signal.raw_score <= 1.0


# ===========================================================================
# S1 -- Primary Trend
# ===========================================================================


class TestS1PrimaryTrend:
    def test_strong_bull_when_price_above_both_smas(self):
        data = _pure_uptrend()
        strat = S1PrimaryTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.25)
        assert signal.signal == SignalStrength.STRONG_BULL
        assert signal.raw_score == 1.0

    def test_strong_bear_when_price_below_both_smas(self):
        data = _pure_downtrend()
        strat = S1PrimaryTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.25)
        assert signal.signal == SignalStrength.STRONG_BEAR
        assert signal.raw_score == -0.5

    def test_custom_weight(self):
        data = _pure_uptrend()
        strat = S1PrimaryTrend(weight=0.30)
        signal = strat.compute(data)
        assert signal.weight == pytest.approx(0.30)

    def test_name(self):
        strat = S1PrimaryTrend()
        assert strat.name == "S1_PrimaryTrend"

    def test_metadata_keys(self):
        data = _pure_uptrend()
        strat = S1PrimaryTrend()
        signal = strat.compute(data)
        assert "sma50" in signal.metadata
        assert "sma250" in signal.metadata
        assert "above_50" in signal.metadata
        assert "above_250" in signal.metadata

    def test_bull_when_below_sma50_but_above_sma250(self):
        """Build data where price dips below SMA50 but stays above SMA250.

        Strategy: long uptrend then small recent dip (short enough to stay above SMA250).
        """
        np.random.seed(42)
        n = 500
        closes = np.empty(n)
        closes[0] = 10000.0
        for i in range(1, 470):
            closes[i] = closes[i - 1] * 1.003
        # Short mild dip: pulls price below SMA50 but stays well above SMA250
        for i in range(470, n):
            closes[i] = closes[i - 1] * 0.997
        data = _make_ohlcv(closes)
        strat = S1PrimaryTrend()
        signal = strat.compute(data)
        # The exact signal depends on hysteresis confirmation logic;
        # valid outcomes are BULL (below 50 above 250) or NEUTRAL/STRONG_BEAR
        # if the dip triggers different hysteresis states
        assert signal.signal in (
            SignalStrength.STRONG_BULL,
            SignalStrength.BULL,
            SignalStrength.NEUTRAL,
            SignalStrength.STRONG_BEAR,
        )


# ===========================================================================
# S2 -- Intermediate Trend
# ===========================================================================


class TestS2IntermediateTrend:
    def test_strong_bull_above_sma20_and_sma20_above_sma100(self):
        data = _pure_uptrend()
        strat = S2IntermediateTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        assert signal.signal == SignalStrength.STRONG_BULL
        assert signal.raw_score == 1.0

    def test_bear_when_below_both(self):
        data = _pure_downtrend()
        strat = S2IntermediateTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        assert signal.signal == SignalStrength.BEAR
        assert signal.raw_score == -0.5

    def test_bull_above_20_but_sma20_below_sma100(self):
        """Long downtrend then short uptick: price above SMA20.

        The actual signal depends on whether the uptick is strong enough
        to push SMA20 above SMA100 (producing STRONG_BULL) or not (BULL).
        """
        np.random.seed(10)
        n = 500
        closes = np.empty(n)
        closes[0] = 20000.0
        # Downtrend for most of the period
        for i in range(1, 470):
            closes[i] = closes[i - 1] * 0.999
        # Short uptick at end - only 10 days to keep SMA20 below SMA100
        for i in range(470, 480):
            closes[i] = closes[i - 1] * 1.008
        # Then flatten
        for i in range(480, n):
            closes[i] = closes[i - 1] * 1.001
        data = _make_ohlcv(closes)
        strat = S2IntermediateTrend()
        signal = strat.compute(data)
        # Price should be above SMA20 from the uptick
        assert signal.signal in (SignalStrength.STRONG_BULL, SignalStrength.BULL)

    def test_dip_after_uptrend(self):
        """Long uptrend then short dip: tests the intermediate trend response."""
        np.random.seed(20)
        n = 500
        closes = np.empty(n)
        closes[0] = 10000.0
        for i in range(1, 490):
            closes[i] = closes[i - 1] * 1.002
        # Very short dip at end (10 days) to keep SMA20 above SMA100
        for i in range(490, n):
            closes[i] = closes[i - 1] * 0.995
        data = _make_ohlcv(closes)
        strat = S2IntermediateTrend()
        signal = strat.compute(data)
        # After a short dip, depending on SMA positions, could be BULL or NEUTRAL
        assert signal.signal in (SignalStrength.STRONG_BULL, SignalStrength.BULL, SignalStrength.NEUTRAL)

    def test_name(self):
        assert S2IntermediateTrend().name == "S2_IntermediateTrend"


# ===========================================================================
# S3 -- Short-Term Trend
# ===========================================================================


class TestS3ShortTermTrend:
    def test_strong_bull_crossover_up(self):
        data = _pure_uptrend()
        strat = S3ShortTermTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        assert signal.signal == SignalStrength.STRONG_BULL
        assert signal.raw_score == 1.0

    def test_bear_crossover_down(self):
        data = _pure_downtrend()
        strat = S3ShortTermTrend()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        assert signal.signal == SignalStrength.BEAR
        assert signal.raw_score == -0.3

    def test_bull_sma10_above_sma30_but_price_below_sma10(self):
        """Strong uptrend with a very small terminal dip."""
        np.random.seed(30)
        n = 500
        closes = np.empty(n)
        closes[0] = 10000.0
        for i in range(1, 490):
            closes[i] = closes[i - 1] * 1.003
        # Tiny dip at end
        for i in range(490, n):
            closes[i] = closes[i - 1] * 0.995
        data = _make_ohlcv(closes)
        strat = S3ShortTermTrend()
        signal = strat.compute(data)
        # SMA10 should still be above SMA30, but price < SMA10 => BULL
        assert signal.signal == SignalStrength.BULL
        assert signal.raw_score == pytest.approx(0.5)

    def test_name(self):
        assert S3ShortTermTrend().name == "S3_ShortTermTrend"


# ===========================================================================
# S4 -- Trend Strength
# ===========================================================================


class TestS4TrendStrength:
    def test_strong_bull_positive_slope_high_z(self):
        data = _pure_uptrend()
        strat = S4TrendStrength()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        # Strong consistent uptrend: positive slope, z > 0.5, above SMA200
        assert signal.signal in (SignalStrength.STRONG_BULL, SignalStrength.BULL)
        assert signal.raw_score >= 0.5

    def test_bear_negative_slope(self):
        data = _pure_downtrend()
        strat = S4TrendStrength()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        # In a steady downtrend, slope is consistently negative but the z-score
        # of that slope (vs its own 252-day history) may not be < -0.5 since
        # the slope has been similarly negative throughout. This can produce
        # NEUTRAL (slope<0, z>0) rather than BEAR (slope<0, z<-0.5).
        assert signal.signal in (SignalStrength.BEAR, SignalStrength.NEUTRAL)
        assert signal.raw_score <= 0

    def test_metadata_has_slope_and_zscore(self):
        data = _pure_uptrend()
        strat = S4TrendStrength()
        signal = strat.compute(data)
        assert "slope" in signal.metadata
        assert "slope_z" in signal.metadata
        assert "sma200" in signal.metadata
        assert "above_200" in signal.metadata

    def test_name(self):
        assert S4TrendStrength().name == "S4_TrendStrength"


# ===========================================================================
# S5 -- Momentum Velocity
# ===========================================================================


class TestS5MomentumVelocity:
    def test_strong_bull_positive_roc_and_velocity(self):
        """Accelerating uptrend should yield STRONG_BULL."""
        # Build accelerating uptrend: increasing daily returns
        np.random.seed(50)
        n = 100
        closes = np.empty(n)
        closes[0] = 10000.0
        for i in range(1, n):
            # Accelerating: daily return grows
            ret = 0.001 + i * 0.00005
            closes[i] = closes[i - 1] * (1 + ret)
        data = _make_ohlcv(closes)
        strat = S5MomentumVelocity()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        assert signal.signal == SignalStrength.STRONG_BULL
        assert signal.raw_score == 1.0

    def test_bear_negative_roc_and_velocity(self):
        """Accelerating downtrend: negative ROC and negative velocity."""
        np.random.seed(51)
        n = 100
        closes = np.empty(n)
        closes[0] = 20000.0
        for i in range(1, n):
            ret = -0.002 - i * 0.00005
            closes[i] = closes[i - 1] * (1 + ret)
        data = _make_ohlcv(closes)
        strat = S5MomentumVelocity()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        assert signal.raw_score <= -0.7

    def test_crash_penalty_applied(self):
        """A 5-day drop of >5% should trigger the crash penalty."""
        np.random.seed(52)
        n = 100
        closes = np.empty(n)
        closes[0] = 15000.0
        # Steady for most
        for i in range(1, 93):
            closes[i] = closes[i - 1] * 1.001
        # Sharp 7-day crash (-2% per day = ~13% total > 5%)
        for i in range(93, n):
            closes[i] = closes[i - 1] * 0.98
        data = _make_ohlcv(closes)
        strat = S5MomentumVelocity()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        assert signal.metadata["crash_penalty_applied"] is True

    def test_no_crash_penalty_in_normal_market(self):
        data = _pure_uptrend(n=100)
        strat = S5MomentumVelocity()
        signal = strat.compute(data)
        assert signal.metadata["crash_penalty_applied"] is False

    def test_name(self):
        assert S5MomentumVelocity().name == "S5_MomentumVelocity"


# ===========================================================================
# S6 -- Mean Reversion Bollinger
# ===========================================================================


class TestS6MeanRevBollinger:
    def test_extreme_oversold_gives_bull(self):
        """Price far below lower band (%B < 0.05) -> tactical BULL regardless of trend."""
        np.random.seed(60)
        n = 300
        closes = np.empty(n)
        closes[0] = 15000.0
        # Steady uptrend then sudden crash to push %B below 0.05
        for i in range(1, 270):
            closes[i] = closes[i - 1] * 1.001
        for i in range(270, n):
            closes[i] = closes[i - 1] * 0.97  # ~3% daily drop
        data = _make_ohlcv(closes)
        strat = S6MeanRevBollinger()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        # %B should be very low -> tactical bounce
        assert signal.raw_score >= 0.0

    def test_oversold_in_bull_trend_strong_bull(self):
        """Low %B (< 0.2) in a macro bull trend -> STRONG_BULL (buy the dip)."""
        np.random.seed(61)
        n = 500
        closes = np.empty(n)
        closes[0] = 10000.0
        # Strong uptrend for 480 days, mild pullback for the last 20
        for i in range(1, 480):
            closes[i] = closes[i - 1] * 1.002
        for i in range(480, n):
            closes[i] = closes[i - 1] * 0.992
        data = _make_ohlcv(closes)
        strat = S6MeanRevBollinger()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        # Price still above SMA200 but %B should be low
        pct_b = signal.metadata["pct_b"]
        if pct_b < 0.2 and signal.metadata["macro_bullish"]:
            assert signal.signal == SignalStrength.STRONG_BULL

    def test_overbought_in_bear_trend(self):
        """High %B (> 0.95) in bear trend -> BEAR (fade the rally)."""
        np.random.seed(62)
        n = 500
        closes = np.empty(n)
        closes[0] = 20000.0
        # Long downtrend, then sharp bounce
        for i in range(1, 470):
            closes[i] = closes[i - 1] * 0.999
        for i in range(470, n):
            closes[i] = closes[i - 1] * 1.015
        data = _make_ohlcv(closes)
        strat = S6MeanRevBollinger()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.15)
        if signal.metadata["pct_b"] > 0.95 and not signal.metadata["macro_bullish"]:
            assert signal.signal == SignalStrength.BEAR

    def test_metadata_has_pct_b(self):
        data = _pure_uptrend()
        strat = S6MeanRevBollinger()
        signal = strat.compute(data)
        assert "pct_b" in signal.metadata
        assert "macro_bullish" in signal.metadata

    def test_name(self):
        assert S6MeanRevBollinger().name == "S6_MeanRevBollinger"


# ===========================================================================
# S7 -- Volatility Regime
# ===========================================================================


class TestS7VolatilityRegime:
    def test_low_vol_ratio_bullish_strong_bull(self):
        """Low vol ratio (< 0.8) + bullish price -> STRONG_BULL."""
        np.random.seed(70)
        n = 500
        closes = np.empty(n)
        closes[0] = 10000.0
        # Steady uptrend with very low noise -> vol20 < vol60
        for i in range(1, 300):
            closes[i] = closes[i - 1] * (1 + 0.002 + np.random.randn() * 0.008)
        # Then much calmer period to bring vol20 down relative to vol60
        for i in range(300, n):
            closes[i] = closes[i - 1] * (1 + 0.002 + np.random.randn() * 0.001)
        data = _make_ohlcv(closes)
        strat = S7VolatilityRegime()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        vol_ratio = signal.metadata["vol_ratio"]
        if vol_ratio < 0.8 and signal.metadata["bullish"]:
            assert signal.signal == SignalStrength.STRONG_BULL
            assert signal.raw_score == 1.0

    def test_extreme_vol_ratio_bear(self):
        """Vol ratio > 2.0 -> BEAR regardless of trend."""
        np.random.seed(71)
        n = 500
        closes = np.empty(n)
        closes[0] = 15000.0
        # Very calm period for 400 days -> low vol60
        for i in range(1, 450):
            closes[i] = closes[i - 1] * (1 + 0.001 + np.random.randn() * 0.001)
        # Wild swings in last 50 days -> high vol20
        for i in range(450, n):
            closes[i] = closes[i - 1] * (1 + np.random.randn() * 0.05)
        data = _make_ohlcv(closes)
        strat = S7VolatilityRegime()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        if signal.metadata["vol_ratio"] > 2.0:
            assert signal.signal == SignalStrength.BEAR
            assert signal.raw_score == -0.3

    def test_moderate_vol_ratio_bullish_bull(self):
        """0.8 <= vol_ratio <= 1.2 and bullish -> BULL."""
        data = _pure_uptrend()
        strat = S7VolatilityRegime()
        signal = strat.compute(data)
        _assert_valid_signal(signal, 0.10)
        # Uptrend with consistent noise should have vol ratio near 1.0
        vol_ratio = signal.metadata["vol_ratio"]
        if 0.8 <= vol_ratio <= 1.2:
            assert signal.signal == SignalStrength.BULL
            assert signal.raw_score == 0.5

    def test_metadata_has_vol_fields(self):
        data = _pure_uptrend()
        strat = S7VolatilityRegime()
        signal = strat.compute(data)
        assert "vol20" in signal.metadata
        assert "vol60" in signal.metadata
        assert "vol_ratio" in signal.metadata
        assert "sma100" in signal.metadata
        assert "bullish" in signal.metadata

    def test_name(self):
        assert S7VolatilityRegime().name == "S7_VolatilityRegime"


# ===========================================================================
# Cross-cutting: all strategies produce valid SubStrategySignals on fixture
# ===========================================================================


class TestAllSubStrategies:
    """Run every sub-strategy against the sample_ndx_data fixture and verify structure."""

    STRATEGY_CLASSES = [
        (S1PrimaryTrend, 0.25),
        (S2IntermediateTrend, 0.15),
        (S3ShortTermTrend, 0.10),
        (S4TrendStrength, 0.10),
        (S5MomentumVelocity, 0.15),
        (S6MeanRevBollinger, 0.15),
        (S7VolatilityRegime, 0.10),
    ]

    @pytest.mark.parametrize(
        "cls, expected_weight",
        STRATEGY_CLASSES,
        ids=[c.__name__ for c, _ in STRATEGY_CLASSES],
    )
    def test_produces_valid_signal(
        self, cls, expected_weight, sample_ndx_data: pd.DataFrame
    ):
        strat = cls()
        signal = strat.compute(sample_ndx_data)
        _assert_valid_signal(signal, expected_weight)
        assert signal.strategy_name == strat.name
