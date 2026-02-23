#!/usr/bin/env python3
"""Monte Carlo v2 — Historical Slice Sampling.

Instead of generating synthetic market paths, samples random time slices
from actual TQQQ history. Each simulation picks a random start date and
random duration, then runs every strategy on that identical real slice.

This preserves regime structure, autocorrelation, and realistic whipsaw
behavior that block bootstrap destroys.

Usage:
    python scripts/monte_carlo_v2.py [--sims 500] [--min-years 1] [--max-years 10]
"""

import argparse
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import warnings
warnings.filterwarnings('ignore')
pd.set_option('future.no_silent_downcasting', True)

try:
    import vectorbt as vbt
    HAS_VBT = True
except ImportError:
    HAS_VBT = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT / "data" / "cache"
DB_PATH = PROJECT / "data" / "strategies.db"
OUTPUT_DIR = PROJECT / "data" / "monte_carlo"


# ── Strategy Implementations ──────────────────────────────────────

def _rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _sma_cross(df, fast, slow):
    f = df["close"].rolling(fast, min_periods=max(5, fast//4)).mean()
    s = df["close"].rolling(slow, min_periods=max(10, slow//4)).mean()
    entries = (f > s) & (f.shift(1) <= s.shift(1))
    exits = (f < s) & (f.shift(1) >= s.shift(1))
    return entries.fillna(False), exits.fillna(False)

def _ema_cross(df, fast, slow):
    f = df["close"].ewm(span=fast, adjust=False).mean()
    s = df["close"].ewm(span=slow, adjust=False).mean()
    entries = (f > s) & (f.shift(1) <= s.shift(1))
    exits = (f < s) & (f.shift(1) >= s.shift(1))
    return entries.fillna(False), exits.fillna(False)

def _triple_ema(df):
    e8 = df["close"].ewm(span=8, adjust=False).mean()
    e21 = df["close"].ewm(span=21, adjust=False).mean()
    e55 = df["close"].ewm(span=55, adjust=False).mean()
    bull = (e8 > e21) & (e21 > e55)
    entries = bull & ~bull.shift(1).fillna(False)
    exits = (e8 < e21) & ~(e8.shift(1) < e21.shift(1)).fillna(False)
    return entries.fillna(False), exits.fillna(False)

def _donchian(df, period=20):
    high_n = df["high"].rolling(period).max()
    low_n = df["low"].rolling(period).min()
    entries = df["close"] > high_n.shift(1)
    exits = df["close"] < low_n.shift(1)
    return entries.fillna(False), exits.fillna(False)

def _macd_cross(df):
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    entries = (macd > signal) & (macd.shift(1) <= signal.shift(1))
    exits = (macd < signal) & (macd.shift(1) >= signal.shift(1))
    return entries.fillna(False), exits.fillna(False)

def _adx_trend(df, period=14, threshold=25):
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(period).mean()
    bull = (adx > threshold) & (plus_di > minus_di)
    entries = bull & ~bull.shift(1).fillna(False)
    exits = (plus_di < minus_di) & (plus_di.shift(1) >= minus_di.shift(1))
    return entries.fillna(False), exits.fillna(False)

def _rsi_momentum(df):
    rsi = _rsi(df, 14)
    entries = (rsi > 50) & (rsi.shift(1) <= 50)
    exits = (rsi < 50) & (rsi.shift(1) >= 50)
    return entries.fillna(False), exits.fillna(False)

def _momentum_breakout(df, period=20):
    ret = df["close"].pct_change(period)
    entries = (ret > 0.1) & (ret.shift(1) <= 0.1)
    exits = (ret < 0) & (ret.shift(1) >= 0)
    return entries.fillna(False), exits.fillna(False)

def _dual_momentum(df, lookback=63):
    mom = df["close"].pct_change(lookback)
    sma200 = df["close"].rolling(200, min_periods=50).mean()
    bull = (mom > 0) & (df["close"] > sma200)
    entries = bull & ~bull.shift(1).fillna(False)
    bear = (mom < 0) | (df["close"] < sma200)
    exits = bear & ~bear.shift(1).fillna(False)
    return entries.fillna(False), exits.fillna(False)

def _williams_r(df, period=14):
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    wr = -100 * (hh - df["close"]) / (hh - ll)
    entries = (wr > -20) & (wr.shift(1) <= -20)
    exits = (wr < -80) & (wr.shift(1) >= -80)
    return entries.fillna(False), exits.fillna(False)

def _rsi_mean_rev(df):
    rsi = _rsi(df, 14)
    entries = (rsi < 30) & (rsi.shift(1) >= 30)
    exits = (rsi > 70) & (rsi.shift(1) <= 70)
    return entries.fillna(False), exits.fillna(False)

def _bollinger_mean_rev(df, period=20, std=2):
    sma = df["close"].rolling(period).mean()
    bb_std = df["close"].rolling(period).std()
    upper = sma + std * bb_std
    lower = sma - std * bb_std
    entries = (df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))
    exits = (df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))
    return entries.fillna(False), exits.fillna(False)

def _mean_rev_sma(df, period=20, threshold=0.05):
    sma = df["close"].rolling(period).mean()
    deviation = (df["close"] - sma) / sma
    entries = (deviation < -threshold) & (deviation.shift(1) >= -threshold)
    exits = (deviation > threshold) & (deviation.shift(1) <= threshold)
    return entries.fillna(False), exits.fillna(False)

def _atr_breakout(df, period=14, mult=2.0):
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    sma = df["close"].rolling(period).mean()
    entries = (df["close"] > sma + mult * atr) & (df["close"].shift(1) <= (sma + mult * atr).shift(1))
    exits = (df["close"] < sma - mult * atr) & (df["close"].shift(1) >= (sma - mult * atr).shift(1))
    return entries.fillna(False), exits.fillna(False)

def _keltner(df, period=20, mult=1.5):
    ema = df["close"].ewm(span=period, adjust=False).mean()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    entries = (df["close"] > ema + mult * atr) & (df["close"].shift(1) <= (ema + mult * atr).shift(1))
    exits = (df["close"] < ema - mult * atr) & (df["close"].shift(1) >= (ema - mult * atr).shift(1))
    return entries.fillna(False), exits.fillna(False)

def _trend_mom_combo(df):
    sma50 = df["close"].rolling(50, min_periods=10).mean()
    sma200 = df["close"].rolling(200, min_periods=50).mean()
    rsi = _rsi(df, 14)
    trend_up = (sma50 > sma200).fillna(False)
    bull = trend_up & (rsi > 50)
    entries = bull & ~bull.shift(1).fillna(False)
    bear = (~trend_up) & (rsi < 50)
    exits = bear & ~bear.shift(1).fillna(False)
    return entries.fillna(False), exits.fillna(False)

def _macd_rsi_combo(df):
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    rsi = _rsi(df, 14)
    bull = (macd > signal) & (rsi > 40)
    entries = bull & ~bull.shift(1).fillna(False)
    bear = (macd < signal) & (rsi < 60)
    exits = bear & ~bear.shift(1).fillna(False)
    return entries.fillna(False), exits.fillna(False)

def _white_light(df):
    """White Light v2 conservative — vol-adaptive SMA + RSI + ATR regime."""
    sma50 = df["close"].rolling(50, min_periods=10).mean()
    sma200 = df["close"].rolling(200, min_periods=50).mean()
    rsi = _rsi(df, 14)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    lookback = min(252, max(60, len(df) // 4))
    atr_pct = atr.rolling(lookback, min_periods=30).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    high_vol = atr_pct.fillna(0.5) > 0.7

    bull = (df["close"] > sma200) & (sma50 > sma200) & (rsi > 40) & (~high_vol)
    entries = bull & ~bull.shift(1).fillna(False)
    bear = (df["close"] < sma200) | ((rsi > 75) & high_vol)
    exits = bear & ~bear.shift(1).fillna(False)
    return entries.fillna(False), exits.fillna(False)


STRATEGY_FNS = {
    1: ("sma_crossover_50_200", "trend-following", lambda df: _sma_cross(df, 50, 200)),
    2: ("sma_crossover_20_50", "trend-following", lambda df: _sma_cross(df, 20, 50)),
    3: ("ema_crossover_9_21", "trend-following", lambda df: _ema_cross(df, 9, 21)),
    4: ("triple_ema", "trend-following", _triple_ema),
    5: ("donchian_breakout_20", "trend-following", _donchian),
    6: ("macd_crossover", "trend-following", _macd_cross),
    7: ("adx_trend", "trend-following", _adx_trend),
    8: ("rsi_momentum", "momentum", _rsi_momentum),
    9: ("momentum_breakout", "momentum", _momentum_breakout),
    10: ("dual_momentum", "momentum", _dual_momentum),
    11: ("williams_r_momentum", "momentum", _williams_r),
    12: ("rsi_mean_reversion", "mean-reversion", _rsi_mean_rev),
    13: ("bollinger_mean_reversion", "mean-reversion", _bollinger_mean_rev),
    14: ("mean_reversion_sma", "mean-reversion", _mean_rev_sma),
    15: ("atr_breakout", "volatility", _atr_breakout),
    16: ("keltner_channel_breakout", "volatility", _keltner),
    17: ("trend_momentum_combo", "composite", _trend_mom_combo),
    18: ("macd_rsi_combo", "composite", _macd_rsi_combo),
    19: ("white_light", "composite", _white_light),
}

# Duration buckets for grouping results
BUCKETS = {
    "1-2yr": (252, 504),
    "2-3yr": (504, 756),
    "3-5yr": (756, 1260),
    "5-8yr": (1260, 2016),
    "8-12yr": (2016, 3024),
}


def load_historical() -> pd.DataFrame:
    path = CACHE_DIR / "tqqq_daily.parquet"
    df = pd.read_parquet(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    return df.sort_index()


def generate_slices(
    hist_df: pd.DataFrame,
    n_sims: int,
    min_days: int,
    max_days: int,
    warmup: int = 300,
    rng: np.random.Generator = None,
) -> list[tuple[pd.DataFrame, str, str, int]]:
    """Generate random historical slices.
    
    Each slice includes `warmup` extra days before the test window
    for indicator warmup. Returns (full_df_with_warmup, test_start, test_end, test_days).
    """
    if rng is None:
        rng = np.random.default_rng()

    n_total = len(hist_df)
    # Clamp max_days to available data minus warmup
    effective_max = min(max_days, n_total - warmup - 1)
    if effective_max < min_days:
        effective_max = min_days

    slices = []
    for _ in range(n_sims):
        # Random duration
        test_days = int(rng.integers(min_days, effective_max + 1))
        # Random start (must leave room for warmup before and test_days after)
        max_start = n_total - test_days
        min_start = warmup
        if max_start <= min_start:
            max_start = min_start + 1
        start_idx = int(rng.integers(min_start, max_start))

        # Extract slice with warmup
        warmup_start = max(0, start_idx - warmup)
        full_slice = hist_df.iloc[warmup_start:start_idx + test_days].copy()

        test_start = str(hist_df.index[start_idx].date())
        test_end = str(hist_df.index[min(start_idx + test_days - 1, n_total - 1)].date())

        slices.append((full_slice, test_start, test_end, test_days, start_idx))

    return slices


def run_strategy_on_slice(strategy_fn, full_df, start_idx_in_slice, test_days, initial_capital=100_000):
    """Run strategy on full slice but measure performance only on test window."""
    try:
        entries, exits = strategy_fn(full_df)
        entries = pd.Series(entries, index=full_df.index).fillna(False).astype(bool)
        exits = pd.Series(exits, index=full_df.index).fillna(False).astype(bool)

        # Run on full slice (signals need warmup context)
        pf = vbt.Portfolio.from_signals(
            close=full_df["close"], entries=entries, exits=exits,
            init_cash=initial_capital, freq="1D",
        )

        # Measure only the test window
        test_df = full_df.iloc[start_idx_in_slice:]
        test_entries = entries.iloc[start_idx_in_slice:]
        test_exits = exits.iloc[start_idx_in_slice:]

        if test_entries.sum() < 1:
            # No signals in test window — treat as cash (0% return)
            return {"cagr": 0, "total_return": 0, "max_drawdown": 0,
                    "sharpe": 0, "total_trades": 0, "final_value": initial_capital, "error": None}

        test_pf = vbt.Portfolio.from_signals(
            close=test_df["close"], entries=test_entries, exits=test_exits,
            init_cash=initial_capital, freq="1D",
        )

        total_ret = float(test_pf.total_return())
        n_years = len(test_df) / 252
        cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 and total_ret > -1 else -1
        max_dd = abs(float(test_pf.max_drawdown()))

        rets = test_pf.returns()
        excess = rets - 0.04 / 252
        sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

        trades = test_pf.trades.records_readable if len(test_pf.trades.records) > 0 else pd.DataFrame()

        return {
            "cagr": cagr, "total_return": total_ret, "max_drawdown": max_dd,
            "sharpe": sharpe, "total_trades": len(trades),
            "final_value": initial_capital * (1 + total_ret), "error": None,
        }
    except Exception as e:
        return {"cagr": 0, "total_return": 0, "max_drawdown": 0,
                "sharpe": 0, "total_trades": 0, "final_value": 100_000, "error": str(e)}


def run_monte_carlo_v2(n_sims=500, min_years=1, max_years=12, initial_capital=100_000):
    if not HAS_VBT:
        raise ImportError("vectorbt required")

    hist_df = load_historical()
    logger.info("Loaded %d days of TQQQ history (%s to %s)",
                len(hist_df), hist_df.index[0].date(), hist_df.index[-1].date())

    rng = np.random.default_rng(42)
    min_days = min_years * 252
    max_days = min(max_years * 252, len(hist_df) - 300)

    # Generate all slices upfront
    logger.info("Generating %d random historical slices (%d-%d trading days)...",
                n_sims, min_days, max_days)
    slices = generate_slices(hist_df, n_sims, min_days, max_days, warmup=300, rng=rng)

    # Log slice distribution
    bucket_counts = {b: 0 for b in BUCKETS}
    for _, _, _, td, _ in slices:
        for bname, (bmin, bmax) in BUCKETS.items():
            if bmin <= td < bmax:
                bucket_counts[bname] += 1
                break
    logger.info("Slice distribution: %s", 
                ", ".join(f"{k}: {v}" for k, v in bucket_counts.items()))

    # Compute warmup length for each slice
    slice_data = []
    for full_df, test_start, test_end, test_days, orig_start_idx in slices:
        warmup_len = len(full_df) - test_days  # how many warmup rows
        slice_data.append((full_df, test_start, test_end, test_days, warmup_len))

    # Run all strategies on all slices
    all_results = {}  # strategy_name -> list of result dicts
    
    for sid, (name, category, sfn) in STRATEGY_FNS.items():
        t0 = time.time()
        results = []

        for full_df, test_start, test_end, test_days, warmup_len in slice_data:
            r = run_strategy_on_slice(sfn, full_df, warmup_len, test_days, initial_capital)
            r["test_start"] = test_start
            r["test_end"] = test_end
            r["test_days"] = test_days
            r["test_years"] = test_days / 252
            results.append(r)

        elapsed = time.time() - t0
        valid = [r for r in results if r["error"] is None]
        cagrs = [r["cagr"] for r in valid]
        
        if cagrs:
            logger.info("  %s: median CAGR %.1f%%, median DD %.1f%%, P(+) %.0f%%, errors %d [%.1fs]",
                        name, np.median(cagrs)*100,
                        np.median([r["max_drawdown"] for r in valid])*100,
                        np.mean([c > 0 for c in cagrs])*100,
                        len(results) - len(valid), elapsed)
        else:
            logger.warning("  %s: all sims failed [%.1fs]", name, elapsed)

        all_results[name] = {
            "strategy_id": sid,
            "name": name,
            "category": category,
            "results": results,
        }

    # Aggregate by duration bucket + overall
    leaderboard = {}
    
    # Overall
    leaderboard["overall"] = _aggregate_bucket(all_results, None, None)
    
    # By bucket
    for bname, (bmin, bmax) in BUCKETS.items():
        lb = _aggregate_bucket(all_results, bmin, bmax)
        if lb:
            leaderboard[bname] = lb

    output = {
        "version": 2,
        "method": "historical_slice_sampling",
        "generated_at": datetime.utcnow().isoformat(),
        "n_sims": n_sims,
        "min_years": min_years,
        "max_years": max_years,
        "historical_period": f"{hist_df.index[0].date()} to {hist_df.index[-1].date()}",
        "initial_capital": initial_capital,
        "slice_distribution": bucket_counts,
        "leaderboard": leaderboard,
    }

    return output


def _aggregate_bucket(all_results, min_days, max_days):
    """Aggregate results for a duration bucket (or all if None)."""
    ranked = []
    
    for name, data in all_results.items():
        if min_days is not None:
            valid = [r for r in data["results"] 
                     if r["error"] is None and min_days <= r["test_days"] < max_days]
        else:
            valid = [r for r in data["results"] if r["error"] is None]

        if len(valid) < 5:
            continue

        cagrs = [r["cagr"] for r in valid]
        dds = [r["max_drawdown"] for r in valid]
        sharpes = [r["sharpe"] for r in valid]
        finals = [r["final_value"] for r in valid]

        # Risk-adjusted composite: 35% CAGR, 25% Sharpe, 25% inverse DD, 15% consistency
        cagr_score = min(max(np.median(cagrs) / 0.30, 0), 1)
        sharpe_score = min(max(np.median(sharpes) / 2.0, 0), 1)
        dd_score = max(1.0 - np.median(dds) / 0.60, 0)
        consistency = np.mean([c > 0 for c in cagrs])  # prob of positive return

        composite = 0.35 * cagr_score + 0.25 * sharpe_score + 0.25 * dd_score + 0.15 * consistency

        ranked.append({
            "strategy_id": data["strategy_id"],
            "name": name,
            "category": data["category"],
            "n_sims": len(valid),
            "cagr": {
                "mean": float(np.mean(cagrs)),
                "median": float(np.median(cagrs)),
                "p5": float(np.percentile(cagrs, 5)),
                "p25": float(np.percentile(cagrs, 25)),
                "p75": float(np.percentile(cagrs, 75)),
                "p95": float(np.percentile(cagrs, 95)),
                "std": float(np.std(cagrs)),
            },
            "max_drawdown": {
                "mean": float(np.mean(dds)),
                "median": float(np.median(dds)),
                "p5": float(np.percentile(dds, 5)),
                "p95": float(np.percentile(dds, 95)),
            },
            "sharpe": {
                "mean": float(np.mean(sharpes)),
                "median": float(np.median(sharpes)),
                "p5": float(np.percentile(sharpes, 5)),
                "p95": float(np.percentile(sharpes, 95)),
            },
            "final_value": {
                "mean": float(np.mean(finals)),
                "median": float(np.median(finals)),
                "p5": float(np.percentile(finals, 5)),
                "p95": float(np.percentile(finals, 95)),
                "min": float(np.min(finals)),
                "max": float(np.max(finals)),
            },
            "prob_positive": float(np.mean([c > 0 for c in cagrs])),
            "prob_gt_10pct": float(np.mean([c > 0.10 for c in cagrs])),
            "prob_gt_20pct": float(np.mean([c > 0.20 for c in cagrs])),
            "prob_drawdown_gt_50": float(np.mean([d > 0.50 for d in dds])),
            "prob_drawdown_gt_70": float(np.mean([d > 0.70 for d in dds])),
            "mc_composite": round(composite, 4),
        })

    ranked.sort(key=lambda x: x["mc_composite"], reverse=True)
    for i, r in enumerate(ranked):
        r["rank"] = i + 1

    return ranked


def print_leaderboard(results):
    for bucket_name, ranked in results["leaderboard"].items():
        n = ranked[0]["n_sims"] if ranked else 0
        print(f"\n{'='*110}")
        print(f"  MONTE CARLO v2 — {bucket_name.upper()} ({n} slices from real TQQQ history)")
        print(f"{'='*110}")
        print(f"{'Rank':>4} {'Strategy':<30} {'Score':>6} {'Med CAGR':>9} {'P5–P95 CAGR':>16} "
              f"{'Med DD':>8} {'Sharpe':>7} {'P(+)':>6} {'P(>20%)':>8}")
        print(f"{'─'*4} {'─'*30} {'─'*6} {'─'*9} {'─'*16} {'─'*8} {'─'*7} {'─'*6} {'─'*8}")
        for r in ranked:
            c = r["cagr"]
            print(f"{r['rank']:4d} {r['name']:<30} {r['mc_composite']:.3f} "
                  f"{c['median']*100:>8.1f}% {c['p5']*100:>6.1f}–{c['p95']*100:>5.1f}% "
                  f"{r['max_drawdown']['median']*100:>7.1f}% {r['sharpe']['median']:>6.2f} "
                  f"{r['prob_positive']*100:>5.0f}% {r['prob_gt_20pct']*100:>7.0f}%")

    # Key insights
    print(f"\n{'='*110}")
    print("  KEY INSIGHTS")
    print(f"{'='*110}")
    overall = results["leaderboard"].get("overall", [])
    if overall:
        top = overall[0]
        print(f"\n  Overall #1: {top['name']} — {top['cagr']['median']*100:.1f}% median CAGR, "
              f"{top['prob_positive']*100:.0f}% chance of profit across {top['n_sims']} random time slices")
        
        # Find White Light
        for r in overall:
            if r["name"] == "white_light":
                print(f"\n  White Light: #{r['rank']} — {r['cagr']['median']*100:.1f}% median CAGR, "
                      f"{r['max_drawdown']['median']*100:.1f}% median DD, "
                      f"{r['prob_positive']*100:.0f}% chance of profit")
                break


def main():
    parser = argparse.ArgumentParser(description="Monte Carlo v2 — Historical Slice Sampling")
    parser.add_argument("--sims", type=int, default=500, help="Number of random slices")
    parser.add_argument("--min-years", type=float, default=1, help="Minimum slice duration in years")
    parser.add_argument("--max-years", type=float, default=12, help="Maximum slice duration in years")
    args = parser.parse_args()

    logger.info("Monte Carlo v2: %d slices × %d strategies = %d backtests on REAL historical data",
                args.sims, len(STRATEGY_FNS), args.sims * len(STRATEGY_FNS))

    results = run_monte_carlo_v2(
        n_sims=args.sims,
        min_years=args.min_years,
        max_years=args.max_years,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"mc_v2_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    latest_path = OUTPUT_DIR / "mc_v2_latest.json"
    with open(latest_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    logger.info("Results saved to %s", out_path)
    print_leaderboard(results)


if __name__ == "__main__":
    main()
