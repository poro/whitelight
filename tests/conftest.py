"""Shared test fixtures."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from whitelight.models import AccountInfo, BrokerageID, Position, PortfolioSnapshot


@pytest.fixture
def sample_ndx_data() -> pd.DataFrame:
    """Generate realistic NDX OHLCV data covering bull and bear regimes.

    Returns ~500 trading days of synthetic data with:
    - First 250 days: uptrend (bull market)
    - Next 100 days: downtrend (bear market)
    - Last 150 days: recovery (choppy then uptrend)
    """
    np.random.seed(42)
    n_days = 500
    dates = pd.bdate_range(start="2023-01-03", periods=n_days, freq="B")

    # Generate price path with regime changes
    prices = [15000.0]  # Starting NDX price

    for i in range(1, n_days):
        if i < 250:
            # Bull market: +0.08% daily drift
            drift = 0.0008
            vol = 0.012
        elif i < 350:
            # Bear market: -0.12% daily drift
            drift = -0.0012
            vol = 0.018
        else:
            # Recovery: +0.05% daily drift
            drift = 0.0005
            vol = 0.015

        ret = drift + vol * np.random.randn()
        prices.append(prices[-1] * (1 + ret))

    closes = np.array(prices)
    # Generate OHLV from close
    highs = closes * (1 + np.abs(np.random.randn(n_days) * 0.005))
    lows = closes * (1 - np.abs(np.random.randn(n_days) * 0.005))
    opens = closes * (1 + np.random.randn(n_days) * 0.003)
    volumes = np.random.randint(1_000_000, 5_000_000, size=n_days)

    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )
    df.index.name = "date"
    return df


@pytest.fixture
def mock_portfolio_snapshot() -> PortfolioSnapshot:
    """A portfolio with some TQQQ holdings."""
    return PortfolioSnapshot(
        accounts=[
            AccountInfo(
                brokerage=BrokerageID.PAPER,
                equity=Decimal("100000"),
                cash=Decimal("70000"),
                buying_power=Decimal("70000"),
            )
        ],
        positions=[
            Position(
                brokerage=BrokerageID.PAPER,
                symbol="TQQQ",
                qty=Decimal("500"),
                market_value=Decimal("30000"),
                avg_cost=Decimal("55.00"),
            )
        ],
        total_equity=Decimal("100000"),
        total_cash=Decimal("70000"),
        positions_by_symbol={"TQQQ": Decimal("500")},
    )
