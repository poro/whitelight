#!/usr/bin/env python3
"""Run the REAL White Light backtest engine with v1 and v2 combiners across multiple periods."""

from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from whitelight.backtest.runner import BacktestConfig, BacktestRunner
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.combiner_v2 import SignalCombinerV2
from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime

OUT_DIR = _PROJECT_ROOT / "data" / "research"
OUT_DIR.mkdir(exist_ok=True)

# --- Data loading (yfinance) ---
def load_data():
    """Load NDX, TQQQ, SQQQ via yfinance."""
    import yfinance as yf
    
    tickers = {"NDX": "^NDX", "TQQQ": "TQQQ", "SQQQ": "SQQQ"}
    data = {}
    for name, symbol in tickers.items():
        df = yf.download(symbol, start="2010-01-01", progress=False)
        if hasattr(df.columns, 'droplevel'):
            try:
                df.columns = df.columns.droplevel(1)
            except Exception:
                pass
        df.columns = [c.lower() for c in df.columns]
        df.index.name = "date"
        data[name] = df
        print(f"  Loaded {name}: {len(df)} rows ({df.index[0].date()} to {df.index[-1].date()})")
    
    return data


def build_strategies():
    return [
        S1PrimaryTrend(),
        S2IntermediateTrend(),
        S3ShortTermTrend(),
        S4TrendStrength(),
        S5MomentumVelocity(),
        S6MeanRevBollinger(),
        S7VolatilityRegime(),
    ]


PERIODS = {
    "1yr": ("2025-02-20", None),
    "2yr": ("2024-02-20", None),
    "3_5yr": ("2022-07-23", None),
    "covid": ("2020-01-02", "2021-12-31"),
    "bear_2022": ("2022-01-03", "2022-10-31"),
    "bull_2023_24": ("2022-11-01", "2024-12-31"),
    "5yr": ("2021-02-20", None),
    "6yr": ("2020-01-02", None),
    "max": ("2011-02-11", None),
}

COMBINERS = {
    "v1_production": lambda: SignalCombiner(),
    "v2_voladaptive": lambda: SignalCombinerV2(),
}


def run_backtest(data, start_str, end_str, combiner_factory, label):
    """Run a single backtest and return metrics dict."""
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str) if end_str else date.today()
    
    config = BacktestConfig(start_date=start, end_date=end, initial_capital=Decimal("100000"))
    strategies = build_strategies()
    combiner = combiner_factory()
    
    runner = BacktestRunner(strategies=strategies, combiner=combiner, backtest_config=config)
    
    try:
        result = runner.run(
            ndx_data=data["NDX"],
            tqqq_data=data["TQQQ"],
            sqqq_data=data["SQQQ"],
        )
    except Exception as e:
        print(f"    ❌ {label}: {e}")
        return None
    
    m = result.metrics
    final = float(result.daily_snapshots[-1].portfolio_value) if result.daily_snapshots else 100000
    
    return {
        "label": label,
        "start": str(start),
        "end": str(end),
        "final": round(final, 0),
        "cagr": round(m.get("annual_return", 0) * 100, 2),
        "max_dd": round(m.get("max_drawdown", 0) * 100, 2),
        "sharpe": round(m.get("sharpe_ratio", 0), 3),
        "sortino": round(m.get("sortino_ratio", 0), 3),
        "calmar": round(m.get("calmar_ratio", 0), 3),
        "pf": round(m.get("profit_factor", 0), 2),
        "trades": m.get("total_trades", 0),
        "win_rate": round(m.get("win_rate", 0) * 100, 1),
        "avg_duration": round(m.get("avg_trade_duration", 0), 1),
    }


def main():
    print("Loading data...")
    data = load_data()
    
    all_results = {}
    
    for period_name, (start, end) in PERIODS.items():
        print(f"\n{'='*80}")
        print(f"PERIOD: {period_name} ({start} → {end or 'today'})")
        print(f"{'='*80}")
        
        period_results = {}
        
        for combiner_name, factory in COMBINERS.items():
            label = f"{combiner_name}"
            print(f"  Running {label}...")
            result = run_backtest(data, start, end, factory, label)
            if result:
                period_results[combiner_name] = result
                print(f"    ✅ CAGR={result['cagr']}% MaxDD={result['max_dd']}% Sharpe={result['sharpe']} Final=${result['final']:,.0f} Trades={result['trades']}")
        
        all_results[period_name] = period_results
    
    # Summary
    print(f"\n\n{'='*120}")
    print("SUMMARY: Real Production Engine — v1 vs v2")
    print(f"{'='*120}")
    print(f"\n{'Period':15s} | {'v1 CAGR':>8s} {'v1 DD':>8s} {'v1 Sharpe':>10s} {'v1 Final':>12s} | {'v2 CAGR':>8s} {'v2 DD':>8s} {'v2 Sharpe':>10s} {'v2 Final':>12s} | {'ΔCAGR':>7s}")
    print("-"*120)
    for period_name, results in all_results.items():
        v1 = results.get("v1_production", {})
        v2 = results.get("v2_voladaptive", {})
        dcagr = (v2.get('cagr', 0) or 0) - (v1.get('cagr', 0) or 0)
        print(f"{period_name:15s} | {v1.get('cagr',0):>7.1f}% {v1.get('max_dd',0):>7.1f}% {v1.get('sharpe',0):>10.3f} ${v1.get('final',0):>10,.0f} | {v2.get('cagr',0):>7.1f}% {v2.get('max_dd',0):>7.1f}% {v2.get('sharpe',0):>10.3f} ${v2.get('final',0):>10,.0f} | {dcagr:>+6.1f}%")
    
    # Save
    with open(OUT_DIR / "v1_vs_v2_real.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved to {OUT_DIR / 'v1_vs_v2_real.json'}")


if __name__ == "__main__":
    main()
