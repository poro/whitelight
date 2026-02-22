"""Evaluate converted strategies using VectorBT.

Runs backtests on TQQQ/SQQQ data and computes composite scores for ranking.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    HAS_VBT = False

from whitelight.research.database import StrategyDB

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/cache")

# Composite score weights (from PRD Section 9.5)
WEIGHTS = {
    "sharpe": 0.25,
    "calmar": 0.25,
    "max_dd": 0.20,
    "profit_factor": 0.15,
    "frequency": 0.15,
}

# Minimum thresholds for a passing strategy
THRESHOLDS = {
    "sharpe": 1.0,
    "calmar": 0.5,
    "max_dd": 0.40,       # max 40% drawdown
    "profit_factor": 1.5,
    "min_trades": 10,
    "max_trades": 200,     # per year
}


def _load_data(ticker: str = "TQQQ") -> pd.DataFrame:
    """Load OHLCV data from parquet cache."""
    path = CACHE_DIR / f"{ticker.lower()}_daily.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Cache file not found: {path}")

    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    df = df.sort_index()
    return df


def _execute_strategy(python_code: str, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Execute a converted strategy function against data.

    Returns (entries, exits) boolean Series.
    """
    # Create a namespace for the strategy code
    namespace = {"np": np, "pd": pd}
    exec(python_code, namespace)

    strategy_fn = namespace.get("strategy")
    if strategy_fn is None:
        raise ValueError("No 'strategy' function found in converted code")

    # Run the strategy
    entries, exits = strategy_fn(df)

    # Ensure they're boolean Series aligned with df index
    entries = pd.Series(entries, index=df.index).fillna(False).astype(bool)
    exits = pd.Series(exits, index=df.index).fillna(False).astype(bool)

    return entries, exits


def _compute_metrics_vbt(
    df: pd.DataFrame,
    entries: pd.Series,
    exits: pd.Series,
    initial_capital: float = 100_000,
) -> dict:
    """Run VectorBT backtest and compute all metrics."""
    if not HAS_VBT:
        raise ImportError("vectorbt not installed")

    # Build portfolio from signals
    pf = vbt.Portfolio.from_signals(
        close=df["close"],
        entries=entries,
        exits=exits,
        init_cash=initial_capital,
        freq="1D",
    )

    # Extract metrics
    stats = pf.stats()

    total_return = float(pf.total_return())
    n_days = len(df)
    n_years = n_days / 252

    # Trade stats
    trades = pf.trades.records_readable if len(pf.trades.records) > 0 else pd.DataFrame()
    n_trades = len(trades) if not trades.empty else 0
    trade_freq = n_trades / n_years if n_years > 0 else 0

    # Win rate
    if not trades.empty and "PnL" in trades.columns:
        winners = (trades["PnL"] > 0).sum()
        win_rate = winners / n_trades if n_trades > 0 else 0
        gross_profit = trades.loc[trades["PnL"] > 0, "PnL"].sum() if winners > 0 else 0
        gross_loss = abs(trades.loc[trades["PnL"] < 0, "PnL"].sum()) if (trades["PnL"] < 0).any() else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_duration = trades["Duration"].dt.days.mean() if "Duration" in trades.columns else 0
    else:
        win_rate = 0
        profit_factor = 0
        avg_duration = 0

    # Core ratios
    returns = pf.returns()
    daily_rf = 0.04 / 252

    excess = returns - daily_rf
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

    downside = excess[excess < 0]
    sortino = float(excess.mean() / np.sqrt((downside ** 2).mean()) * np.sqrt(252)) if len(downside) > 0 else 0

    max_dd = float(pf.max_drawdown())
    cagr = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return {
        "ticker": "TQQQ",
        "start_date": str(df.index[0].date()),
        "end_date": str(df.index[-1].date()),
        "initial_capital": initial_capital,
        "final_value": initial_capital * (1 + total_return),
        "total_return": total_return,
        "annual_return": cagr,
        "max_drawdown": abs(max_dd),
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "profit_factor": profit_factor,
        "win_rate": win_rate,
        "total_trades": n_trades,
        "avg_trade_duration": avg_duration,
        "trade_frequency": trade_freq,
    }


def _compute_composite_score(metrics: dict) -> float:
    """Compute the weighted composite score for ranking.

    Normalizes each metric to a 0-1 scale then applies weights.
    """
    # Normalize sharpe: 0 maps to 0, 3+ maps to 1
    sharpe_norm = min(max(metrics.get("sharpe_ratio", 0) / 3.0, 0), 1)

    # Normalize calmar: 0 maps to 0, 2+ maps to 1
    calmar_norm = min(max(metrics.get("calmar_ratio", 0) / 2.0, 0), 1)

    # Normalize max_dd: 0% maps to 1, 50%+ maps to 0
    max_dd = metrics.get("max_drawdown", 1.0)
    dd_norm = max(1.0 - (max_dd / 0.5), 0)

    # Normalize profit factor: 1 maps to 0, 4+ maps to 1
    pf = metrics.get("profit_factor", 0)
    if pf == float("inf"):
        pf_norm = 1.0
    else:
        pf_norm = min(max((pf - 1.0) / 3.0, 0), 1)

    # Normalize frequency: sweet spot is 20-100 trades/year
    freq = metrics.get("trade_frequency", 0)
    if 20 <= freq <= 100:
        freq_norm = 1.0
    elif 10 <= freq < 20 or 100 < freq <= 200:
        freq_norm = 0.5
    else:
        freq_norm = 0.1

    score = (
        WEIGHTS["sharpe"] * sharpe_norm
        + WEIGHTS["calmar"] * calmar_norm
        + WEIGHTS["max_dd"] * dd_norm
        + WEIGHTS["profit_factor"] * pf_norm
        + WEIGHTS["frequency"] * freq_norm
    )

    return round(score, 4)


def evaluate_strategy(
    db: StrategyDB,
    strategy_id: int,
    python_code: str,
    ticker: str = "TQQQ",
) -> Optional[dict]:
    """Evaluate a converted strategy on historical data.

    Returns metrics dict with composite_score, or None on failure.
    """
    try:
        df = _load_data(ticker)
    except FileNotFoundError as e:
        logger.error("Data not found: %s", e)
        return None

    try:
        entries, exits = _execute_strategy(python_code, df)
    except Exception as e:
        logger.error("Strategy execution failed for #%d: %s", strategy_id, e)
        db.update_status(strategy_id, "failed", f"Execution error: {e}")
        return None

    # Check we got some signals
    n_entries = entries.sum()
    n_exits = exits.sum()
    if n_entries < 2:
        logger.warning("Strategy #%d produced only %d entry signals — skipping", strategy_id, n_entries)
        db.update_status(strategy_id, "failed", f"Too few signals: {n_entries} entries")
        return None

    try:
        metrics = _compute_metrics_vbt(df, entries, exits)
    except Exception as e:
        logger.error("VectorBT backtest failed for #%d: %s\n%s", strategy_id, e, traceback.format_exc())
        db.update_status(strategy_id, "failed", f"Backtest error: {e}")
        return None

    # Compute composite score
    metrics["composite_score"] = _compute_composite_score(metrics)

    # Check thresholds
    passes = True
    reasons = []
    if metrics["sharpe_ratio"] < THRESHOLDS["sharpe"]:
        reasons.append(f"Sharpe {metrics['sharpe_ratio']:.2f} < {THRESHOLDS['sharpe']}")
        passes = False
    if metrics["calmar_ratio"] < THRESHOLDS["calmar"]:
        reasons.append(f"Calmar {metrics['calmar_ratio']:.2f} < {THRESHOLDS['calmar']}")
        passes = False
    if metrics["max_drawdown"] > THRESHOLDS["max_dd"]:
        reasons.append(f"MaxDD {metrics['max_drawdown']:.1%} > {THRESHOLDS['max_dd']:.0%}")
    if metrics["profit_factor"] < THRESHOLDS["profit_factor"] and metrics["profit_factor"] != float("inf"):
        reasons.append(f"PF {metrics['profit_factor']:.2f} < {THRESHOLDS['profit_factor']}")

    metrics["passes_thresholds"] = passes
    metrics["threshold_notes"] = "; ".join(reasons) if reasons else "All thresholds met"

    # Save to DB
    db.add_backtest_result(strategy_id, metrics)

    logger.info(
        "Strategy #%d: score=%.4f sharpe=%.2f calmar=%.2f maxdd=%.1f%% pf=%.2f trades=%d %s",
        strategy_id, metrics["composite_score"], metrics["sharpe_ratio"],
        metrics["calmar_ratio"], metrics["max_drawdown"] * 100,
        metrics["profit_factor"], metrics["total_trades"],
        "✅" if passes else "❌",
    )

    return metrics
