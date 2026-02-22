"""Library of well-known trading strategies implemented in Python for VectorBT.

Each strategy is a function that takes a DataFrame (OHLCV) and returns
(entries: pd.Series[bool], exits: pd.Series[bool]).

These are classic strategies from academic literature and trading communities.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helper indicators
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low'] - df['close'].shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    fast_ema = series.ewm(span=fast, adjust=False).mean()
    slow_ema = series.ewm(span=slow, adjust=False).mean()
    macd_line = fast_ema - slow_ema
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index."""
    high, low, close = df['high'], df['low'], df['close']
    plus_dm = high.diff().clip(lower=0)
    minus_dm = (-low.diff()).clip(lower=0)
    # When +DM > -DM, keep +DM; else 0
    plus_dm[plus_dm <= minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0
    tr = _atr(df, 1) * period  # Approximation
    atr = _atr(df, period)
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    return dx.rolling(period).mean()


# ---------------------------------------------------------------------------
# Strategy Library
# ---------------------------------------------------------------------------

STRATEGIES = {}

def register(name: str, category: str, description: str):
    """Decorator to register a strategy in the library."""
    def wrapper(fn):
        STRATEGIES[name] = {
            'fn': fn,
            'name': name,
            'category': category,
            'description': description,
        }
        return fn
    return wrapper


# ── Trend Following ──

@register("sma_crossover_50_200", "trend-following",
          "Golden Cross / Death Cross: Buy when SMA50 crosses above SMA200, sell on cross below")
def sma_crossover_50_200(df: pd.DataFrame):
    sma50 = df['close'].rolling(50).mean()
    sma200 = df['close'].rolling(200).mean()
    entries = (sma50.shift(1) <= sma200.shift(1)) & (sma50 > sma200)
    exits = (sma50.shift(1) >= sma200.shift(1)) & (sma50 < sma200)
    return entries, exits


@register("sma_crossover_20_50", "trend-following",
          "Short-term trend: Buy when SMA20 crosses above SMA50")
def sma_crossover_20_50(df: pd.DataFrame):
    sma20 = df['close'].rolling(20).mean()
    sma50 = df['close'].rolling(50).mean()
    entries = (sma20.shift(1) <= sma50.shift(1)) & (sma20 > sma50)
    exits = (sma20.shift(1) >= sma50.shift(1)) & (sma20 < sma50)
    return entries, exits


@register("ema_crossover_9_21", "trend-following",
          "Fast EMA cross: Buy when EMA9 crosses above EMA21")
def ema_crossover_9_21(df: pd.DataFrame):
    ema9 = df['close'].ewm(span=9, adjust=False).mean()
    ema21 = df['close'].ewm(span=21, adjust=False).mean()
    entries = (ema9.shift(1) <= ema21.shift(1)) & (ema9 > ema21)
    exits = (ema9.shift(1) >= ema21.shift(1)) & (ema9 < ema21)
    return entries, exits


@register("triple_ema", "trend-following",
          "Triple EMA: Buy when EMA8 > EMA21 > EMA55, sell on reverse")
def triple_ema(df: pd.DataFrame):
    ema8 = df['close'].ewm(span=8, adjust=False).mean()
    ema21 = df['close'].ewm(span=21, adjust=False).mean()
    ema55 = df['close'].ewm(span=55, adjust=False).mean()
    bullish = (ema8 > ema21) & (ema21 > ema55)
    entries = bullish & ~bullish.shift(1).fillna(False)
    exits = ~bullish & bullish.shift(1).fillna(False)
    return entries, exits


@register("donchian_breakout_20", "trend-following",
          "Donchian Channel Breakout: Buy on 20-day high, sell on 20-day low (Turtle Traders)")
def donchian_breakout_20(df: pd.DataFrame):
    upper = df['high'].rolling(20).max()
    lower = df['low'].rolling(20).min()
    entries = df['close'] > upper.shift(1)
    exits = df['close'] < lower.shift(1)
    return entries, exits


@register("supertrend", "trend-following",
          "Supertrend indicator: ATR-based trend following with factor=3, period=10")
def supertrend(df: pd.DataFrame):
    period, factor = 10, 3.0
    atr = _atr(df, period)
    hl2 = (df['high'] + df['low']) / 2
    upper = hl2 + factor * atr
    lower = hl2 - factor * atr
    
    trend = pd.Series(1, index=df.index)  # 1 = up, -1 = down
    final_upper = upper.copy()
    final_lower = lower.copy()
    
    for i in range(1, len(df)):
        if lower.iloc[i] > final_lower.iloc[i-1]:
            final_lower.iloc[i] = lower.iloc[i]
        else:
            final_lower.iloc[i] = final_lower.iloc[i-1]
        if upper.iloc[i] < final_upper.iloc[i-1]:
            final_upper.iloc[i] = upper.iloc[i]
        else:
            final_upper.iloc[i] = final_upper.iloc[i-1]
        
        if trend.iloc[i-1] == 1:
            if df['close'].iloc[i] < final_lower.iloc[i]:
                trend.iloc[i] = -1
            else:
                trend.iloc[i] = 1
        else:
            if df['close'].iloc[i] > final_upper.iloc[i]:
                trend.iloc[i] = 1
            else:
                trend.iloc[i] = -1
    
    entries = (trend == 1) & (trend.shift(1) == -1)
    exits = (trend == -1) & (trend.shift(1) == 1)
    return entries, exits


@register("macd_crossover", "trend-following",
          "MACD Signal Line Cross: Buy when MACD crosses above signal, sell on cross below")
def macd_crossover(df: pd.DataFrame):
    macd_line, signal_line, _ = _macd(df['close'])
    entries = (macd_line.shift(1) <= signal_line.shift(1)) & (macd_line > signal_line)
    exits = (macd_line.shift(1) >= signal_line.shift(1)) & (macd_line < signal_line)
    return entries, exits


@register("adx_trend", "trend-following",
          "ADX Trend: Buy when ADX > 25 and price above SMA50, sell when ADX < 20")
def adx_trend(df: pd.DataFrame):
    adx = _adx(df, 14)
    sma50 = df['close'].rolling(50).mean()
    entries = (adx > 25) & (df['close'] > sma50) & ((adx.shift(1) <= 25) | (df['close'].shift(1) <= sma50.shift(1)))
    exits = (adx < 20) & (adx.shift(1) >= 20)
    return entries, exits


# ── Momentum ──

@register("rsi_momentum", "momentum",
          "RSI Momentum: Buy when RSI(14) crosses above 50, sell when crosses below 50")
def rsi_momentum(df: pd.DataFrame):
    rsi = _rsi(df['close'], 14)
    entries = (rsi.shift(1) <= 50) & (rsi > 50)
    exits = (rsi.shift(1) >= 50) & (rsi < 50)
    return entries, exits


@register("momentum_breakout", "momentum",
          "Rate of Change Breakout: Buy when 20-day ROC > 5%, sell when < -5%")
def momentum_breakout(df: pd.DataFrame):
    roc = df['close'].pct_change(20) * 100
    entries = (roc > 5) & (roc.shift(1) <= 5)
    exits = (roc < -5) & (roc.shift(1) >= -5)
    return entries, exits


@register("dual_momentum", "momentum",
          "Dual Momentum (Antonacci): Buy when both absolute and relative momentum are positive")
def dual_momentum(df: pd.DataFrame):
    # Absolute momentum: 12-month return > 0
    abs_mom = df['close'].pct_change(252) > 0
    # Relative momentum: price above 200-day SMA
    rel_mom = df['close'] > df['close'].rolling(200).mean()
    
    signal = abs_mom & rel_mom
    entries = signal & ~signal.shift(1).fillna(False)
    exits = ~signal & signal.shift(1).fillna(False)
    return entries, exits


@register("williams_r_momentum", "momentum",
          "Williams %R: Buy when %R crosses above -80 (oversold exit), sell when crosses below -20")
def williams_r_momentum(df: pd.DataFrame):
    period = 14
    highest = df['high'].rolling(period).max()
    lowest = df['low'].rolling(period).min()
    wr = -100 * (highest - df['close']) / (highest - lowest)
    entries = (wr.shift(1) <= -80) & (wr > -80)
    exits = (wr.shift(1) >= -20) & (wr < -20)
    return entries, exits


# ── Mean Reversion ──

@register("rsi_mean_reversion", "mean-reversion",
          "RSI Mean Reversion: Buy when RSI(14) < 30 (oversold), sell when RSI > 70 (overbought)")
def rsi_mean_reversion(df: pd.DataFrame):
    rsi = _rsi(df['close'], 14)
    entries = (rsi < 30) & (rsi.shift(1) >= 30)
    exits = (rsi > 70) & (rsi.shift(1) <= 70)
    return entries, exits


@register("bollinger_mean_reversion", "mean-reversion",
          "Bollinger Band Bounce: Buy at lower band, sell at upper band")
def bollinger_mean_reversion(df: pd.DataFrame):
    sma = df['close'].rolling(20).mean()
    std = df['close'].rolling(20).std()
    upper = sma + 2 * std
    lower = sma - 2 * std
    entries = (df['close'] < lower) & (df['close'].shift(1) >= lower.shift(1))
    exits = (df['close'] > upper) & (df['close'].shift(1) <= upper.shift(1))
    return entries, exits


@register("mean_reversion_sma", "mean-reversion",
          "SMA Mean Reversion: Buy when price drops 5% below SMA50, sell when returns to SMA50")
def mean_reversion_sma(df: pd.DataFrame):
    sma50 = df['close'].rolling(50).mean()
    deviation = (df['close'] - sma50) / sma50
    entries = (deviation < -0.05) & (deviation.shift(1) >= -0.05)
    exits = (df['close'] > sma50) & (df['close'].shift(1) <= sma50.shift(1))
    return entries, exits


# ── Volatility ──

@register("atr_breakout", "volatility",
          "ATR Breakout: Buy when price moves 2x ATR above 20-day SMA")
def atr_breakout(df: pd.DataFrame):
    atr = _atr(df, 14)
    sma20 = df['close'].rolling(20).mean()
    entries = (df['close'] > sma20 + 2 * atr) & (df['close'].shift(1) <= (sma20.shift(1) + 2 * atr.shift(1)))
    exits = df['close'] < sma20
    return entries, exits


@register("keltner_channel_breakout", "volatility",
          "Keltner Channel Breakout: Buy above upper channel, sell below lower")
def keltner_channel_breakout(df: pd.DataFrame):
    ema20 = df['close'].ewm(span=20, adjust=False).mean()
    atr = _atr(df, 10)
    upper = ema20 + 2 * atr
    lower = ema20 - 2 * atr
    entries = (df['close'] > upper) & (df['close'].shift(1) <= upper.shift(1))
    exits = (df['close'] < lower) & (df['close'].shift(1) >= lower.shift(1))
    return entries, exits


# ── Composite / Multi-Factor ──

@register("trend_momentum_combo", "composite",
          "Trend + Momentum: Buy when SMA50 > SMA200 AND RSI > 50, sell on either failing")
def trend_momentum_combo(df: pd.DataFrame):
    sma50 = df['close'].rolling(50).mean()
    sma200 = df['close'].rolling(200).mean()
    rsi = _rsi(df['close'], 14)
    bullish = (sma50 > sma200) & (rsi > 50)
    entries = bullish & ~bullish.shift(1).fillna(False)
    exits = ~bullish & bullish.shift(1).fillna(False)
    return entries, exits


@register("macd_rsi_combo", "composite",
          "MACD + RSI Filter: MACD crossover only when RSI confirms (40-70 zone)")
def macd_rsi_combo(df: pd.DataFrame):
    macd_line, signal_line, _ = _macd(df['close'])
    rsi = _rsi(df['close'], 14)
    macd_cross_up = (macd_line.shift(1) <= signal_line.shift(1)) & (macd_line > signal_line)
    entries = macd_cross_up & (rsi > 40) & (rsi < 70)
    macd_cross_down = (macd_line.shift(1) >= signal_line.shift(1)) & (macd_line < signal_line)
    exits = macd_cross_down | (rsi > 80)
    return entries, exits


def get_all_strategies() -> dict:
    """Return all registered strategies."""
    return STRATEGIES


def get_strategy(name: str):
    """Get a specific strategy by name."""
    return STRATEGIES.get(name)
