"""Tests for the backtesting framework.

Uses the ``sample_ndx_data`` fixture from conftest to run backtests with
synthetic data.  TQQQ and SQQQ prices are derived from NDX to ensure
consistent test data without network access.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from whitelight.backtest.runner import BacktestConfig, BacktestRunner, DailySnapshot
from whitelight.backtest import metrics as bt_metrics
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_strategies():
    """Instantiate all 7 sub-strategies with default weights."""
    return [
        S1PrimaryTrend(),
        S2IntermediateTrend(),
        S3ShortTermTrend(),
        S4TrendStrength(),
        S5MomentumVelocity(),
        S6MeanRevBollinger(),
        S7VolatilityRegime(),
    ]


def _derive_leveraged_etf(ndx_data: pd.DataFrame, leverage: float, base_price: float) -> pd.DataFrame:
    """Simulate a leveraged ETF from NDX daily returns.

    This is a simplified model: daily ETF return = leverage * daily NDX return.
    Compounding and tracking error are inherent in leveraged ETFs, so this
    approximation is reasonable for testing purposes.

    Parameters
    ----------
    ndx_data:
        NDX OHLCV DataFrame indexed by date.
    leverage:
        3.0 for TQQQ, -3.0 for SQQQ.
    base_price:
        Starting price for the simulated ETF.
    """
    ndx_close = ndx_data["close"].values
    daily_returns = np.diff(ndx_close) / ndx_close[:-1]

    # Apply leverage to daily returns.
    etf_returns = leverage * daily_returns

    # Build price series from returns.
    prices = [base_price]
    for ret in etf_returns:
        prices.append(prices[-1] * (1 + ret))

    prices = np.array(prices)

    # Build OHLCV DataFrame.
    n = len(prices)
    np.random.seed(99)
    highs = prices * (1 + np.abs(np.random.randn(n) * 0.003))
    lows = prices * (1 - np.abs(np.random.randn(n) * 0.003))
    opens = prices * (1 + np.random.randn(n) * 0.002)
    volumes = np.random.randint(5_000_000, 50_000_000, size=n)

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": prices,
            "volume": volumes,
        },
        index=ndx_data.index,
    )
    df.index.name = "date"
    return df


@pytest.fixture
def backtest_data(sample_ndx_data):
    """Prepare NDX, TQQQ, and SQQQ data for backtesting.

    TQQQ is simulated as 3x daily NDX return.
    SQQQ is simulated as -3x daily NDX return.
    """
    tqqq = _derive_leveraged_etf(sample_ndx_data, leverage=3.0, base_price=60.0)
    sqqq = _derive_leveraged_etf(sample_ndx_data, leverage=-3.0, base_price=30.0)
    return sample_ndx_data, tqqq, sqqq


@pytest.fixture
def backtest_config(sample_ndx_data):
    """Create a backtest config spanning the test data range."""
    dates = sample_ndx_data.index
    # Start after enough warmup for the longest indicator (250-day SMA + buffer).
    warmup = 260
    start_idx = warmup
    start_date = dates[start_idx].date()
    end_date = dates[-1].date()
    return BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=Decimal("100000"),
        warmup_days=warmup,
    )


# ---------------------------------------------------------------------------
# Tests: BacktestRunner
# ---------------------------------------------------------------------------


class TestBacktestRunner:
    """Integration tests for the backtest runner."""

    def test_backtest_completes_without_errors(self, backtest_data, backtest_config):
        """The backtest should run to completion with synthetic data."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        assert len(result.daily_snapshots) > 0
        assert result.metrics is not None
        assert result.config == backtest_config

    def test_portfolio_value_always_positive(self, backtest_data, backtest_config):
        """Portfolio value should never go negative (no margin trading)."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        for snapshot in result.daily_snapshots:
            assert snapshot.portfolio_value > 0, (
                f"Portfolio value went non-positive on {snapshot.date}: "
                f"${snapshot.portfolio_value}"
            )

    def test_cash_never_negative(self, backtest_data, backtest_config):
        """Cash balance should never be significantly negative.

        Small floating-point rounding is acceptable (< $1), but large
        negative balances indicate a bug in position sizing.
        """
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        for snapshot in result.daily_snapshots:
            assert snapshot.cash >= Decimal("-1"), (
                f"Cash went negative on {snapshot.date}: ${snapshot.cash}"
            )

    def test_snapshots_are_chronological(self, backtest_data, backtest_config):
        """Daily snapshots must be in chronological order."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        dates = [s.date for s in result.daily_snapshots]
        assert dates == sorted(dates), "Snapshots are not in chronological order"

    def test_initial_portfolio_value_matches_capital(self, backtest_data, backtest_config):
        """The first day's portfolio should start near the initial capital."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        if result.daily_snapshots:
            first = result.daily_snapshots[0]
            # The portfolio value on day 1 may differ slightly from initial
            # capital if the strategy immediately takes positions, but it
            # should be in the same ballpark (within 5%).
            expected = float(backtest_config.initial_capital)
            actual = float(first.portfolio_value)
            assert abs(actual - expected) / expected < 0.05, (
                f"First day portfolio value ({actual}) differs too much from "
                f"initial capital ({expected})"
            )

    def test_no_simultaneous_tqqq_and_sqqq(self, backtest_data, backtest_config):
        """The system should never hold both TQQQ and SQQQ simultaneously.

        This is enforced by the combiner's no-flip rule and the fact that
        the target allocation never has both tqqq_pct > 0 and sqqq_pct > 0.
        """
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        for snapshot in result.daily_snapshots:
            assert not (snapshot.tqqq_shares > 0 and snapshot.sqqq_shares > 0), (
                f"Held both TQQQ ({snapshot.tqqq_shares}) and SQQQ "
                f"({snapshot.sqqq_shares}) on {snapshot.date}"
            )

    def test_summary_string(self, backtest_data, backtest_config):
        """The summary method should produce a non-empty string."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)
        summary = result.summary()

        assert isinstance(summary, str)
        assert len(summary) > 100
        assert "WHITE LIGHT" in summary


# ---------------------------------------------------------------------------
# Tests: Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    """Unit tests for the metrics module."""

    def test_total_return(self):
        """Total return calculation."""
        values = pd.Series([100, 110, 120, 130])
        assert bt_metrics.total_return(values) == pytest.approx(0.3, abs=0.001)

    def test_total_return_with_loss(self):
        """Total return with a losing portfolio."""
        values = pd.Series([100, 90, 80])
        assert bt_metrics.total_return(values) == pytest.approx(-0.2, abs=0.001)

    def test_annual_return_cagr(self):
        """CAGR calculation over one year of trading days."""
        # 252 data points -> 251 return periods -> 1 year.
        n = 252
        daily_ret = 0.001  # ~0.1% per day
        values = pd.Series([100 * (1 + daily_ret) ** i for i in range(n)])
        cagr = bt_metrics.annual_return(values)
        expected = (1 + daily_ret) ** 252 - 1  # ~28.6%
        assert cagr == pytest.approx(expected, rel=0.01)

    def test_max_drawdown(self):
        """Max drawdown from a peak-to-valley."""
        values = pd.Series([100, 110, 90, 95, 85, 100])
        mdd = bt_metrics.max_drawdown(values)
        # Peak is 110, trough is 85 -> drawdown = 25/110 = 22.7%
        assert mdd == pytest.approx(25 / 110, abs=0.001)

    def test_max_drawdown_no_drawdown(self):
        """Max drawdown when portfolio only goes up."""
        values = pd.Series([100, 110, 120, 130])
        assert bt_metrics.max_drawdown(values) == 0.0

    def test_sharpe_ratio_positive(self):
        """Sharpe ratio should be positive for consistently positive returns."""
        np.random.seed(42)
        # Strongly positive returns with low volatility.
        returns = pd.Series(np.random.normal(0.002, 0.005, 252))
        sr = bt_metrics.sharpe_ratio(returns)
        assert sr > 0

    def test_sortino_ratio(self):
        """Sortino ratio should be computable."""
        np.random.seed(42)
        returns = pd.Series(np.random.normal(0.001, 0.01, 252))
        sr = bt_metrics.sortino_ratio(returns)
        assert isinstance(sr, float)

    def test_calmar_ratio(self):
        """Calmar ratio = CAGR / max drawdown."""
        values = pd.Series([100, 110, 90, 95, 100, 115])
        cr = bt_metrics.calmar_ratio(values)
        assert isinstance(cr, float)
        assert cr != 0

    def test_win_rate(self):
        """Win rate from trades."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
            {"pnl": -30},
        ]
        assert bt_metrics.win_rate(trades) == pytest.approx(0.5, abs=0.001)

    def test_profit_factor(self):
        """Profit factor = gross profits / gross losses."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
        ]
        pf = bt_metrics.profit_factor(trades)
        assert pf == pytest.approx(300 / 50, abs=0.01)

    def test_profit_factor_no_losses(self):
        """Profit factor is inf when there are no losses."""
        trades = [{"pnl": 100}, {"pnl": 200}]
        assert bt_metrics.profit_factor(trades) == float("inf")

    def test_monthly_returns(self):
        """Monthly returns table generation."""
        dates = [
            date(2023, 1, 3),
            date(2023, 1, 31),
            date(2023, 2, 1),
            date(2023, 2, 28),
            date(2023, 3, 1),
            date(2023, 3, 31),
        ]
        values = [
            Decimal("100000"),
            Decimal("105000"),
            Decimal("105000"),
            Decimal("110000"),
            Decimal("110000"),
            Decimal("108000"),
        ]
        monthly = bt_metrics.monthly_returns(dates, values)
        assert not monthly.empty
        assert "year" in monthly.columns
        assert "month" in monthly.columns
        assert "return_pct" in monthly.columns

    def test_compute_all_returns_dict(self, backtest_data, backtest_config):
        """compute_all should return a dict with all expected metric keys."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)
        metrics = result.metrics

        expected_keys = {
            "total_return",
            "annual_return",
            "max_drawdown",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "win_rate",
            "profit_factor",
            "avg_trade_duration",
            "avg_winning_trade",
            "avg_losing_trade",
            "total_trades",
            "trading_days",
        }
        assert expected_keys.issubset(metrics.keys()), (
            f"Missing metrics: {expected_keys - metrics.keys()}"
        )


# ---------------------------------------------------------------------------
# Tests: Monthly returns table
# ---------------------------------------------------------------------------


class TestMonthlyReturns:
    """Tests for monthly return computation."""

    def test_monthly_returns_generated(self, backtest_data, backtest_config):
        """The backtest should produce a monthly returns DataFrame."""
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        assert isinstance(result.monthly_returns, pd.DataFrame)
        assert not result.monthly_returns.empty
        assert list(result.monthly_returns.columns) == ["year", "month", "return_pct"]

    def test_monthly_returns_reasonable_values(self, backtest_data, backtest_config):
        """Monthly returns should be within a reasonable range for TQQQ/SQQQ.

        Leveraged ETFs can have extreme months, but each month should be
        within -80% to +100% for a position-sized portfolio.
        """
        ndx, tqqq, sqqq = backtest_data
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, backtest_config)

        result = runner.run(ndx, tqqq, sqqq)

        for _, row in result.monthly_returns.iterrows():
            ret = row["return_pct"]
            assert -80 < ret < 100, (
                f"Monthly return of {ret}% for {int(row['year'])}-{int(row['month'])} "
                f"seems unreasonable"
            )


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests for the backtest runner."""

    def test_empty_date_range(self, sample_ndx_data):
        """Backtest with an impossible date range should produce empty results."""
        tqqq = _derive_leveraged_etf(sample_ndx_data, 3.0, 60.0)
        sqqq = _derive_leveraged_etf(sample_ndx_data, -3.0, 30.0)

        config = BacktestConfig(
            start_date=date(2099, 1, 1),
            end_date=date(2099, 12, 31),
        )
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, config)

        result = runner.run(sample_ndx_data, tqqq, sqqq)

        assert len(result.daily_snapshots) == 0
        assert len(result.trades) == 0

    def test_single_day_backtest(self, sample_ndx_data):
        """Backtest over a single day should produce one snapshot."""
        tqqq = _derive_leveraged_etf(sample_ndx_data, 3.0, 60.0)
        sqqq = _derive_leveraged_etf(sample_ndx_data, -3.0, 30.0)

        # Pick a day that has enough warmup history.
        dates = sample_ndx_data.index
        single_day = dates[270].date()

        config = BacktestConfig(
            start_date=single_day,
            end_date=single_day,
            warmup_days=260,
        )
        strategies = _build_strategies()
        combiner = SignalCombiner()
        runner = BacktestRunner(strategies, combiner, config)

        result = runner.run(sample_ndx_data, tqqq, sqqq)

        assert len(result.daily_snapshots) == 1
