#!/usr/bin/env python3
"""CLI entry point for running White Light backtests.

Usage examples::

    python scripts/backtest.py                                  # Full backtest, default dates
    python scripts/backtest.py --start 2022-07-23               # From C2 inception
    python scripts/backtest.py --source yfinance                # Use free Yahoo data (default)
    python scripts/backtest.py --source massive --api-key KEY   # Use Massive REST API
    python scripts/backtest.py --source polygon --api-key KEY   # Use Polygon REST API
    python scripts/backtest.py --compare-c2                     # Compare against C2 monthly returns
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

# Ensure the project root is on sys.path so ``whitelight`` is importable.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from whitelight.backtest.runner import BacktestConfig, BacktestRunner
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime


# ---------------------------------------------------------------------------
# C2 monthly returns from the PRD (for comparison)
# ---------------------------------------------------------------------------

# Monthly returns as reported on Collective2 (inception 2022-07-23).
C2_MONTHLY_RETURNS = {
    (2022, 7): -3.2,
    (2022, 8): -8.5,
    (2022, 9): -11.2,
    (2022, 10): 6.8,
    (2022, 11): 4.3,
    (2022, 12): -5.1,
    (2023, 1): 15.2,
    (2023, 2): -4.8,
    (2023, 3): 8.7,
    (2023, 4): 2.1,
    (2023, 5): 11.4,
    (2023, 6): 14.2,
    (2023, 7): 5.3,
    (2023, 8): -6.1,
    (2023, 9): -7.4,
    (2023, 10): -4.2,
    (2023, 11): 18.5,
    (2023, 12): 9.1,
    (2024, 1): 7.3,
    (2024, 2): 11.8,
    (2024, 3): 4.5,
    (2024, 4): -8.7,
    (2024, 5): 12.1,
    (2024, 6): 9.4,
}

MONTH_NAMES = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_data_yfinance(
    start_date: date,
    end_date: date,
    warmup_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download NDX, TQQQ, and SQQQ data from Yahoo Finance."""
    from whitelight.data.yfinance_client import YFinanceClient

    client = YFinanceClient()

    # Fetch extra history for the warmup window.
    # Roughly 1.5x warmup in calendar days to account for weekends/holidays.
    warmup_start = start_date - timedelta(days=int(warmup_days * 1.5))

    print(f"Downloading NDX data ({warmup_start} to {end_date})...")
    ndx = client.get_daily_bars("NDX", warmup_start, end_date)

    print(f"Downloading TQQQ data ({warmup_start} to {end_date})...")
    tqqq = client.get_daily_bars("TQQQ", warmup_start, end_date)

    print(f"Downloading SQQQ data ({warmup_start} to {end_date})...")
    sqqq = client.get_daily_bars("SQQQ", warmup_start, end_date)

    return ndx, tqqq, sqqq


def _load_data_massive(
    api_key: str,
    start_date: date,
    end_date: date,
    warmup_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download NDX, TQQQ, and SQQQ data from Massive REST API."""
    from whitelight.data.massive_client import MassiveClient

    client = MassiveClient(api_key=api_key)
    warmup_start = start_date - timedelta(days=int(warmup_days * 1.5))

    print(f"Downloading NDX data from Massive ({warmup_start} to {end_date})...")
    ndx = client.get_daily_bars("NDX", warmup_start, end_date)

    print(f"Downloading TQQQ data from Massive ({warmup_start} to {end_date})...")
    tqqq = client.get_daily_bars("TQQQ", warmup_start, end_date)

    print(f"Downloading SQQQ data from Massive ({warmup_start} to {end_date})...")
    sqqq = client.get_daily_bars("SQQQ", warmup_start, end_date)

    return ndx, tqqq, sqqq


def _load_data_polygon(
    api_key: str,
    start_date: date,
    end_date: date,
    warmup_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Download NDX, TQQQ, and SQQQ data from Polygon.io."""
    from whitelight.data.polygon_client import PolygonClient

    client = PolygonClient(api_key=api_key)
    warmup_start = start_date - timedelta(days=int(warmup_days * 1.5))

    print(f"Downloading NDX data from Polygon ({warmup_start} to {end_date})...")
    ndx = client.get_daily_bars("NDX", warmup_start, end_date)

    print(f"Downloading TQQQ data from Polygon ({warmup_start} to {end_date})...")
    tqqq = client.get_daily_bars("TQQQ", warmup_start, end_date)

    print(f"Downloading SQQQ data from Polygon ({warmup_start} to {end_date})...")
    sqqq = client.get_daily_bars("SQQQ", warmup_start, end_date)

    return ndx, tqqq, sqqq


def _load_data_cache(
    cache_dir: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load data from the local Parquet cache."""
    from whitelight.data.cache import CacheManager

    cache = CacheManager(cache_dir)

    print(f"Loading cached data from {cache_dir}...")
    ndx = cache.read("NDX")
    tqqq = cache.read("TQQQ")
    sqqq = cache.read("SQQQ")

    if ndx.empty or tqqq.empty or sqqq.empty:
        print("ERROR: Cache is empty or incomplete. Run seed_cache.py first, or use --source yfinance.")
        sys.exit(1)

    return ndx, tqqq, sqqq


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def _print_monthly_returns_table(monthly_df: pd.DataFrame) -> None:
    """Print a formatted monthly returns table (year rows x month columns)."""
    if monthly_df.empty:
        print("  No monthly returns to display.")
        return

    pivot = monthly_df.pivot(index="year", columns="month", values="return_pct")
    pivot = pivot.reindex(columns=range(1, 13))

    # Header.
    header = "  Year  " + "  ".join(f"{MONTH_NAMES[m]:>6s}" for m in range(1, 13)) + "   YTD"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for year in sorted(pivot.index):
        row_vals = []
        ytd = 1.0
        for m in range(1, 13):
            val = pivot.loc[year, m] if pd.notna(pivot.loc[year, m]) else None
            if val is not None:
                row_vals.append(f"{val:+6.1f}%")
                ytd *= (1 + val / 100.0)
            else:
                row_vals.append("      ")
        ytd_pct = (ytd - 1.0) * 100
        row_str = "  ".join(row_vals)
        print(f"  {year}  {row_str}  {ytd_pct:+6.1f}%")


def _print_c2_comparison(backtest_monthly: pd.DataFrame) -> None:
    """Print side-by-side comparison of backtest vs C2 monthly returns."""
    print("\n" + "=" * 60)
    print("  BACKTEST vs C2 MONTHLY RETURNS")
    print("=" * 60)
    print(f"  {'Month':<12s} {'Backtest':>10s} {'C2':>10s} {'Diff':>10s}")
    print("  " + "-" * 44)

    for _, row in backtest_monthly.iterrows():
        year = int(row["year"])
        month = int(row["month"])
        bt_ret = row["return_pct"]
        c2_ret = C2_MONTHLY_RETURNS.get((year, month))

        month_label = f"{year}-{MONTH_NAMES[month]}"
        bt_str = f"{bt_ret:+.1f}%"

        if c2_ret is not None:
            c2_str = f"{c2_ret:+.1f}%"
            diff = bt_ret - c2_ret
            diff_str = f"{diff:+.1f}%"
        else:
            c2_str = "  N/A"
            diff_str = "  N/A"

        print(f"  {month_label:<12s} {bt_str:>10s} {c2_str:>10s} {diff_str:>10s}")


def _save_results(result, output_dir: Path) -> Path:
    """Save backtest results to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = date.today().isoformat()
    filename = f"backtest_{result.config.start_date}_{result.config.end_date}_{timestamp}.json"
    filepath = output_dir / filename

    # Serialise results (convert non-JSON-serialisable types).
    data = {
        "config": {
            "start_date": str(result.config.start_date),
            "end_date": str(result.config.end_date),
            "initial_capital": str(result.config.initial_capital),
            "warmup_days": result.config.warmup_days,
        },
        "metrics": result.metrics,
        "monthly_returns": result.monthly_returns.to_dict(orient="records"),
        "trade_count": len(result.trades),
        "snapshot_count": len(result.daily_snapshots),
        "trades": [
            {
                k: str(v) if isinstance(v, (date, Decimal)) else v
                for k, v in t.items()
            }
            for t in result.trades
        ],
    }

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)

    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_strategies() -> list:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a White Light backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2020-01-02",
        help="Backtest start date (YYYY-MM-DD).  Default: 2020-01-02",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Backtest end date (YYYY-MM-DD).  Default: today",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000,
        help="Initial capital in USD.  Default: 100000",
    )
    parser.add_argument(
        "--source",
        choices=["yfinance", "massive", "polygon", "cache"],
        default="yfinance",
        help="Data source.  Default: yfinance",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API key (required if --source massive or polygon)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="./data",
        help="Cache directory for parquet files.  Default: ./data",
    )
    parser.add_argument(
        "--compare-c2",
        action="store_true",
        help="Compare backtest monthly returns against C2 track record",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/backtest_results",
        help="Directory to save results JSON.  Default: ./data/backtest_results",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=260,
        help="Warmup days for indicator calculation.  Default: 260",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    args = parser.parse_args()

    # Configure logging.
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end) if args.end else date.today()

    print("\n" + "=" * 60)
    print("  WHITE LIGHT BACKTESTER")
    print("=" * 60)
    print(f"  Period:  {start_date} to {end_date}")
    print(f"  Capital: ${args.capital:,.2f}")
    print(f"  Source:  {args.source}")
    print(f"  Warmup:  {args.warmup} days")
    print("=" * 60 + "\n")

    # Load data.
    if args.source == "yfinance":
        ndx, tqqq, sqqq = _load_data_yfinance(start_date, end_date, args.warmup)
    elif args.source == "massive":
        if not args.api_key:
            print("ERROR: --api-key is required when using --source massive")
            sys.exit(1)
        ndx, tqqq, sqqq = _load_data_massive(args.api_key, start_date, end_date, args.warmup)
    elif args.source == "polygon":
        if not args.api_key:
            print("ERROR: --api-key is required when using --source polygon")
            sys.exit(1)
        ndx, tqqq, sqqq = _load_data_polygon(args.api_key, start_date, end_date, args.warmup)
    elif args.source == "cache":
        ndx, tqqq, sqqq = _load_data_cache(args.cache_dir)
    else:
        print(f"ERROR: Unknown data source: {args.source}")
        sys.exit(1)

    # Validate data.
    for name, df in [("NDX", ndx), ("TQQQ", tqqq), ("SQQQ", sqqq)]:
        print(f"  {name}: {len(df)} bars")
        if df.empty:
            print(f"ERROR: No data available for {name}")
            sys.exit(1)

    print()

    # Build strategy components.
    strategies = _build_strategies()
    combiner = SignalCombiner()

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=Decimal(str(args.capital)),
        warmup_days=args.warmup,
    )

    # Run backtest.
    print("Running backtest...")
    runner = BacktestRunner(strategies, combiner, config)
    result = runner.run(ndx, tqqq, sqqq)

    # Print results.
    print(result.summary())

    # Monthly returns table.
    print("\n  MONTHLY RETURNS")
    print("  " + "-" * 56)
    _print_monthly_returns_table(result.monthly_returns)

    # C2 comparison.
    if args.compare_c2:
        _print_c2_comparison(result.monthly_returns)

    # Save results.
    output_path = _save_results(result, Path(args.output_dir))
    print(f"\n  Results saved to: {output_path}")
    print()


if __name__ == "__main__":
    main()
