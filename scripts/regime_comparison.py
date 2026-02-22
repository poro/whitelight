#!/usr/bin/env python3
"""Multi-regime strategy comparison for White Light improvement research."""

import pandas as pd
import numpy as np
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
OUT_DIR = DATA_DIR / "research"
OUT_DIR.mkdir(exist_ok=True)

# Load TQQQ
df = pd.read_parquet(DATA_DIR / "cache" / "tqqq_daily.parquet")
df['date'] = pd.to_datetime(df['date'])
df = df.set_index('date').sort_index()

# Periods to test
PERIODS = {
    "covid_crash_recovery": ("2020-01-01", "2021-12-31"),
    "bear_2022": ("2022-01-01", "2022-10-31"),
    "bull_recovery": ("2022-11-01", "2024-12-31"),
    "full_cycle": ("2020-01-01", "2026-02-20"),
    "whitelight_period": ("2022-07-23", "2026-02-20"),
}

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

def make_state_signal(close, buy_cond, sell_cond):
    """Generic state machine: enter on buy_cond, exit on sell_cond."""
    pos = pd.Series(0, index=close.index)
    state = 0
    for i in range(1, len(close)):
        if buy_cond.iloc[i] and not np.isnan(buy_cond.iloc[i]):
            state = 1
        elif sell_cond.iloc[i] and not np.isnan(sell_cond.iloc[i]):
            state = 0
        pos.iloc[i] = state
    return pos

def build_strategies(df_period):
    """Build all 18 strategy signals for a given period."""
    close = df_period['close']
    strategies = {}
    
    # 1. SMA 50/200
    strategies['sma_50_200'] = (sma(close,50) > sma(close,200)).astype(int)
    # 2. SMA 20/50
    strategies['sma_20_50'] = (sma(close,20) > sma(close,50)).astype(int)
    # 3. EMA 9/21
    strategies['ema_9_21'] = (ema(close,9) > ema(close,21)).astype(int)
    # 4. Triple EMA
    strategies['triple_ema'] = ((ema(close,8) > ema(close,21)) & (ema(close,21) > ema(close,55))).astype(int)
    # 5. Donchian 20
    strategies['donchian_20'] = make_state_signal(close, close >= close.rolling(20).max().shift(1), close <= close.rolling(20).min().shift(1))
    # 6. MACD
    ml = ema(close,12) - ema(close,26)
    strategies['macd'] = (ml > ema(ml,9)).astype(int)
    # 7. ADX simplified (price > SMA50)
    strategies['adx_trend'] = (close > sma(close,50)).astype(int)
    # 8. RSI Momentum (>50)
    r14 = rsi(close, 14)
    strategies['rsi_momentum'] = (r14 > 50).astype(int)
    # 9. Momentum breakout (ROC)
    roc = close.pct_change(20) * 100
    strategies['momentum_breakout'] = make_state_signal(close, roc > 5, roc < -5)
    # 10. Dual momentum
    strategies['dual_momentum'] = ((close.pct_change(252) > 0) & (close.pct_change(126) > 0)).astype(int)
    # 11. Williams %R
    wr = -100 * (close.rolling(14).max() - close) / (close.rolling(14).max() - close.rolling(14).min() + 1e-10)
    strategies['williams_r'] = make_state_signal(close, (wr > -80) & (wr.shift(1) <= -80), (wr < -20) & (wr.shift(1) >= -20))
    # 12. RSI Mean Reversion
    strategies['rsi_mean_rev'] = make_state_signal(close, r14 < 30, r14 > 70)
    # 13. Bollinger Bounce
    bb_mid = sma(close,20); bb_std = close.rolling(20).std()
    strategies['bollinger_bounce'] = make_state_signal(close, close <= bb_mid - 2*bb_std, close >= bb_mid + 2*bb_std)
    # 14. SMA Mean Reversion
    s50 = sma(close,50)
    strategies['sma_mean_rev'] = make_state_signal(close, close < s50*0.95, close >= s50)
    # 15. ATR Breakout
    a14 = atr_calc(df_period, 14); s20 = sma(close,20)
    strategies['atr_breakout'] = make_state_signal(close, close > s20 + 2*a14, close < s20 - 2*a14)
    # 16. Keltner
    e20 = ema(close,20)
    strategies['keltner'] = make_state_signal(close, close > e20 + 2*a14, close < e20 - 2*a14)
    # 17. Trend+Momentum
    strategies['trend_momentum'] = ((sma(close,50) > sma(close,200)) & (r14 > 50)).astype(int)
    # 18. MACD+RSI
    strategies['macd_rsi'] = ((ml > ema(ml,9)) & (r14 > 40) & (r14 < 70)).astype(int)
    
    # === EXPERIMENTAL: Improved White Light candidates ===
    
    # E1: ATR-Adaptive Trend (combine ATR breakout's adaptive threshold with trend confirmation)
    trend_up = sma(close, 50) > sma(close, 200)
    atr_bull = close > s20 + 1.5*a14  # slightly tighter threshold
    atr_bear = close < s20 - 1.5*a14
    e1_buy = trend_up & atr_bull
    e1_sell = ~trend_up | atr_bear
    strategies['exp_atr_adaptive_trend'] = make_state_signal(close, e1_buy, e1_sell)
    
    # E2: Volatility-Regime Switch (use ATR percentile to adjust aggression)
    atr_pct = a14.rolling(252).rank(pct=True)  # ATR percentile over 1 year
    # Low vol: use faster signals (EMA 9/21), High vol: use slower (SMA 50/200)
    fast_sig = (ema(close,9) > ema(close,21)).astype(int)
    slow_sig = (sma(close,50) > sma(close,200)).astype(int)
    vol_switch = pd.Series(0, index=close.index)
    for i in range(1, len(close)):
        if pd.isna(atr_pct.iloc[i]):
            vol_switch.iloc[i] = fast_sig.iloc[i]
        elif atr_pct.iloc[i] > 0.7:  # high vol → slow
            vol_switch.iloc[i] = slow_sig.iloc[i]
        else:  # low vol → fast
            vol_switch.iloc[i] = fast_sig.iloc[i]
    strategies['exp_vol_regime_switch'] = vol_switch
    
    # E3: Multi-Signal Consensus (vote: SMA50/200, MACD, RSI>50, ATR breakout — need 3/4)
    sig1 = (sma(close,50) > sma(close,200)).astype(int)
    sig2 = (ml > ema(ml,9)).astype(int)
    sig3 = (r14 > 50).astype(int)
    sig4 = (close > s20 + 1*a14).astype(int)  # softer ATR threshold
    consensus = sig1 + sig2 + sig3 + sig4
    strategies['exp_consensus_3of4'] = (consensus >= 3).astype(int)
    
    # E4: Adaptive RSI + Trend (RSI thresholds adjust with volatility)
    # High vol: wider RSI bands (25/75), Low vol: tighter (40/60)
    rsi_buy = pd.Series(False, index=close.index)
    rsi_sell = pd.Series(False, index=close.index)
    for i in range(1, len(close)):
        if pd.isna(atr_pct.iloc[i]):
            continue
        if atr_pct.iloc[i] > 0.7:  # high vol
            rsi_buy.iloc[i] = r14.iloc[i] > 45 and close.iloc[i] > sma(close,100).iloc[i]
            rsi_sell.iloc[i] = r14.iloc[i] < 35 or close.iloc[i] < sma(close,100).iloc[i] * 0.95
        else:  # low vol
            rsi_buy.iloc[i] = r14.iloc[i] > 55 and close.iloc[i] > sma(close,50).iloc[i]
            rsi_sell.iloc[i] = r14.iloc[i] < 45
    strategies['exp_adaptive_rsi'] = make_state_signal(close, rsi_buy, rsi_sell)
    
    # E5: Calmar Maximizer (optimize for risk-adjusted: slow trend + tight ATR stop)
    # Enter on golden cross, exit on 1.5x ATR trailing stop from peak
    in_uptrend = sma(close,50) > sma(close,200)
    pos_e5 = pd.Series(0, index=close.index)
    peak = close.iloc[0]
    state = 0
    for i in range(1, len(close)):
        if state == 0:
            if in_uptrend.iloc[i] and not np.isnan(in_uptrend.iloc[i]):
                state = 1
                peak = close.iloc[i]
        else:
            peak = max(peak, close.iloc[i])
            atr_val = a14.iloc[i] if not np.isnan(a14.iloc[i]) else 0
            # Exit if: trend reverses OR price drops 2x ATR from peak
            if not in_uptrend.iloc[i] or close.iloc[i] < peak - 2.5 * atr_val:
                state = 0
        pos_e5.iloc[i] = state
    strategies['exp_calmar_maximizer'] = pos_e5
    
    return strategies

def evaluate(close, pos):
    """Calculate all metrics for a strategy."""
    pos = pos.fillna(0)
    daily_ret = close.pct_change().fillna(0)
    strat_ret = pos.shift(1).fillna(0) * daily_ret
    equity = (1 + strat_ret).cumprod() * 100000
    
    days = (close.index[-1] - close.index[0]).days
    years = max(days / 365.25, 0.1)
    final = float(equity.iloc[-1])
    cagr = (final/100000)**(1/years) - 1
    
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min())
    
    std = strat_ret.std()
    sharpe = float(strat_ret.mean() / std * np.sqrt(252)) if std > 0 else 0
    sortino_dn = strat_ret[strat_ret < 0].std()
    sortino = float(strat_ret.mean() / sortino_dn * np.sqrt(252)) if sortino_dn > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    trades = int((pos.diff().abs() > 0).sum())
    
    pos_ret = strat_ret[strat_ret > 0].sum()
    neg_ret = abs(strat_ret[strat_ret < 0].sum())
    pf = float(pos_ret / neg_ret) if neg_ret > 0 else 99
    
    # Win rate from actual trades
    entries = pos.diff().fillna(0)
    entry_idx = entries[entries > 0].index
    exit_idx = entries[entries < 0].index
    wins = total = 0
    for ent in entry_idx:
        ex = exit_idx[exit_idx > ent]
        if len(ex) > 0:
            total += 1
            if close[ex[0]] > close[ent]: wins += 1
    win_rate = wins/total if total > 0 else 0
    
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
    }

# === Run all periods ===
all_results = {}

for period_name, (start, end) in PERIODS.items():
    print(f"\n{'='*80}")
    print(f"PERIOD: {period_name} ({start} to {end})")
    print(f"{'='*80}")
    
    dp = df.loc[start:end].copy()
    if len(dp) < 50:
        print(f"  Skipping — only {len(dp)} rows")
        continue
    
    close = dp['close']
    strategies = build_strategies(dp)
    
    results = []
    for name, pos in strategies.items():
        metrics = evaluate(close, pos)
        metrics['name'] = name
        metrics['is_experimental'] = name.startswith('exp_')
        results.append(metrics)
    
    # Sort by Calmar (risk-adjusted focus)
    results.sort(key=lambda x: x['calmar'], reverse=True)
    
    print(f"\n{'Strategy':35s} {'CAGR':>7s} {'MaxDD':>7s} {'Sharpe':>7s} {'Calmar':>7s} {'Sortino':>8s} {'PF':>6s} {'Trd':>5s} {'Win%':>6s} {'$100K→':>10s}")
    print("-"*110)
    for r in results:
        flag = " ★" if r['is_experimental'] else ""
        print(f"{r['name']:35s} {r['cagr']:>6.1f}% {r['max_dd']:>6.1f}% {r['sharpe']:>7.3f} {r['calmar']:>7.3f} {r['sortino']:>8.3f} {r['pf']:>6.2f} {r['trades']:>5d} {r['win_rate']:>5.1f}% {r['final']:>9,.0f}{flag}")
    
    all_results[period_name] = results
    
    # Save individual period
    with open(OUT_DIR / f"regime_{period_name}.json", 'w') as f:
        json.dump(results, f, indent=2)

# === Summary: Best strategy per period ===
print(f"\n\n{'='*80}")
print("REGIME WINNERS (by Calmar Ratio — best risk/reward balance)")
print(f"{'='*80}")
print(f"\n{'Period':25s} {'#1 Strategy':30s} {'Calmar':>8s} {'CAGR':>7s} {'MaxDD':>7s}")
print("-"*80)
for period_name, results in all_results.items():
    best = results[0]
    print(f"{period_name:25s} {best['name']:30s} {best['calmar']:>8.3f} {best['cagr']:>6.1f}% {best['max_dd']:>6.1f}%")

# === Experimental strategies summary ===
print(f"\n\n{'='*80}")
print("EXPERIMENTAL STRATEGIES — Average across all periods")
print(f"{'='*80}")

exp_names = [n for n in all_results[list(all_results.keys())[0]] if n.get('is_experimental')]
exp_names = set()
for period_results in all_results.values():
    for r in period_results:
        if r['is_experimental']:
            exp_names.add(r['name'])

for ename in sorted(exp_names):
    cagrs, dds, sharpes, calmars = [], [], [], []
    for period_results in all_results.values():
        for r in period_results:
            if r['name'] == ename:
                cagrs.append(r['cagr'])
                dds.append(r['max_dd'])
                sharpes.append(r['sharpe'])
                calmars.append(r['calmar'])
    print(f"\n{ename}:")
    print(f"  Avg CAGR: {np.mean(cagrs):.1f}%  Avg MaxDD: {np.mean(dds):.1f}%  Avg Sharpe: {np.mean(sharpes):.3f}  Avg Calmar: {np.mean(calmars):.3f}")
    print(f"  Range CAGR: {min(cagrs):.1f}% to {max(cagrs):.1f}%  Range MaxDD: {min(dds):.1f}% to {max(dds):.1f}%")

# Save all
with open(OUT_DIR / "all_regime_results.json", 'w') as f:
    json.dump(all_results, f, indent=2)

print(f"\n\nResults saved to {OUT_DIR}/")
