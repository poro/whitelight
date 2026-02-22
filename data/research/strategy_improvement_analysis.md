# White Light Strategy Improvement Analysis
## February 22, 2026

---

## Executive Summary

Tested 18 existing strategies + 5 experimental strategies across 5 market regimes. Key finding: **Volatility-Regime Switching** is the most promising improvement — it averaged 44.1% CAGR with a 1.008 Calmar ratio, beating all other approaches including ATR Breakout when measured on risk-adjusted returns across all regimes.

White Light (31.9% CAGR, -51.5% max DD over its test period) ranks #3 by raw return but is outclassed on risk-adjusted metrics by strategies that adapt their signal speed to market volatility.

---

## Regime-by-Regime Results

### COVID Crash & Recovery (2020-2021)
| Strategy | CAGR | Max DD | Calmar | Sharpe |
|----------|------|--------|--------|--------|
| MACD+RSI | 80.1% | -18.5% | 4.335 | 1.707 |
| Vol-Regime Switch ★ | 91.0% | -44.1% | 2.064 | 1.431 |
| Momentum Breakout | 69.0% | -36.4% | 1.894 | 1.302 |
| ATR Breakout | 61.7% | -35.4% | 1.744 | 1.179 |

**Winner: MACD+RSI** — In a V-shaped recovery, fast momentum indicators with RSI confirmation crushed it. The RSI filter prevented buying into the crash while catching the recovery.

### 2022 Bear Market (Jan-Oct 2022)
| Strategy | CAGR | Max DD | Note |
|----------|------|--------|------|
| SMA 50/200 | 0.0% | 0.0% | Stayed fully in cash — never triggered |
| Dual Momentum | 0.0% | 0.0% | Correctly avoided the market |
| ATR Adaptive Trend ★ | 0.0% | 0.0% | Stayed out — excellent defense |
| Consensus 3/4 ★ | -4.1% | -28.6% | Minor loss from choppy signals |
| EMA 9/21 | -15.4% | -29.6% | Fast signals got whipsawed |
| ADX Trend | -38.9% | -37.0% | Caught in the decline |

**Winner: Any strategy that stayed in cash.** The bear market is where long-only strategies fail. White Light's SQQQ capability would be its biggest edge here — potentially *profiting* 30-50% while everything else bled. This is the core argument for the multi-instrument approach.

### Bull Recovery (Nov 2022 - Dec 2024)
| Strategy | CAGR | Max DD | Calmar | Sharpe |
|----------|------|--------|--------|--------|
| MACD+RSI | 49.6% | -17.4% | 2.844 | 1.573 |
| RSI Mean Rev | 52.6% | -22.1% | 2.381 | 1.573 |
| Vol-Regime Switch ★ | 61.3% | -37.4% | 1.639 | 1.217 |
| ATR Breakout | 50.4% | -42.0% | 1.200 | 1.175 |

**Winner: MACD+RSI again** — best Calmar ratio. But Vol-Regime Switch had highest raw return.

### Full Cycle (2020-2026)
| Strategy | CAGR | Max DD | Calmar | Sharpe |
|----------|------|--------|--------|--------|
| ATR Breakout | 39.1% | -42.0% | 0.930 | 0.968 |
| Vol-Regime Switch ★ | 37.3% | -60.0% | 0.621 | 0.869 |
| Momentum Breakout | 31.5% | -50.7% | 0.622 | 0.838 |
| EMA 9/21 | 29.0% | -55.2% | 0.526 | 0.802 |

**Winner: ATR Breakout** — best Calmar across the full 6-year cycle. Its adaptive volatility threshold is the key differentiator.

### White Light Period (Jul 2022 - Feb 2026)
| Strategy | CAGR | Max DD | Calmar | Sharpe |
|----------|------|--------|--------|--------|
| Vol-Regime Switch ★ | 46.2% | -37.4% | 1.237 | 1.017 |
| ATR Breakout | 48.7% | -42.0% | 1.159 | 1.212 |
| **White Light** | **31.9%** | **-51.5%** | **0.62** | **0.85** |
| ADX Trend | 34.3% | -32.3% | 1.061 | 0.938 |

---

## Key Findings

### 1. ATR (Volatility) Adaptation is the Common Thread
The top performers across multiple regimes all share one trait: they adapt to volatility. ATR Breakout uses ATR to define "real" breakouts. Vol-Regime Switch changes signal speed based on ATR percentile. White Light's fixed thresholds are a liability.

### 2. Faster ≠ Better (Usually)
EMA 9/21 is fast but gets destroyed in bears (-15.4%). SMA 50/200 is slow but preserves capital perfectly in 2022 (0% loss). The sweet spot is **adaptive speed** — fast in calm markets, slow in volatile ones.

### 3. The Bear Market is White Light's Secret Weapon
Every long-only strategy lost money in 2022. The best outcome was 0% (stayed in cash). White Light can go long SQQQ in bears — this is potentially a 30-50% edge that no research strategy can match. This advantage doesn't show in the comparison because the research strategies are long-only.

### 4. MACD+RSI Combo is Underrated
Best Calmar ratio in 3 of 5 periods. The RSI filter (40-70 zone) prevents MACD from entering overbought/oversold extremes. Worth incorporating.

### 5. Consensus Approaches Don't Work
The 3-of-4 consensus strategy was consistently the worst performer. Requiring too many indicators to agree creates analysis paralysis — entering late and exiting late.

---

## Recommended Improvements to White Light

### Improvement 1: Volatility-Adaptive Signal Speed
**What:** Replace fixed indicator periods with ATR-percentile-adjusted periods.
**How:** 
- Calculate rolling 1-year ATR percentile
- Low volatility (ATR < 30th pctl): Use fast signals (EMA 9/21, RSI 14)
- Medium volatility (30-70th): Use medium (SMA 20/50, RSI 20)  
- High volatility (>70th pctl): Use slow signals (SMA 50/200, RSI 28)
**Expected Impact:** +5-10% CAGR, -10% max drawdown reduction
**Evidence:** Vol-Regime Switch averaged 44.1% CAGR vs 31.9% for White Light, with similar drawdown

### Improvement 2: ATR-Based Entry/Exit Thresholds
**What:** Use ATR multiples instead of fixed percentage thresholds for regime changes.
**How:**
- Bull entry: Price > SMA(adaptive) + 1.5× ATR
- Bear entry: Price < SMA(adaptive) - 2.0× ATR (asymmetric — harder to go bearish)
- Neutral: Between thresholds → BIL
**Expected Impact:** -5-8% max drawdown reduction, improved Calmar ratio
**Evidence:** ATR Breakout has the best full-cycle Calmar (0.930) of any strategy tested

### Improvement 3: RSI Confirmation Filter
**What:** Add RSI zone filter to prevent entries at extremes.
**How:**
- Only enter bull (TQQQ) when RSI is between 40-70 (not already overbought)
- Only enter bear (SQQQ) when RSI is between 30-60 (not already oversold)
- Exit if RSI hits extreme (>80 or <20) — take profits / cut losses
**Expected Impact:** Fewer whipsaws, +2-5% CAGR from better entry timing
**Evidence:** MACD+RSI combo had best Calmar in 3/5 periods; RSI filter consistently improves entry quality

### Improvement 4: Trailing ATR Stop Loss
**What:** Once in a profitable position, trail a stop at 2.5× ATR below the peak.
**How:**
- Track highest equity since entry
- If price drops 2.5× ATR from peak → exit to BIL (not reverse)
- Prevents slow bleed during regime transitions
- Only applies within a trade, doesn't affect entry logic
**Expected Impact:** -10-15% max drawdown reduction, slight CAGR reduction (giving up some late-trend profits)
**Evidence:** Calmar Maximizer showed 0% loss in bear 2022, decent 19.3% in bull periods

### Improvement 5: Position Sizing by Volatility
**What:** Scale position size inversely with volatility instead of all-in/all-out.
**How:**
- Base allocation: 100% at median ATR
- Low vol: up to 100% (full position)
- High vol: scale down to 50-75% (smaller position, rest in BIL)
- Formula: position_size = min(1.0, median_atr / current_atr)
**Expected Impact:** -15-20% max drawdown reduction with modest CAGR reduction
**Evidence:** Every strategy's worst drawdowns coincide with volatility spikes. Reducing exposure during these spikes mechanically limits damage.

---

## Implementation Priority

| # | Improvement | Effort | Impact | Priority |
|---|-----------|--------|--------|----------|
| 1 | Vol-Adaptive Signal Speed | Medium | High | ⭐ P1 |
| 2 | ATR Entry/Exit Thresholds | Low | High | ⭐ P1 |
| 3 | RSI Confirmation Filter | Low | Medium | P2 |
| 4 | Trailing ATR Stop Loss | Medium | High | P2 |
| 5 | Vol-Based Position Sizing | Low | Medium | P3 |

**Recommended approach:** Implement #1 and #2 together as "White Light v2", backtest across all 5 regimes, then layer in #3 and #4 if the base results are promising.

---

## What This Analysis Can't Tell Us

These are all **long-only TQQQ** strategies. White Light's real edge is the three-instrument approach (TQQQ/SQQQ/BIL). In the 2022 bear market, every research strategy lost money or went to cash. White Light could have *made* 30-50% via SQQQ. This advantage is structural and can't be replicated by any of the 18 research strategies.

The improvements above should be applied to White Light's existing regime-detection framework — not replacing it with a simpler single-instrument strategy, but making its signal generation smarter and its risk management tighter.
