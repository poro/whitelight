#!/usr/bin/env python3
"""Grid search optimization for White Light bull/bear composite score thresholds.

Sweeps bull and bear threshold combinations, running a full backtest for each,
and outputs a CSV of results plus a Sharpe ratio heatmap.
"""

from __future__ import annotations

import csv
import itertools
import logging
import sys
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
# Threshold-aware combiner
# ---------------------------------------------------------------------------

class ThresholdCombiner(SignalCombiner):
    """Extends SignalCombiner with configurable bull/bear composite thresholds.

    When the composite score is above `bull_threshold`, the volatility-targeted
    TQQQ allocation is used (standard behaviour).  When below `bear_threshold`,
    the SQQQ sprint logic kicks in regardless of SMA status.  Between the two
    thresholds, the allocation goes to cash.
    """

    def __init__(self, bull_threshold: float = 0.20, bear_threshold: float = -0.10):
        super().__init__()
        self.bull_threshold = bull_threshold
        self.bear_threshold = bear_threshold

    def combine(self, signals, ndx_data=None):
        composite = sum(s.weight * s.raw_score for s in signals)

        vol20 = self._get_vol20(signals, ndx_data)

        if composite >= self.bull_threshold:
            # Bull: volatility-targeted TQQQ
            if vol20 > 0:
                raw_tqqq = self.TARGET_VOL / vol20
            else:
                raw_tqqq = 1.0
            tqqq_pct = Decimal(str(round(min(raw_tqqq, 1.0), 4)))
            sqqq_pct = Decimal("0")
        elif composite <= self.bear_threshold:
            # Bear: SQQQ sprint
            tqqq_pct = Decimal("0")
            sqqq_pct = self.SQQQ_SPRINT_PCT
        else:
            # Neutral: cash
            tqqq_pct = Decimal("0")
            sqqq_pct = Decimal("0")

        # No direct flip override
        if self._previous_allocation is not None:
            prev = self._previous_allocation
            if (prev.tqqq_pct > 0 and sqqq_pct > 0) or (prev.sqqq_pct > 0 and tqqq_pct > 0):
                tqqq_pct = Decimal("0")
                sqqq_pct = Decimal("0")

        cash_pct = Decimal("1.0") - tqqq_pct - sqqq_pct

        from whitelight.models import TargetAllocation
        allocation = TargetAllocation(
            tqqq_pct=tqqq_pct,
            sqqq_pct=sqqq_pct,
            cash_pct=cash_pct,
            signals=list(signals),
            composite_score=round(composite, 6),
        )
        self._previous_allocation = allocation
        return allocation


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------

BULL_THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]
BEAR_THRESHOLDS = [-0.05, -0.10, -0.15, -0.20, -0.25, -0.30]


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


def load_data(start_date, end_date, warmup_days=260):
    from whitelight.data.yfinance_client import YFinanceClient
    client = YFinanceClient()
    warmup_start = start_date - timedelta(days=int(warmup_days * 1.5))
    ndx = client.get_daily_bars("NDX", warmup_start, end_date)
    tqqq = client.get_daily_bars("TQQQ", warmup_start, end_date)
    sqqq = client.get_daily_bars("SQQQ", warmup_start, end_date)
    return ndx, tqqq, sqqq


def run_grid_search():
    logging.basicConfig(level=logging.WARNING)

    start_date = date(2020, 1, 2)
    end_date = date.today()

    print("Loading market data...")
    ndx, tqqq, sqqq = load_data(start_date, end_date)
    print(f"  NDX: {len(ndx)} bars, TQQQ: {len(tqqq)} bars, SQQQ: {len(sqqq)} bars\n")

    config = BacktestConfig(
        start_date=start_date,
        end_date=end_date,
        initial_capital=Decimal("100000"),
        warmup_days=260,
    )

    results = []
    total = len(BULL_THRESHOLDS) * len(BEAR_THRESHOLDS)
    count = 0

    for bull_t, bear_t in itertools.product(BULL_THRESHOLDS, BEAR_THRESHOLDS):
        count += 1
        strategies = build_strategies()
        combiner = ThresholdCombiner(bull_threshold=bull_t, bear_threshold=bear_t)
        runner = BacktestRunner(strategies, combiner, config)

        result = runner.run(ndx, tqqq, sqqq)
        m = result.metrics

        row = {
            "bull_threshold": bull_t,
            "bear_threshold": bear_t,
            "sharpe_ratio": m.get("sharpe_ratio", 0),
            "max_drawdown": m.get("max_drawdown", 0),
            "cagr": m.get("annual_return", 0),
            "win_rate": m.get("win_rate", 0),
            "total_return": m.get("total_return", 0),
            "sortino_ratio": m.get("sortino_ratio", 0),
            "total_trades": m.get("total_trades", 0),
        }
        results.append(row)
        print(f"  [{count}/{total}] bull={bull_t:+.2f} bear={bear_t:+.2f} → "
              f"Sharpe={row['sharpe_ratio']:.2f}  CAGR={row['cagr']*100:+.1f}%  "
              f"MaxDD={row['max_drawdown']*100:.1f}%  WR={row['win_rate']*100:.0f}%")

    # Save CSV
    csv_path = Path(__file__).parent / "grid_search_results.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\nResults saved to {csv_path}")

    # Top 5 by Sharpe
    sorted_results = sorted(results, key=lambda r: r["sharpe_ratio"], reverse=True)
    print("\n" + "=" * 70)
    print("  TOP 5 PARAMETER COMBINATIONS BY SHARPE RATIO")
    print("=" * 70)
    print(f"  {'Bull':>6s}  {'Bear':>6s}  {'Sharpe':>7s}  {'CAGR':>8s}  {'MaxDD':>7s}  {'WinRate':>7s}")
    print("  " + "-" * 58)
    for r in sorted_results[:5]:
        print(f"  {r['bull_threshold']:+6.2f}  {r['bear_threshold']:+6.2f}  "
              f"{r['sharpe_ratio']:7.2f}  {r['cagr']*100:+7.1f}%  "
              f"{r['max_drawdown']*100:6.1f}%  {r['win_rate']*100:6.0f}%")

    # Heatmap
    _plot_heatmap(results)

    return sorted_results


def _plot_heatmap(results):
    df = pd.DataFrame(results)
    pivot = df.pivot(index="bear_threshold", columns="bull_threshold", values="sharpe_ratio")
    pivot = pivot.sort_index(ascending=False)

    fig, ax = plt.subplots(figsize=(10, 7))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto")

    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{x:+.2f}" for x in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels([f"{y:+.2f}" for y in pivot.index])

    ax.set_xlabel("Bull Threshold (composite score)")
    ax.set_ylabel("Bear Threshold (composite score)")
    ax.set_title("White Light Grid Search — Sharpe Ratio by Threshold Combination")

    # Annotate cells
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            val = pivot.values[i, j]
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    color="black" if 0.3 < (val - pivot.values.min()) / (pivot.values.max() - pivot.values.min() + 1e-9) < 0.7 else "white",
                    fontsize=9, fontweight="bold")

    plt.colorbar(im, label="Sharpe Ratio")
    plt.tight_layout()

    heatmap_path = Path(__file__).parent / "grid_search_heatmap.png"
    plt.savefig(heatmap_path, dpi=150)
    print(f"Heatmap saved to {heatmap_path}")
    plt.close()


if __name__ == "__main__":
    run_grid_search()
