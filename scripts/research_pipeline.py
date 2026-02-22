#!/usr/bin/env python3
"""White Light Strategy Research Pipeline.

Discover → Extract → Convert → Backtest → Rank

Usage:
    python scripts/research_pipeline.py --source tradingview --category trend-following --limit 10
    python scripts/research_pipeline.py --source tradingview --category momentum --limit 20
    python scripts/research_pipeline.py --source reddit --limit 10
    python scripts/research_pipeline.py --rank  # Show top strategies from DB
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from whitelight.research.database import StrategyDB
from whitelight.research.discovery import (
    discover_tradingview,
    extract_pine_script,
    discover_reddit,
    extract_reddit_code,
)
from whitelight.research.converter import convert_strategy
from whitelight.research.evaluator import evaluate_strategy


def _print_table(rows: list[dict], columns: list[tuple[str, str, int]]) -> None:
    """Print a formatted table."""
    header = "  ".join(f"{title:<{width}}" for title, _, width in columns)
    print(f"  {header}")
    print("  " + "-" * len(header))
    for row in rows:
        line = "  ".join(
            f"{str(row.get(key, '')):<{width}}" for _, key, width in columns
        )
        print(f"  {line}")


def run_pipeline(
    source: str,
    category: str = "trend-following",
    limit: int = 10,
    db_path: str = "data/strategies.db",
    ticker: str = "TQQQ",
) -> None:
    """Execute the full research pipeline."""
    db = StrategyDB(db_path)

    print("\n" + "=" * 70)
    print("  WHITE LIGHT STRATEGY RESEARCH PIPELINE")
    print("=" * 70)
    print(f"  Source:   {source}")
    print(f"  Category: {category}")
    print(f"  Limit:    {limit}")
    print(f"  Ticker:   {ticker}")
    print("=" * 70)

    # ── Stage 1: Discover ──
    print("\n📡 Stage 1: DISCOVER")
    print("-" * 40)

    if source == "tradingview":
        discovered = discover_tradingview(db, category=category, limit=limit)
    elif source == "reddit":
        discovered = discover_reddit(db, limit=limit)
    else:
        print(f"Unknown source: {source}")
        return

    print(f"  Found {len(discovered)} strategies")

    if not discovered:
        print("  No new strategies found. Try a different category or increase limit.")
        return

    # ── Stage 2: Extract ──
    print("\n🔍 Stage 2: EXTRACT")
    print("-" * 40)

    extracted = 0
    for strat in discovered:
        sid = strat["id"]
        url = strat["url"]

        if source == "tradingview":
            pine = extract_pine_script(db, sid, url)
        else:
            pine = extract_reddit_code(db, sid, url)

        if pine:
            extracted += 1
            print(f"  ✅ #{sid}: {strat['name'][:50]}")
        else:
            print(f"  ❌ #{sid}: {strat['name'][:50]} (extraction failed)")

        time.sleep(3)  # Rate limit

    print(f"\n  Extracted: {extracted}/{len(discovered)}")

    if extracted == 0:
        print("  No scripts could be extracted. Some may be protected/invite-only.")
        return

    # ── Stage 3: Convert ──
    print("\n🔄 Stage 3: CONVERT (Pine Script → Python)")
    print("-" * 40)

    converted = 0
    strategies_with_code = db.get_strategies(status="extracted")

    for strat in strategies_with_code:
        sid = strat["id"]
        pine = strat["pine_script"]

        if not pine:
            continue

        python_code = convert_strategy(
            db, sid, pine,
            name=strat["name"],
            source_url=strat.get("source_url", ""),
        )

        if python_code:
            converted += 1
            print(f"  ✅ #{sid}: {strat['name'][:50]}")
        else:
            print(f"  ❌ #{sid}: {strat['name'][:50]} (conversion failed)")

    print(f"\n  Converted: {converted}/{len(strategies_with_code)}")

    if converted == 0:
        print("  No strategies could be converted. May need manual review.")
        return

    # ── Stage 4: Backtest ──
    print("\n📊 Stage 4: BACKTEST (VectorBT)")
    print("-" * 40)

    tested = 0
    passed = 0
    strategies_to_test = db.get_strategies(status="converted")

    for strat in strategies_to_test:
        sid = strat["id"]
        code = strat["python_code"]

        if not code:
            continue

        metrics = evaluate_strategy(db, sid, code, ticker=ticker)

        if metrics:
            tested += 1
            score = metrics["composite_score"]
            sharpe = metrics["sharpe_ratio"]
            passes = metrics.get("passes_thresholds", False)

            status = "✅ PASS" if passes else "⚠️"
            print(f"  {status} #{sid}: {strat['name'][:40]} | Score: {score:.3f} | Sharpe: {sharpe:.2f}")

            if passes:
                passed += 1
        else:
            print(f"  ❌ #{sid}: {strat['name'][:40]} (backtest failed)")

    print(f"\n  Tested: {tested}, Passed: {passed}")

    # ── Stage 5: Rank ──
    print("\n🏆 Stage 5: RANKINGS")
    print("-" * 40)
    show_rankings(db)

    db.close()


def show_rankings(db: StrategyDB | None = None, db_path: str = "data/strategies.db") -> None:
    """Display top-ranked strategies."""
    if db is None:
        db = StrategyDB(db_path)
        should_close = True
    else:
        should_close = False

    top = db.get_top_strategies(limit=20)

    if not top:
        print("  No tested strategies yet.")
        if should_close:
            db.close()
        return

    print(f"\n  {'#':<4} {'Score':<8} {'Sharpe':<8} {'Calmar':<8} {'MaxDD':<8} {'PF':<8} {'Trades':<8} {'CAGR':<8} {'Name'}")
    print("  " + "-" * 90)

    for i, s in enumerate(top, 1):
        score = s.get("composite_score", 0) or 0
        sharpe = s.get("sharpe_ratio", 0) or 0
        calmar = s.get("calmar_ratio", 0) or 0
        max_dd = s.get("max_drawdown", 0) or 0
        pf = s.get("profit_factor", 0) or 0
        trades = s.get("total_trades", 0) or 0
        cagr = s.get("annual_return", 0) or 0
        name = s.get("name", "?")[:30]

        print(
            f"  {i:<4} {score:<8.3f} {sharpe:<8.2f} {calmar:<8.2f} "
            f"{max_dd:<8.1%} {pf:<8.2f} {trades:<8} {cagr:<8.1%} {name}"
        )

    if should_close:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="White Light Strategy Research Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--source",
        choices=["tradingview", "reddit"],
        default="tradingview",
        help="Strategy source. Default: tradingview",
    )
    parser.add_argument(
        "--category",
        default="trend-following",
        help="TradingView category filter. Default: trend-following",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Max strategies to discover. Default: 10",
    )
    parser.add_argument(
        "--ticker",
        default="TQQQ",
        help="Ticker to backtest against. Default: TQQQ",
    )
    parser.add_argument(
        "--db",
        default="data/strategies.db",
        help="Database path. Default: data/strategies.db",
    )
    parser.add_argument(
        "--rank",
        action="store_true",
        help="Just show current rankings (no new discovery)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.rank:
        show_rankings(db_path=args.db)
    else:
        run_pipeline(
            source=args.source,
            category=args.category,
            limit=args.limit,
            db_path=args.db,
            ticker=args.ticker,
        )


if __name__ == "__main__":
    main()
