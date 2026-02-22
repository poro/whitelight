#!/usr/bin/env python3
"""White Light v2 — Implementing P1+P2 improvements and backtesting across all regimes."""

import pandas as pd
import numpy as np
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR = DATA_DIR / "research"
OUT_DIR.mkdir(exist_ok=True)

# Load data
tqqq = pd.read_parquet(DATA_DIR / "cache" / "tqqq_daily.parquet")
tqqq['date'] = pd.to_datetime(tqqq['date'])
tqqq = tqqq.set_index('date').sort_index()

sqqq = pd.read_parquet(DATA_DIR / "cache" / "sqqq_daily.parquet")
sqqq['date'] = pd.to_datetime(sqqq['date'])
sqqq = sqqq.set_index('date').sort_index()

# --- Indicator helpers ---
def sma(s, n): return s.rolling(n).mean()
def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).rolling(n).mean()
    dn = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100/(1+up/(dn+1e-10))
def atr_calc(df, n=14):
    h, l, c = df['high'], df['low'], df['close']
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def white_light_v1(df):
    """Original White Light — simplified reproduction using SMA 50/200 + RSI regime detection."""
    close = df['close']
    s50, s200 = sma(close, 50), sma(close, 200)
    r14 = rsi(close, 14)
    
    # Bull: SMA50 > SMA200 and RSI > 45
    # Bear: SMA50 < SMA200 and RSI < 55
    # Neutral: otherwise
    regime = pd.Series('neutral', index=close.index)
    for i in range(1, len(close)):
        if pd.isna(s200.iloc[i]):
            continue
        if s50.iloc[i] > s200.iloc[i] and r14.iloc[i] > 45:
            regime.iloc[i] = 'bull'
        elif s50.iloc[i] < s200.iloc[i] and r14.iloc[i] < 55:
            regime.iloc[i] = 'bear'
        else:
            regime.iloc[i] = 'neutral'
    return regime


def white_light_v2(df):
    """White Light v2 — Vol-adaptive signals + ATR thresholds + RSI filter."""
    close = df['close']
    a14 = atr_calc(df, 14)
    atr_pct = a14.rolling(252, min_periods=60).rank(pct=True)
    r14 = rsi(close, 14)
    
    # Pre-compute all timeframe indicators
    ema9 = ema(close, 9); ema21 = ema(close, 21)
    sma20 = sma(close, 20); s50 = sma(close, 50)
    s100 = sma(close, 100); s200 = sma(close, 200)
    
    regime = pd.Series('neutral', index=close.index)
    peak_price = close.iloc[0]
    current_regime = 'neutral'
    
    for i in range(1, len(close)):
        if pd.isna(s200.iloc[i]) or pd.isna(a14.iloc[i]):
            continue
        
        vol = atr_pct.iloc[i] if not pd.isna(atr_pct.iloc[i]) else 0.5
        atr_val = a14.iloc[i]
        price = close.iloc[i]
        rsi_val = r14.iloc[i] if not pd.isna(r14.iloc[i]) else 50
        
        # === Improvement 1: Volatility-Adaptive Signal Speed ===
        if vol < 0.3:  # Low vol → fast signals
            trend_bull = ema9.iloc[i] > ema21.iloc[i]
            trend_bear = ema9.iloc[i] < ema21.iloc[i]
            ref_ma = sma20.iloc[i]
        elif vol < 0.7:  # Medium vol → medium signals
            trend_bull = sma20.iloc[i] > s50.iloc[i]
            trend_bear = sma20.iloc[i] < s50.iloc[i]
            ref_ma = s50.iloc[i]
        else:  # High vol → slow signals
            trend_bull = s50.iloc[i] > s200.iloc[i]
            trend_bear = s50.iloc[i] < s200.iloc[i]
            ref_ma = s100.iloc[i]
        
        # === Improvement 2: ATR-Based Entry/Exit Thresholds ===
        bull_threshold = ref_ma + 1.5 * atr_val
        bear_threshold = ref_ma - 2.0 * atr_val  # Asymmetric — harder to go bear
        
        # === Improvement 3: RSI Confirmation Filter ===
        rsi_allows_bull = 35 < rsi_val < 75
        rsi_allows_bear = 25 < rsi_val < 65
        
        # === Improvement 4: Trailing ATR Stop ===
        if current_regime == 'bull':
            peak_price = max(peak_price, price)
            atr_stop_hit = price < peak_price - 2.5 * atr_val
        elif current_regime == 'bear':
            peak_price = min(peak_price, price)  # track lowest for bear
            atr_stop_hit = price > peak_price + 2.5 * atr_val
        else:
            atr_stop_hit = False
        
        # === Improvement 5: Regime Decision ===
        new_regime = current_regime
        
        if atr_stop_hit:
            new_regime = 'neutral'  # stop hit → go to cash, don't reverse
        elif trend_bull and price > bull_threshold and rsi_allows_bull:
            new_regime = 'bull'
            peak_price = price
        elif trend_bear and price < bear_threshold and rsi_allows_bear:
            new_regime = 'bear'
            peak_price = price
        elif current_regime == 'bull' and not trend_bull:
            new_regime = 'neutral'
        elif current_regime == 'bear' and not trend_bear:
            new_regime = 'neutral'
        
        current_regime = new_regime
        regime.iloc[i] = current_regime
    
    return regime


def white_light_v2_conservative(df):
    """White Light v2 Conservative — Same as v2 but with position sizing by volatility."""
    close = df['close']
    a14 = atr_calc(df, 14)
    atr_pct = a14.rolling(252, min_periods=60).rank(pct=True)
    r14 = rsi(close, 14)
    
    ema9 = ema(close, 9); ema21 = ema(close, 21)
    sma20 = sma(close, 20); s50 = sma(close, 50)
    s100 = sma(close, 100); s200 = sma(close, 200)
    atr_median = a14.rolling(252, min_periods=60).median()
    
    regime = pd.Series('neutral', index=close.index)
    sizing = pd.Series(1.0, index=close.index)  # position size multiplier
    peak_price = close.iloc[0]
    current_regime = 'neutral'
    
    for i in range(1, len(close)):
        if pd.isna(s200.iloc[i]) or pd.isna(a14.iloc[i]):
            continue
        
        vol = atr_pct.iloc[i] if not pd.isna(atr_pct.iloc[i]) else 0.5
        atr_val = a14.iloc[i]
        price = close.iloc[i]
        rsi_val = r14.iloc[i] if not pd.isna(r14.iloc[i]) else 50
        
        # Vol-Adaptive signals (same as v2)
        if vol < 0.3:
            trend_bull = ema9.iloc[i] > ema21.iloc[i]
            trend_bear = ema9.iloc[i] < ema21.iloc[i]
            ref_ma = sma20.iloc[i]
        elif vol < 0.7:
            trend_bull = sma20.iloc[i] > s50.iloc[i]
            trend_bear = sma20.iloc[i] < s50.iloc[i]
            ref_ma = s50.iloc[i]
        else:
            trend_bull = s50.iloc[i] > s200.iloc[i]
            trend_bear = s50.iloc[i] < s200.iloc[i]
            ref_ma = s100.iloc[i]
        
        bull_threshold = ref_ma + 1.5 * atr_val
        bear_threshold = ref_ma - 2.0 * atr_val
        rsi_allows_bull = 35 < rsi_val < 75
        rsi_allows_bear = 25 < rsi_val < 65
        
        if current_regime == 'bull':
            peak_price = max(peak_price, price)
            atr_stop_hit = price < peak_price - 2.5 * atr_val
        elif current_regime == 'bear':
            peak_price = min(peak_price, price)
            atr_stop_hit = price > peak_price + 2.5 * atr_val
        else:
            atr_stop_hit = False
        
        new_regime = current_regime
        if atr_stop_hit:
            new_regime = 'neutral'
        elif trend_bull and price > bull_threshold and rsi_allows_bull:
            new_regime = 'bull'
            peak_price = price
        elif trend_bear and price < bear_threshold and rsi_allows_bear:
            new_regime = 'bear'
            peak_price = price
        elif current_regime == 'bull' and not trend_bull:
            new_regime = 'neutral'
        elif current_regime == 'bear' and not trend_bear:
            new_regime = 'neutral'
        
        current_regime = new_regime
        regime.iloc[i] = current_regime
        
        # Position sizing by volatility
        if not pd.isna(atr_median.iloc[i]) and atr_val > 0:
            sizing.iloc[i] = min(1.0, max(0.5, float(atr_median.iloc[i] / atr_val)))
        
    return regime, sizing


def simulate_3instrument(tqqq_df, sqqq_df, regime, initial=100000, sizing=None):
    """Simulate 3-instrument trading: bull→TQQQ, bear→SQQQ, neutral→BIL(~5% annual)."""
    tqqq_ret = tqqq_df['close'].pct_change().fillna(0)
    sqqq_ret = sqqq_df['close'].pct_change().fillna(0)
    bil_daily = 0.05 / 252  # ~5% annual risk-free
    
    # Align
    common = tqqq_ret.index.intersection(sqqq_ret.index).intersection(regime.index)
    tqqq_ret = tqqq_ret.loc[common]
    sqqq_ret = sqqq_ret.loc[common]
    regime = regime.loc[common]
    if sizing is not None:
        sizing = sizing.loc[common]
    
    equity = pd.Series(0.0, index=common)
    equity.iloc[0] = initial
    trades = 0
    prev_regime = 'neutral'
    wins = 0
    total_trades = 0
    entry_price = 0
    
    for i in range(1, len(common)):
        r = regime.iloc[i-1]  # use previous day's signal
        size = sizing.iloc[i-1] if sizing is not None else 1.0
        
        if r == 'bull':
            daily = tqqq_ret.iloc[i] * size + bil_daily * (1 - size)
        elif r == 'bear':
            daily = sqqq_ret.iloc[i] * size + bil_daily * (1 - size)
        else:
            daily = bil_daily
        
        equity.iloc[i] = equity.iloc[i-1] * (1 + daily)
        
        if r != prev_regime:
            trades += 1
            if prev_regime in ('bull', 'bear') and entry_price > 0:
                total_trades += 1
                if equity.iloc[i] > entry_price:
                    wins += 1
            if r in ('bull', 'bear'):
                entry_price = equity.iloc[i]
            prev_regime = r
    
    # Metrics
    days = (common[-1] - common[0]).days
    years = max(days / 365.25, 0.1)
    final = float(equity.iloc[-1])
    cagr = (final/initial)**(1/years) - 1
    
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min())
    
    daily_returns = equity.pct_change().dropna()
    sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() > 0 else 0
    sortino_dn = daily_returns[daily_returns < 0].std()
    sortino = float(daily_returns.mean() / sortino_dn * np.sqrt(252)) if sortino_dn > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    pos_ret = daily_returns[daily_returns > 0].sum()
    neg_ret = abs(daily_returns[daily_returns < 0].sum())
    pf = float(pos_ret / neg_ret) if neg_ret > 0 else 99
    
    win_rate = wins / total_trades if total_trades > 0 else 0
    
    # Regime breakdown
    regime_counts = regime.value_counts()
    
    return {
        'cagr': round(cagr*100, 2),
        'max_dd': round(max_dd*100, 2),
        'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3),
        'calmar': round(calmar, 3),
        'pf': round(pf, 2),
        'trades': trades,
        'win_rate': round(win_rate*100, 1),
        'final': round(final, 0),
        'years': round(years, 1),
        'regime_pct': {
            'bull': round(regime_counts.get('bull', 0) / len(regime) * 100, 1),
            'bear': round(regime_counts.get('bear', 0) / len(regime) * 100, 1),
            'neutral': round(regime_counts.get('neutral', 0) / len(regime) * 100, 1),
        },
        'equity_curve': {str(d.date()): round(v, 0) for d, v in list(equity.items())[::max(1, len(equity)//200)]},
    }


# === Test Periods ===
PERIODS = {
    "short_1yr": ("2025-02-20", "2026-02-20"),
    "short_2yr": ("2024-02-20", "2026-02-20"),
    "whitelight_3_5yr": ("2022-07-23", "2026-02-20"),
    "covid_recovery": ("2020-01-01", "2021-12-31"),
    "bear_2022": ("2022-01-01", "2022-10-31"),
    "bull_2023_2024": ("2022-11-01", "2024-12-31"),
    "full_5yr": ("2021-02-20", "2026-02-20"),
    "full_cycle_6yr": ("2020-01-01", "2026-02-20"),
    "max_history": ("2011-01-01", "2026-02-20"),
}

STRATEGIES = {
    'White Light v1': lambda df: (white_light_v1(df), None),
    'White Light v2': lambda df: (white_light_v2(df), None),
    'White Light v2 Conservative': lambda df: white_light_v2_conservative(df),
}

all_results = {}

for period_name, (start, end) in PERIODS.items():
    t = tqqq.loc[start:end].copy()
    s = sqqq.loc[start:end].copy()
    
    if len(t) < 50:
        print(f"Skipping {period_name} — only {len(t)} rows")
        continue
    
    print(f"\n{'='*100}")
    print(f"PERIOD: {period_name} ({start} → {end}, {len(t)} trading days)")
    print(f"{'='*100}")
    
    period_results = {}
    
    for name, strategy_fn in STRATEGIES.items():
        result = strategy_fn(t)
        if isinstance(result, tuple):
            regime, sizing = result
        else:
            regime, sizing = result, None
        
        metrics = simulate_3instrument(t, s, regime, sizing=sizing)
        metrics['name'] = name
        period_results[name] = metrics
        
        bull_pct = metrics['regime_pct']['bull']
        bear_pct = metrics['regime_pct']['bear']
        neutral_pct = metrics['regime_pct']['neutral']
        
        print(f"\n  {name}:")
        print(f"    CAGR: {metrics['cagr']:>7.1f}%  |  Max DD: {metrics['max_dd']:>7.1f}%  |  Sharpe: {metrics['sharpe']:>6.3f}  |  Calmar: {metrics['calmar']:>6.3f}")
        print(f"    Sortino: {metrics['sortino']:>6.3f}  |  PF: {metrics['pf']:>5.2f}  |  Trades: {metrics['trades']:>4d}  |  Win: {metrics['win_rate']:>5.1f}%")
        print(f"    $100K → ${metrics['final']:>12,.0f}  |  Bull: {bull_pct:.0f}%  Bear: {bear_pct:.0f}%  Neutral: {neutral_pct:.0f}%")
    
    all_results[period_name] = period_results

# === Summary Table ===
print(f"\n\n{'='*130}")
print(f"SUMMARY: All Periods × All Strategies")
print(f"{'='*130}")
print(f"\n{'Period':25s} | {'v1 CAGR':>8s} {'v1 DD':>8s} {'v1 Calmar':>10s} | {'v2 CAGR':>8s} {'v2 DD':>8s} {'v2 Calmar':>10s} | {'v2C CAGR':>8s} {'v2C DD':>8s} {'v2C Calmar':>10s}")
print("-"*130)
for period_name, results in all_results.items():
    v1 = results.get('White Light v1', {})
    v2 = results.get('White Light v2', {})
    v2c = results.get('White Light v2 Conservative', {})
    print(f"{period_name:25s} | {v1.get('cagr',0):>7.1f}% {v1.get('max_dd',0):>7.1f}% {v1.get('calmar',0):>10.3f} | {v2.get('cagr',0):>7.1f}% {v2.get('max_dd',0):>7.1f}% {v2.get('calmar',0):>10.3f} | {v2c.get('cagr',0):>7.1f}% {v2c.get('max_dd',0):>7.1f}% {v2c.get('calmar',0):>10.3f}")

# === Improvement Deltas ===
print(f"\n\n{'='*80}")
print("IMPROVEMENT DELTAS (v2 vs v1)")
print(f"{'='*80}")
for period_name, results in all_results.items():
    v1 = results.get('White Light v1', {})
    v2 = results.get('White Light v2', {})
    dcagr = v2.get('cagr',0) - v1.get('cagr',0)
    ddd = v2.get('max_dd',0) - v1.get('max_dd',0)  # less negative = better
    dcalmar = v2.get('calmar',0) - v1.get('calmar',0)
    print(f"  {period_name:25s}  CAGR: {dcagr:>+6.1f}%  MaxDD: {ddd:>+6.1f}%  Calmar: {dcalmar:>+6.3f}")

# Save
# Strip equity curves for compact JSON
compact = {}
for pname, results in all_results.items():
    compact[pname] = {}
    for sname, metrics in results.items():
        m = {k: v for k, v in metrics.items() if k != 'equity_curve'}
        compact[pname][sname] = m

with open(OUT_DIR / "whitelight_v2_results.json", 'w') as f:
    json.dump(compact, f, indent=2)

# Save equity curves separately
curves = {}
for pname, results in all_results.items():
    curves[pname] = {}
    for sname, metrics in results.items():
        curves[pname][sname] = metrics.get('equity_curve', {})
with open(OUT_DIR / "whitelight_v2_equity_curves.json", 'w') as f:
    json.dump(curves, f, indent=2)

print(f"\n\nResults saved to {OUT_DIR}/")
