#!/usr/bin/env python3
"""Monte Carlo v3 — Production White Light Engine on Historical Slices.

OPTIMIZATION: Pre-computes daily allocations for ALL 4000+ days of history
in a single pass, then slices into random windows for metrics. This avoids
re-running the engine per-sim.

Usage:
    python scripts/monte_carlo_production.py [--sims 500] [--min-years 1] [--max-years 12]
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import warnings
warnings.filterwarnings('ignore')
pd.set_option('future.no_silent_downcasting', True)

logging.getLogger('whitelight').setLevel(logging.WARNING)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.engine import StrategyEngine

CACHE_DIR = PROJECT / "data" / "cache"
OUTPUT_DIR = PROJECT / "data" / "monte_carlo"

ALLOC_CACHE = OUTPUT_DIR / "production_allocations.parquet"


def load_data():
    dfs = {}
    for ticker in ['ndx', 'tqqq', 'sqqq']:
        path = CACHE_DIR / f"{ticker}_daily.parquet"
        df = pd.read_parquet(path)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        dfs[ticker] = df.sort_index()
    return dfs


def precompute_allocations(ndx_df, force=False):
    """Run production engine day-by-day across full history. Cache result."""
    if ALLOC_CACHE.exists() and not force:
        cached = pd.read_parquet(ALLOC_CACHE)
        cached_end = cached.index[-1]
        data_end = ndx_df.index[-1]
        if cached_end >= data_end:
            logger.info("Using cached allocations (%d days, up to %s)", len(cached), cached_end.date())
            return cached
        logger.info("Cache stale (%s vs %s), recomputing...", cached_end.date(), data_end.date())

    logger.info("Pre-computing production allocations for %d days...", len(ndx_df))
    
    strategies = [
        S1PrimaryTrend(), S2IntermediateTrend(), S3ShortTermTrend(),
        S4TrendStrength(), S5MomentumVelocity(), S6MeanRevBollinger(),
        S7VolatilityRegime(),
    ]
    engine = StrategyEngine(strategies=strategies, combiner=SignalCombiner())

    records = []
    t0 = time.time()
    
    # Need ~300 days warmup for indicators
    for i in range(300, len(ndx_df)):
        today = ndx_df.index[i]
        history = ndx_df.iloc[:i+1]
        
        try:
            alloc = engine.evaluate(history)
            records.append({
                'date': today,
                'tqqq_pct': float(alloc.tqqq_pct),
                'sqqq_pct': float(alloc.sqqq_pct),
                'cash_pct': float(alloc.cash_pct),
                'composite': alloc.composite_score,
            })
        except Exception as e:
            records.append({
                'date': today,
                'tqqq_pct': 0.0, 'sqqq_pct': 0.0, 'cash_pct': 1.0, 'composite': 0.0,
            })
        
        if (i - 299) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i - 299) / elapsed if elapsed > 0 else 0
            eta = (len(ndx_df) - i) / rate if rate > 0 else 0
            logger.info("  Day %d/%d (%.0f days/s, ETA %.0fs)", i, len(ndx_df), rate, eta)

    alloc_df = pd.DataFrame(records).set_index('date')
    
    elapsed = time.time() - t0
    logger.info("Pre-computed %d daily allocations in %.1fs (%.0f days/s)", len(alloc_df), elapsed, len(alloc_df)/elapsed)

    # Cache
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    alloc_df.to_parquet(ALLOC_CACHE)
    logger.info("Cached to %s", ALLOC_CACHE)

    return alloc_df


def run_production_mc(n_sims=500, min_years=1, max_years=12, initial_capital=100_000, force_recompute=False):
    dfs = load_data()
    ndx_df, tqqq_df, sqqq_df = dfs['ndx'], dfs['tqqq'], dfs['sqqq']

    # Align dates
    common_start = max(ndx_df.index[0], tqqq_df.index[0], sqqq_df.index[0])
    common_end = min(ndx_df.index[-1], tqqq_df.index[-1], sqqq_df.index[-1])
    ndx_df = ndx_df.loc[common_start:common_end]
    tqqq_df = tqqq_df.loc[common_start:common_end]
    sqqq_df = sqqq_df.loc[common_start:common_end]

    # Step 1: Pre-compute allocations (one-time, cached)
    alloc_df = precompute_allocations(ndx_df, force=force_recompute)

    # Align alloc with price data
    common_idx = alloc_df.index.intersection(tqqq_df.index).intersection(sqqq_df.index)
    common_idx = common_idx.sort_values()
    alloc_df = alloc_df.loc[common_idx]
    tqqq_df = tqqq_df.loc[common_idx]
    sqqq_df = sqqq_df.loc[common_idx]

    # Pre-compute daily returns
    tqqq_rets = tqqq_df['close'].pct_change().fillna(0).values
    sqqq_rets = sqqq_df['close'].pct_change().fillna(0).values
    tqqq_pcts = alloc_df['tqqq_pct'].values
    sqqq_pcts = alloc_df['sqqq_pct'].values
    cash_pcts = alloc_df['cash_pct'].values
    dates = common_idx

    daily_cash_ret = (1 + 0.04) ** (1/252) - 1
    n_total = len(common_idx)

    # Portfolio daily returns (vectorized)
    port_rets = tqqq_pcts * tqqq_rets + sqqq_pcts * sqqq_rets + cash_pcts * daily_cash_ret

    logger.info("Aligned %d trading days with allocations", n_total)
    logger.info("Running %d random slice simulations...", n_sims)

    # Step 2: Random slices — just extract windows from pre-computed returns
    min_days = int(min_years * 252)
    max_days = min(int(max_years * 252), n_total - 1)
    
    rng = np.random.default_rng(42)
    results = []

    BUCKETS = {
        "1-2yr": (252, 504), "2-3yr": (504, 756), "3-5yr": (756, 1260),
        "5-8yr": (1260, 2016), "8-12yr": (2016, 3024),
    }

    t0 = time.time()
    for i in range(n_sims):
        test_days = int(rng.integers(min_days, max_days + 1))
        max_start = n_total - test_days
        if max_start < 1:
            continue
        start = int(rng.integers(0, max_start))
        end = start + test_days

        # Extract window returns
        window_rets = port_rets[start:end]
        
        # Compute cumulative equity
        equity = initial_capital * np.cumprod(1 + window_rets)
        final = equity[-1]
        total_return = final / initial_capital - 1
        n_years = test_days / 252
        cagr = (1 + total_return) ** (1/n_years) - 1 if n_years > 0 and total_return > -1 else -1

        # Max drawdown
        running_max = np.maximum.accumulate(equity)
        drawdowns = (running_max - equity) / running_max
        max_dd = float(np.max(drawdowns))

        # Sharpe
        excess = window_rets - 0.04/252
        sharpe = float(np.mean(excess) / np.std(excess) * np.sqrt(252)) if np.std(excess) > 0 else 0

        # Count allocation regime changes
        window_allocs = tqqq_pcts[start:end]
        states = np.where(window_allocs > 0.5, 2, np.where(sqqq_pcts[start:end] > 0.1, 0, 1))
        trades = int(np.sum(np.diff(states) != 0))

        # Avg TQQQ allocation
        avg_tqqq = float(np.mean(window_allocs))
        avg_sqqq = float(np.mean(sqqq_pcts[start:end]))

        results.append({
            'initial': initial_capital, 'final': float(final),
            'total_return': float(total_return), 'cagr': float(cagr),
            'max_drawdown': max_dd, 'sharpe': sharpe, 'trades': trades,
            'test_days': test_days, 'test_years': n_years,
            'start_date': str(dates[start].date()), 'end_date': str(dates[min(end-1, n_total-1)].date()),
            'avg_tqqq_alloc': avg_tqqq, 'avg_sqqq_alloc': avg_sqqq,
        })

    total_time = time.time() - t0
    logger.info("Simulations: %.2fs for %d slices (%.0f/s)", total_time, len(results), len(results)/total_time)

    overall = _aggregate(results)
    bucket_results = {}
    for bname, (bmin, bmax) in BUCKETS.items():
        bucket = [r for r in results if bmin <= r['test_days'] < bmax]
        if len(bucket) >= 5:
            bucket_results[bname] = _aggregate(bucket)

    output = {
        "version": 3,
        "method": "production_engine_historical_slices",
        "engine": "White Light Production (S1-S7 + vol-targeted combiner + SQQQ sprints)",
        "generated_at": datetime.utcnow().isoformat(),
        "n_sims": len(results),
        "min_years": min_years, "max_years": max_years,
        "historical_period": f"{dates[0].date()} to {dates[-1].date()}",
        "initial_capital": initial_capital,
        "precompute_days": n_total,
        "overall": overall,
        "by_duration": bucket_results,
        "slice_distribution": {bname: len([r for r in results if bmin <= r['test_days'] < bmax])
                               for bname, (bmin, bmax) in BUCKETS.items()},
    }
    return output


def _aggregate(results):
    cagrs = [r['cagr'] for r in results]
    dds = [r['max_drawdown'] for r in results]
    sharpes = [r['sharpe'] for r in results]
    finals = [r['final'] for r in results]
    return {
        "n": len(results),
        "cagr": {
            "mean": float(np.mean(cagrs)), "median": float(np.median(cagrs)),
            "p5": float(np.percentile(cagrs, 5)), "p10": float(np.percentile(cagrs, 10)),
            "p25": float(np.percentile(cagrs, 25)), "p75": float(np.percentile(cagrs, 75)),
            "p90": float(np.percentile(cagrs, 90)), "p95": float(np.percentile(cagrs, 95)),
            "std": float(np.std(cagrs)), "min": float(np.min(cagrs)), "max": float(np.max(cagrs)),
        },
        "max_drawdown": {
            "mean": float(np.mean(dds)), "median": float(np.median(dds)),
            "p5": float(np.percentile(dds, 5)), "p95": float(np.percentile(dds, 95)),
        },
        "sharpe": {
            "mean": float(np.mean(sharpes)), "median": float(np.median(sharpes)),
            "p5": float(np.percentile(sharpes, 5)), "p95": float(np.percentile(sharpes, 95)),
        },
        "final_value": {
            "mean": float(np.mean(finals)), "median": float(np.median(finals)),
            "p5": float(np.percentile(finals, 5)), "p95": float(np.percentile(finals, 95)),
            "min": float(np.min(finals)), "max": float(np.max(finals)),
        },
        "prob_positive": float(np.mean([c > 0 for c in cagrs])),
        "prob_gt_10pct": float(np.mean([c > 0.10 for c in cagrs])),
        "prob_gt_20pct": float(np.mean([c > 0.20 for c in cagrs])),
        "prob_gt_30pct": float(np.mean([c > 0.30 for c in cagrs])),
        "prob_drawdown_gt_50": float(np.mean([d > 0.50 for d in dds])),
    }


def print_results(output):
    print(f"\n{'='*90}")
    print(f"  ⚡ WHITE LIGHT PRODUCTION — MONTE CARLO ({output['n_sims']} historical slices)")
    print(f"  Engine: {output['engine']}")
    print(f"  Data: {output['historical_period']} ({output['precompute_days']} trading days)")
    print(f"{'='*90}")

    def pb(label, data):
        c, d, s, f = data['cagr'], data['max_drawdown'], data['sharpe'], data['final_value']
        print(f"\n  ── {label} ({data['n']} slices) ──")
        print(f"  CAGR:     {c['median']*100:>6.1f}% median  |  P5={c['p5']*100:.1f}%  P25={c['p25']*100:.1f}%  P75={c['p75']*100:.1f}%  P95={c['p95']*100:.1f}%")
        print(f"  Max DD:   {d['median']*100:>6.1f}% median  |  P5={d['p5']*100:.1f}%  P95={d['p95']*100:.1f}%")
        print(f"  Sharpe:   {s['median']:>6.2f} median   |  P5={s['p5']:.2f}  P95={s['p95']:.2f}")
        print(f"  $100K →   ${f['median']:>10,.0f} median  |  ${f['p5']:>10,.0f} – ${f['p95']:>10,.0f}")
        print(f"  P(+)={data['prob_positive']*100:.0f}%  P(>10%)={data['prob_gt_10pct']*100:.0f}%  P(>20%)={data['prob_gt_20pct']*100:.0f}%  P(>30%)={data['prob_gt_30pct']*100:.0f}%  P(DD>50%)={data['prob_drawdown_gt_50']*100:.0f}%")

    pb("OVERALL", output['overall'])
    for b in ['1-2yr','2-3yr','3-5yr','5-8yr','8-12yr']:
        if b in output['by_duration']:
            pb(b.upper(), output['by_duration'][b])

    # $20K projection
    print(f"\n{'='*90}")
    print(f"  💰 $20K PROJECTION")
    print(f"{'='*90}")
    for b in ['3-5yr','5-8yr','8-12yr']:
        if b in output['by_duration']:
            c = output['by_duration'][b]['cagr']
            yrs = {'3-5yr':4,'5-8yr':6.5,'8-12yr':10}[b]
            for lbl, key in [("Worst P5",  "p5"), ("Median", "median"), ("Best P95", "p95")]:
                val = 20_000 * (1 + c[key]) ** yrs
                print(f"  {b} {lbl:12s}: {c[key]*100:>5.1f}% → ${val:>10,.0f}")
            print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sims", type=int, default=500)
    parser.add_argument("--min-years", type=float, default=1)
    parser.add_argument("--max-years", type=float, default=12)
    parser.add_argument("--force", action="store_true", help="Force recompute allocations")
    args = parser.parse_args()

    output = run_production_mc(n_sims=args.sims, min_years=args.min_years, 
                                max_years=args.max_years, force_recompute=args.force)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    out_path = OUTPUT_DIR / f"mc_production_{ts}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    latest = OUTPUT_DIR / "mc_production_latest.json"
    with open(latest, "w") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info("Saved to %s", out_path)
    print_results(output)


if __name__ == "__main__":
    main()
