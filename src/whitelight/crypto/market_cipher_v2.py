"""
Market Cipher v2 — Enhanced implementation with precise entry strategies.

Entry Strategies:
  1. White Line Cut on Trigger Wave (Momentum)
  2. VWAP Strong Curve Cross (Reversal)
  3. Money Flow Zero-Line Cross (Trend Continuation)
  4. Multi-Timeframe Sniper (4H/24M concept adapted to daily)
  5. Higher Timeframe Alignment (Golden Rule)

Modifications over v1:
  - Adaptive thresholds (vol-regime scaled)
  - VWAP curve concavity (2nd derivative)
  - MFI rate-of-change (slope = thickness)
  - Volume confirmation on divergences
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple


# ============================================================
#  Core Indicators
# ============================================================

def ema(s: pd.Series, period: int) -> pd.Series:
    return s.ewm(span=period, adjust=False).mean()


def compute_momentum(close: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """Stochastic RSI → smoothed momentum wave + white line."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    stoch_rsi = ((rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)).fillna(0.5)

    # Blue wave (dark) = slower smooth
    blue_wave = ema(stoch_rsi * 2 - 1, 5)  # [-1, 1] range, period 5 smooth
    # White line = faster smooth (the "cut" line)
    white_line = ema(stoch_rsi * 2 - 1, 3)  # [-1, 1] range, period 3 smooth

    return blue_wave, white_line


def compute_money_flow(close: pd.Series, high: pd.Series,
                       low: pd.Series, volume: pd.Series) -> pd.Series:
    """Money Flow Index normalized to [-1, 1]."""
    tp = (high + low + close) / 3
    raw_mf = tp * volume
    pos_mf = raw_mf.where(tp > tp.shift(1), 0.0).rolling(14).sum()
    neg_mf = raw_mf.where(tp < tp.shift(1), 0.0).rolling(14).sum()
    mfi = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
    return ((mfi - 50) / 50).fillna(0)


def compute_vwap_signal(close: pd.Series, high: pd.Series,
                        low: pd.Series, volume: pd.Series,
                        period: int = 20) -> pd.Series:
    """Rolling VWAP deviation normalized to ~[-1, 1]."""
    tp = (high + low + close) / 3
    cum_pv = (tp * volume).rolling(period).sum()
    cum_vol = volume.rolling(period).sum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    signal = ((close - vwap) / vwap.replace(0, np.nan)).clip(-0.05, 0.05) * 20
    return signal.fillna(0)


def compute_ema_ribbons(close: pd.Series) -> dict:
    """EMA ribbon state for MCA."""
    e9 = ema(close, 9)
    e21 = ema(close, 21)
    e50 = ema(close, 50)
    return {
        'bullish': (e9 > e21) & (e21 > e50),
        'bearish': (e9 < e21) & (e21 < e50),
        'fast_cross_up': (e9 > e21) & (e9.shift(1) <= e21.shift(1)),
        'fast_cross_down': (e9 < e21) & (e9.shift(1) >= e21.shift(1)),
    }


# ============================================================
#  Entry Strategy 1: White Line Cut on Trigger Wave
# ============================================================

def entry_white_line_cut(blue_wave: pd.Series, white_line: pd.Series,
                         vol_regime: pd.Series) -> pd.Series:
    """
    Detect anchor wave + trigger wave + white line cutting into blue.
    Anchor = deep wave below -0.60 (adaptive to vol).
    Trigger = subsequent shallower wave.
    Entry = white line crosses into blue wave on trigger.
    """
    # Adaptive anchor level: deeper in low vol, shallower in high vol
    anchor_level = -0.60 * (1.0 / vol_regime.clip(0.5, 2.0))

    signal = pd.Series(0.0, index=blue_wave.index)

    # Vectorized: rolling 50-bar min of blue wave
    rolling_min_50 = blue_wave.rolling(50).min()
    rolling_max_50 = blue_wave.rolling(50).max()

    # Had anchor: rolling min was below adaptive anchor level
    had_anchor = rolling_min_50 < anchor_level

    # Trigger wave: current is shallower than the anchor low
    is_trigger = had_anchor & (blue_wave > rolling_min_50) & (blue_wave < -0.20)

    # White line cuts into blue wave (crosses above)
    white_cuts_up = (white_line > blue_wave) & (white_line.shift(1) <= blue_wave.shift(1))

    # Bullish entry: trigger wave + white line cut + near -45 level
    bullish = is_trigger & white_cuts_up & (blue_wave > -0.60) & (blue_wave < -0.15)
    signal[bullish] = 1.0

    # Bearish mirror
    had_peak = rolling_max_50 > 0.60
    is_bear_trigger = had_peak & (blue_wave < rolling_max_50) & (blue_wave > 0.20)
    white_cuts_down = (white_line < blue_wave) & (white_line.shift(1) >= blue_wave.shift(1))
    bearish = is_bear_trigger & white_cuts_down & (blue_wave < 0.60) & (blue_wave > 0.15)
    signal[bearish] = -1.0

    return signal


# ============================================================
#  Entry Strategy 2: VWAP Strong Curve Cross
# ============================================================

def entry_vwap_curve_cross(vwap_signal: pd.Series) -> pd.Series:
    """
    VWAP zero-line cross with curve direction filter.
    Strong: curve pointing TOWARD zero before crossing.
    Weak: curve pointing AWAY from zero but crossing anyway.
    """
    signal = pd.Series(0.0, index=vwap_signal.index)

    # First derivative (slope)
    slope = vwap_signal.diff()
    # Second derivative (concavity / acceleration)
    accel = slope.diff()

    # Zero crosses
    cross_up = (vwap_signal > 0) & (vwap_signal.shift(1) <= 0)
    cross_down = (vwap_signal < 0) & (vwap_signal.shift(1) >= 0)

    # Strong cross: slope was pointing toward zero before crossing
    # For cross_up: slope should be positive (moving up toward zero from below)
    # AND acceleration positive = curve bending toward zero
    strong_cross_up = cross_up & (slope > 0) & (accel.shift(1) > 0)
    weak_cross_up = cross_up & ~strong_cross_up

    strong_cross_down = cross_down & (slope < 0) & (accel.shift(1) < 0)
    weak_cross_down = cross_down & ~strong_cross_down

    # Strong cross = full signal, weak = half signal
    signal[strong_cross_up] = 1.0
    signal[weak_cross_up] = 0.4
    signal[strong_cross_down] = -1.0
    signal[weak_cross_down] = -0.4

    return signal


# ============================================================
#  Entry Strategy 3: Money Flow Zero-Line Cross
# ============================================================

def entry_mf_zero_cross(money_flow: pd.Series) -> pd.Series:
    """
    Money Flow zero-line cross with slope (thickness) confirmation.
    Rate of change of MFI = how fast money is moving.
    """
    signal = pd.Series(0.0, index=money_flow.index)

    mf_slope = money_flow.diff(3)  # 3-bar slope = "thickness"

    cross_up = (money_flow > 0) & (money_flow.shift(1) <= 0)
    cross_down = (money_flow < 0) & (money_flow.shift(1) >= 0)

    # Strong = crossing with momentum (thick wave)
    signal[cross_up & (mf_slope > 0.05)] = 1.0
    signal[cross_up & (mf_slope <= 0.05)] = 0.6
    signal[cross_down & (mf_slope < -0.05)] = -1.0
    signal[cross_down & (mf_slope >= -0.05)] = -0.6

    return signal


# ============================================================
#  Entry Strategy 4: Multi-Timeframe Alignment
# ============================================================

def compute_htf_trend(close: pd.Series, money_flow: pd.Series) -> pd.Series:
    """
    Simulate higher-timeframe trend using longer lookback.
    Weekly MF ≈ 5-day smoothed daily MF.
    """
    htf_mf = money_flow.rolling(5).mean()  # ~weekly on daily data
    htf_momentum_up = close.rolling(20).mean() > close.rolling(50).mean()

    # +1 bullish, -1 bearish, 0 neutral
    trend = pd.Series(0.0, index=close.index)
    trend[(htf_mf > 0.1) & htf_momentum_up] = 1.0
    trend[(htf_mf < -0.1) & ~htf_momentum_up] = -1.0
    return trend


def entry_multi_tf(htf_trend: pd.Series, blue_wave: pd.Series,
                   white_line: pd.Series, money_flow: pd.Series) -> pd.Series:
    """
    4H/24M adapted: HTF sets direction, LTF provides entry.
    Only take entries that agree with higher timeframe.
    """
    signal = pd.Series(0.0, index=htf_trend.index)

    # LTF green dot equivalent
    ltf_green = (white_line > blue_wave) & (white_line.shift(1) <= blue_wave.shift(1))
    ltf_red = (white_line < blue_wave) & (white_line.shift(1) >= blue_wave.shift(1))

    # MF curving up/down
    mf_up = money_flow > money_flow.shift(1)
    mf_down = money_flow < money_flow.shift(1)

    # Sniper entries: HTF agrees + LTF trigger
    signal[(htf_trend > 0) & ltf_green & mf_up] = 1.0
    signal[(htf_trend < 0) & ltf_red & mf_down] = -1.0

    return signal


# ============================================================
#  Entry Strategy 5: Divergence with Volume Confirmation
# ============================================================

def entry_divergence_vol(close: pd.Series, blue_wave: pd.Series,
                         volume: pd.Series, vwap_signal: pd.Series,
                         money_flow: pd.Series,
                         lookback: int = 20) -> pd.Series:
    """
    Vectorized divergence detection with volume confirmation.
    Price lower low + momentum higher low + declining volume = strong bullish div.
    """
    signal = pd.Series(0.0, index=close.index)
    vol_sma = volume.rolling(20).mean()

    # Rolling min/max for price and momentum
    p_cur_min = close.rolling(lookback).min()
    p_prev_min = close.shift(lookback).rolling(lookback).min()
    m_cur_min = blue_wave.rolling(lookback).min()
    m_prev_min = blue_wave.shift(lookback).rolling(lookback).min()

    p_cur_max = close.rolling(lookback).max()
    p_prev_max = close.shift(lookback).rolling(lookback).max()
    m_cur_max = blue_wave.rolling(lookback).max()
    m_prev_max = blue_wave.shift(lookback).rolling(lookback).max()

    # Bullish: price lower low, momentum higher low
    bull_div = (p_cur_min < p_prev_min) & (m_cur_min > m_prev_min)
    # Bearish: price higher high, momentum lower high
    bear_div = (p_cur_max > p_prev_max) & (m_cur_max < m_prev_max)

    vol_declining = volume < vol_sma
    vwap_cross_up = (vwap_signal > 0) & (vwap_signal.shift(1) <= 0)
    vwap_cross_down = (vwap_signal < 0) & (vwap_signal.shift(1) >= 0)
    mf_up = money_flow > money_flow.shift(1)
    mf_down = money_flow < money_flow.shift(1)

    # Bullish divergence strength
    bull_strength = bull_div.astype(float) * 0.5
    bull_strength += (bull_div & vol_declining).astype(float) * 0.25
    bull_strength += (bull_div & vwap_cross_up).astype(float) * 0.15
    bull_strength += (bull_div & mf_up).astype(float) * 0.10
    signal[bull_div] = bull_strength[bull_div].clip(0, 1)

    # Bearish divergence strength
    bear_strength = bear_div.astype(float) * -0.5
    bear_strength -= (bear_div & vol_declining).astype(float) * 0.25
    bear_strength -= (bear_div & vwap_cross_down).astype(float) * 0.15
    bear_strength -= (bear_div & mf_down).astype(float) * 0.10
    signal[bear_div] = bear_strength[bear_div].clip(-1, 0)

    return signal


# ============================================================
#  Composite Signal v2
# ============================================================

def composite_mc_v2(close: pd.Series, high: pd.Series, low: pd.Series,
                    volume: pd.Series,
                    w_trigger: float = 0.25,
                    w_vwap: float = 0.20,
                    w_mf: float = 0.20,
                    w_mtf: float = 0.20,
                    w_div: float = 0.15) -> pd.Series:
    """
    Combined Market Cipher v2 signal.
    5 entry strategies weighted and blended.
    Money Flow acts as a master filter (Golden Rule).
    """
    # Compute indicators
    blue_wave, white_line = compute_momentum(close)
    money_flow = compute_money_flow(close, high, low, volume)
    vwap_signal = compute_vwap_signal(close, high, low, volume)
    ribbons = compute_ema_ribbons(close)

    # Vol regime for adaptive thresholds
    daily_vol = close.pct_change().rolling(20).std() * np.sqrt(365)
    avg_vol = close.pct_change().rolling(60).std() * np.sqrt(365)
    vol_regime = (daily_vol / avg_vol.replace(0, np.nan)).fillna(1.0)

    # Higher timeframe trend
    htf_trend = compute_htf_trend(close, money_flow)

    # Entry signals
    s1 = entry_white_line_cut(blue_wave, white_line, vol_regime)
    s2 = entry_vwap_curve_cross(vwap_signal)
    s3 = entry_mf_zero_cross(money_flow)
    s4 = entry_multi_tf(htf_trend, blue_wave, white_line, money_flow)
    s5 = entry_divergence_vol(close, blue_wave, volume, vwap_signal, money_flow)

    # Weighted composite
    raw = (w_trigger * s1 + w_vwap * s2 + w_mf * s3 +
           w_mtf * s4 + w_div * s5)

    # Master filter: Money Flow direction scales the signal
    # When MF > 0 (money entering): allow full long signals
    # When MF < 0 (money leaving): suppress long signals, allow shorts
    mf_filter = money_flow.clip(-1, 1)

    # Scale: if signal is long but MF is negative, reduce by 70%
    filtered = raw.copy()
    long_mask = raw > 0
    short_mask = raw < 0
    filtered[long_mask & (mf_filter < 0)] *= 0.3
    filtered[short_mask & (mf_filter > 0)] *= 0.3

    # EMA ribbon confirmation boost (±20%)
    filtered[long_mask & ribbons['bullish']] *= 1.2
    filtered[short_mask & ribbons['bearish']] *= 1.2

    return filtered.clip(-1, 1)
