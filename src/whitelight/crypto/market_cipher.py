"""
Market Cipher A & B Implementation for White Light Crypto Strategy.

Based on pseudocode breakdown of MarketCipher indicator suite.
Components:
  - MCA: EMA ribbons, trend reversal detection
  - MCB: Momentum waves, Money Flow Index, VWAP, Trigger dots
  
Strategies:
  1. Multi-Timeframe Confluence
  2. Pro Divergence
  3. 4H/24M Anchor-Trigger
"""

import numpy as np
import pandas as pd
from typing import Optional


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def compute_mca(close: pd.Series) -> pd.DataFrame:
    """Market Cipher A — EMA ribbon crossovers and trend signals."""
    ema_fast = ema(close, 9)
    ema_mid = ema(close, 21)
    ema_slow = ema(close, 50)
    ema_trend = ema(close, 200)

    # Bullish: fast > mid > slow (ribbon expanding up)
    bullish_ribbon = (ema_fast > ema_mid) & (ema_mid > ema_slow)
    bearish_ribbon = (ema_fast < ema_mid) & (ema_mid < ema_slow)

    # EMA cross signals
    fast_cross_up = (ema_fast > ema_mid) & (ema_fast.shift(1) <= ema_mid.shift(1))
    fast_cross_down = (ema_fast < ema_mid) & (ema_fast.shift(1) >= ema_mid.shift(1))

    # Trend reversal: bearish-to-bullish ribbon flip
    prev_bearish = bearish_ribbon.shift(1).fillna(False)
    blue_triangle = bullish_ribbon & prev_bearish  # reversal signal

    return pd.DataFrame({
        'ema_fast': ema_fast,
        'ema_mid': ema_mid,
        'ema_slow': ema_slow,
        'ema_trend': ema_trend,
        'bullish_ribbon': bullish_ribbon,
        'bearish_ribbon': bearish_ribbon,
        'fast_cross_up': fast_cross_up,
        'fast_cross_down': fast_cross_down,
        'blue_triangle': blue_triangle,
    }, index=close.index)


def compute_mcb(close: pd.Series, high: pd.Series, low: pd.Series,
                volume: pd.Series) -> pd.DataFrame:
    """Market Cipher B — Momentum, Money Flow, VWAP, Trigger dots."""

    # 1. Momentum Waves (weighted Stochastic RSI-like oscillator)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # Stochastic RSI
    rsi_min = rsi.rolling(14).min()
    rsi_max = rsi.rolling(14).max()
    stoch_rsi = (rsi - rsi_min) / (rsi_max - rsi_min).replace(0, np.nan)
    stoch_rsi = stoch_rsi.fillna(0.5)

    # Smooth and center around zero (-1 to +1)
    momentum = ema(stoch_rsi, 3) * 2 - 1  # range [-1, 1]
    momentum_smooth = ema(momentum, 5)

    # 2. Money Flow Index (volume-weighted)
    typical_price = (high + low + close) / 3
    raw_mf = typical_price * volume
    pos_mf = raw_mf.where(typical_price > typical_price.shift(1), 0.0).rolling(14).sum()
    neg_mf = raw_mf.where(typical_price < typical_price.shift(1), 0.0).rolling(14).sum()
    mfi = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
    # Normalize to [-1, 1]
    money_flow = (mfi - 50) / 50

    # 3. VWAP (rolling, normalized around zero)
    cum_vol = volume.rolling(20).sum()
    cum_pv = (typical_price * volume).rolling(20).sum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    # Normalize: distance from VWAP as % of price, scaled
    vwap_signal = (close - vwap) / vwap.replace(0, np.nan)
    vwap_signal = vwap_signal.clip(-0.05, 0.05) * 20  # scale to [-1, 1]

    # VWAP zero cross direction
    vwap_cross_up = (vwap_signal > 0) & (vwap_signal.shift(1) <= 0)
    vwap_cross_down = (vwap_signal < 0) & (vwap_signal.shift(1) >= 0)
    # Strong cross: VWAP pointing toward zero before crossing
    vwap_slope = vwap_signal.diff()
    vwap_strong_cross_up = vwap_cross_up & (vwap_slope > 0)
    vwap_strong_cross_down = vwap_cross_down & (vwap_slope < 0)

    # 4. Trigger Dots (momentum crossover signals)
    green_dot = (momentum > momentum_smooth) & (momentum.shift(1) <= momentum_smooth.shift(1))
    red_dot = (momentum < momentum_smooth) & (momentum.shift(1) >= momentum_smooth.shift(1))

    return pd.DataFrame({
        'momentum': momentum,
        'momentum_smooth': momentum_smooth,
        'money_flow': money_flow,
        'vwap_signal': vwap_signal,
        'vwap_cross_up': vwap_cross_up,
        'vwap_cross_down': vwap_cross_down,
        'vwap_strong_cross_up': vwap_strong_cross_up,
        'vwap_strong_cross_down': vwap_strong_cross_down,
        'green_dot': green_dot,
        'red_dot': red_dot,
        'rsi': rsi,
        'mfi': mfi,
    }, index=close.index)


def detect_divergence(price: pd.Series, momentum: pd.Series,
                      lookback: int = 20) -> pd.DataFrame:
    """Detect bullish and bearish divergences between price and momentum."""
    bullish_div = pd.Series(False, index=price.index)
    bearish_div = pd.Series(False, index=price.index)

    for i in range(lookback * 2, len(price)):
        window_price = price.iloc[i - lookback:i + 1]
        window_mom = momentum.iloc[i - lookback:i + 1]

        # Find recent lows for bullish divergence
        price_min_idx = window_price.idxmin()
        price_prev_window = price.iloc[max(0, i - lookback * 2):i - lookback + 1]
        if len(price_prev_window) > 0:
            prev_min_idx = price_prev_window.idxmin()
            if (price.loc[price_min_idx] < price.loc[prev_min_idx] and
                    momentum.loc[price_min_idx] > momentum.loc[prev_min_idx]):
                bullish_div.iloc[i] = True

        # Find recent highs for bearish divergence
        price_max_idx = window_price.idxmax()
        price_prev_window = price.iloc[max(0, i - lookback * 2):i - lookback + 1]
        if len(price_prev_window) > 0:
            prev_max_idx = price_prev_window.idxmax()
            if (price.loc[price_max_idx] > price.loc[prev_max_idx] and
                    momentum.loc[price_max_idx] < momentum.loc[prev_max_idx]):
                bearish_div.iloc[i] = True

    return pd.DataFrame({
        'bullish_divergence': bullish_div,
        'bearish_divergence': bearish_div,
    }, index=price.index)


def strategy_confluence(mca: pd.DataFrame, mcb: pd.DataFrame,
                        htf_money_flow: Optional[pd.Series] = None) -> pd.Series:
    """
    Strategy 1: Multi-Timeframe Confluence.
    Returns signal: +1 (long), -1 (short), 0 (no signal).
    If htf_money_flow provided, uses it as trend filter.
    """
    signal = pd.Series(0, index=mca.index)

    # Trend bias from higher timeframe money flow (or same TF if not provided)
    if htf_money_flow is not None:
        trend_bullish = htf_money_flow > 0
        trend_bearish = htf_money_flow < 0
    else:
        trend_bullish = mcb['money_flow'] > 0
        trend_bearish = mcb['money_flow'] < 0

    # Long signals: bullish trend + MCA confirmation + MCB triggers
    long_signal = (
        trend_bullish &
        (mca['bullish_ribbon'] | mca['fast_cross_up'] | mca['blue_triangle']) &
        (mcb['green_dot'] | (mcb['momentum'] > mcb['momentum_smooth'])) &
        (mcb['vwap_signal'] > 0) &
        (mcb['money_flow'] > mcb['money_flow'].shift(1))  # MF curving up
    )

    # Short signals: bearish trend + MCA confirmation + MCB triggers
    short_signal = (
        trend_bearish &
        (mca['bearish_ribbon'] | mca['fast_cross_down']) &
        mcb['red_dot'] &
        (mcb['vwap_signal'] < 0) &
        (mcb['money_flow'] < mcb['money_flow'].shift(1))  # MF curving down
    )

    signal[long_signal] = 1
    signal[short_signal] = -1

    return signal


def strategy_divergence(close: pd.Series, mcb: pd.DataFrame,
                        lookback: int = 20) -> pd.Series:
    """
    Strategy 2: Pro Divergence — catch tops/bottoms.
    Returns signal: +1 (long), -1 (short), 0 (no signal).
    """
    divs = detect_divergence(close, mcb['momentum'], lookback)
    signal = pd.Series(0, index=close.index)

    # Bullish divergence + confirmation
    long = (
        divs['bullish_divergence'] &
        mcb['vwap_cross_up'] &
        (mcb['money_flow'] > mcb['money_flow'].shift(1)) &
        mcb['green_dot']
    )

    # Bearish divergence + confirmation
    short = (
        divs['bearish_divergence'] &
        mcb['vwap_cross_down'] &
        (mcb['money_flow'] < mcb['money_flow'].shift(1)) &
        mcb['red_dot']
    )

    signal[long] = 1
    signal[short] = -1

    return signal


def composite_mc_signal(close: pd.Series, high: pd.Series, low: pd.Series,
                        volume: pd.Series,
                        confluence_weight: float = 0.5,
                        divergence_weight: float = 0.3,
                        momentum_weight: float = 0.2) -> pd.Series:
    """
    Combined MarketCipher signal blending all strategies.
    Returns continuous signal [-1, +1].
    """
    mca = compute_mca(close)
    mcb = compute_mcb(close, high, low, volume)

    # Strategy signals
    conf = strategy_confluence(mca, mcb)
    div = strategy_divergence(close, mcb)

    # Raw momentum as continuous signal
    mom = mcb['momentum'].clip(-1, 1)

    # Money flow as trend filter (continuous)
    mf = mcb['money_flow'].clip(-1, 1)

    # Blend: discrete signals + continuous momentum + money flow bias
    composite = (
        confluence_weight * conf +
        divergence_weight * div +
        momentum_weight * mom
    )

    # Apply money flow as a scaling factor (reduce position when MF disagrees)
    mf_scale = (mf.clip(0, 1) * 2).clip(0.2, 1.0)  # when MF > 0, scale 0.2-1.0
    mf_scale[mf < 0] = 0.0  # no longs when money flowing out

    final = composite * mf_scale

    return final.clip(-1, 1)
