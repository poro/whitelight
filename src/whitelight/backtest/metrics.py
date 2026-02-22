"""Performance metric calculations for backtesting results.

All functions operate on sequences of daily portfolio values (or returns)
and produce standard risk-adjusted performance statistics.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from whitelight.backtest.runner import DailySnapshot


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.04  # annualised


# ---------------------------------------------------------------------------
# Core metric functions
# ---------------------------------------------------------------------------


def total_return(portfolio_values: pd.Series) -> float:
    """Cumulative total return: (final / initial) - 1."""
    if len(portfolio_values) < 2:
        return 0.0
    initial = float(portfolio_values.iloc[0])
    final = float(portfolio_values.iloc[-1])
    if initial == 0:
        return 0.0
    return (final / initial) - 1.0


def annual_return(portfolio_values: pd.Series) -> float:
    """Compound Annual Growth Rate (CAGR).

    CAGR = (final / initial) ^ (252 / n_days) - 1
    """
    if len(portfolio_values) < 2:
        return 0.0
    initial = float(portfolio_values.iloc[0])
    final = float(portfolio_values.iloc[-1])
    n_days = len(portfolio_values) - 1
    if initial <= 0 or final <= 0 or n_days == 0:
        return 0.0
    return (final / initial) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0


def max_drawdown(portfolio_values: pd.Series) -> float:
    """Maximum peak-to-valley drawdown (returned as a positive number).

    E.g. a 25% drawdown is returned as 0.25.
    """
    if len(portfolio_values) < 2:
        return 0.0
    cummax = portfolio_values.cummax()
    drawdowns = (portfolio_values - cummax) / cummax
    return float(-drawdowns.min())


def sharpe_ratio(daily_returns: pd.Series) -> float:
    """Annualised Sharpe ratio.

    Sharpe = (mean_excess_return / std_return) * sqrt(252)
    Uses a risk-free rate of 4% annualised.
    """
    if len(daily_returns) < 2:
        return 0.0
    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    excess = daily_returns - daily_rf
    std = float(excess.std())
    if std == 0:
        return 0.0
    return float(excess.mean() / std) * np.sqrt(TRADING_DAYS_PER_YEAR)


def sortino_ratio(daily_returns: pd.Series) -> float:
    """Annualised Sortino ratio.

    Like Sharpe but uses downside deviation instead of total standard deviation.
    """
    if len(daily_returns) < 2:
        return 0.0
    daily_rf = RISK_FREE_RATE / TRADING_DAYS_PER_YEAR
    excess = daily_returns - daily_rf
    downside = excess[excess < 0]
    if len(downside) == 0 or float(downside.std()) == 0:
        return 0.0
    downside_std = float(np.sqrt((downside**2).mean()))
    return float(excess.mean() / downside_std) * np.sqrt(TRADING_DAYS_PER_YEAR)


def calmar_ratio(portfolio_values: pd.Series) -> float:
    """Calmar ratio: CAGR / max drawdown.

    Returns 0.0 if max drawdown is zero.
    """
    cagr = annual_return(portfolio_values)
    mdd = max_drawdown(portfolio_values)
    if mdd == 0:
        return 0.0
    return cagr / mdd


# ---------------------------------------------------------------------------
# Trade-level metrics
# ---------------------------------------------------------------------------


def win_rate(trades: list[dict]) -> float:
    """Fraction of completed trades that were profitable.

    A trade is profitable if sell_price * shares > buy_price * shares.
    Expects trades in the format:
        [{"pnl": float}, ...]
    """
    completed = [t for t in trades if "pnl" in t]
    if not completed:
        return 0.0
    winners = [t for t in completed if t["pnl"] > 0]
    return len(winners) / len(completed)


def profit_factor(trades: list[dict]) -> float:
    """Gross profits / gross losses.

    Returns ``float('inf')`` if there are no losses, 0.0 if no trades.
    """
    completed = [t for t in trades if "pnl" in t]
    if not completed:
        return 0.0
    gross_profit = sum(t["pnl"] for t in completed if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in completed if t["pnl"] < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_trade_duration(trades: list[dict]) -> float:
    """Average number of trading days per completed round-trip trade."""
    durations = [t["duration_days"] for t in trades if "duration_days" in t]
    if not durations:
        return 0.0
    return sum(durations) / len(durations)


def avg_winning_trade(trades: list[dict]) -> float:
    """Average PnL of winning trades (as a decimal return)."""
    winners = [t for t in trades if "pnl" in t and t["pnl"] > 0]
    if not winners:
        return 0.0
    return sum(t["pnl"] for t in winners) / len(winners)


def avg_losing_trade(trades: list[dict]) -> float:
    """Average PnL of losing trades (as a negative decimal return)."""
    losers = [t for t in trades if "pnl" in t and t["pnl"] < 0]
    if not losers:
        return 0.0
    return sum(t["pnl"] for t in losers) / len(losers)


# ---------------------------------------------------------------------------
# Monthly returns
# ---------------------------------------------------------------------------


def monthly_returns(
    dates: list[date],
    portfolio_values: list[Decimal],
) -> pd.DataFrame:
    """Build a table of monthly returns from daily snapshots.

    Returns a DataFrame with columns:
        year, month, return_pct
    """
    if len(dates) < 2:
        return pd.DataFrame(columns=["year", "month", "return_pct"])

    # Build a daily series indexed by date.
    series = pd.Series(
        [float(v) for v in portfolio_values],
        index=pd.DatetimeIndex(dates),
        name="portfolio_value",
    )

    # Resample to month-end, taking the last available value in each month.
    month_end = series.resample("ME").last()

    # Compute month-over-month returns.
    monthly_rets = month_end.pct_change().dropna()

    rows = []
    for dt, ret in monthly_rets.items():
        rows.append({"year": dt.year, "month": dt.month, "return_pct": round(ret * 100, 2)})

    return pd.DataFrame(rows, columns=["year", "month", "return_pct"])


# ---------------------------------------------------------------------------
# Aggregated compute_all
# ---------------------------------------------------------------------------


def compute_all(
    snapshots: list[DailySnapshot],
    trades: list[dict],
) -> dict:
    """Compute all performance metrics from daily snapshots and trade list.

    Returns a dictionary containing every metric keyed by name.
    """
    if not snapshots:
        return {}

    portfolio_values = pd.Series(
        [float(s.portfolio_value) for s in snapshots],
        index=pd.DatetimeIndex([s.date for s in snapshots]),
    )

    daily_rets = portfolio_values.pct_change().dropna()

    completed_trades = [t for t in trades if "pnl" in t]

    return {
        "total_return": round(total_return(portfolio_values), 6),
        "annual_return": round(annual_return(portfolio_values), 6),
        "max_drawdown": round(max_drawdown(portfolio_values), 6),
        "sharpe_ratio": round(sharpe_ratio(daily_rets), 4),
        "sortino_ratio": round(sortino_ratio(daily_rets), 4),
        "calmar_ratio": round(calmar_ratio(portfolio_values), 4),
        "win_rate": round(win_rate(completed_trades), 4),
        "profit_factor": round(profit_factor(completed_trades), 4),
        "avg_trade_duration": round(avg_trade_duration(completed_trades), 1),
        "avg_winning_trade": round(avg_winning_trade(completed_trades), 4),
        "avg_losing_trade": round(avg_losing_trade(completed_trades), 4),
        "total_trades": len(completed_trades),
        "trading_days": len(snapshots),
    }
