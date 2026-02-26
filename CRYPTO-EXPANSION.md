# White Light Crypto Expansion — Design Doc

## Current State
- **Asset universe:** NDX → TQQQ/SQQQ/BIL (equity only, market hours only)
- **Execution:** Once daily, 30 min before close (20:30 UTC cron)
- **Broker:** Alpaca (paper), same keys already support 73 crypto assets
- **Signal:** 7 sub-strategies with weighted composite → allocation tiers

## Crypto Expansion Plan

### Phase 1: BTC/ETH via Alpaca (Same Infrastructure)
**Why Alpaca:** We already have keys, paper trading, and the execution layer.
Alpaca supports BTC/USD, ETH/USD, SOL/USD with fractional shares, 24/7.

**New config section:**
```yaml
crypto:
  enabled: true
  assets:
    - BTC/USD   # Bitcoin
    - ETH/USD   # Ethereum  
  allocation_pct: 20  # % of total portfolio for crypto
  execution_interval: "4h"  # Run every 4 hours (24/7)
  data_source: "alpaca"  # Alpaca crypto data API
```

**Signals to adapt:**
| Equity Strategy | Crypto Equivalent | Notes |
|----------------|-------------------|-------|
| S1 Primary Trend (50/250 SMA) | 50/250 4h candles | Same logic, shorter timeframes |
| S2 Intermediate (20/100 SMA) | 20/100 4h candles | |
| S5 Momentum Velocity (ROC14) | ROC14 on 4h | Crypto moves faster |
| S6 Bollinger Mean Rev | 20-period 4h Bollinger | Crypto mean reverts hard |
| S7 Vol Regime | 30-day realized vol | BTC vol ranges 40-100% annualized |

**Key differences from equity:**
- 24/7 execution → cron every 4h instead of once daily
- Higher volatility → tighter allocation caps
- No leveraged ETF (TQQQ) → direct BTC/ETH exposure
- Cash = USDC or USD in Alpaca account

### Phase 2: White Light Improvements

**A. Grid Search Optimization**
Current thresholds are hand-picked (+0.2 for TQQQ, -0.1 for neutral).
Run parameter sweep:
- Bull threshold: [0.10, 0.15, 0.20, 0.25, 0.30]
- Bear threshold: [-0.05, -0.10, -0.15, -0.20]
- Sub-strategy weights: use Sharpe-ratio weighted optimization
- Generate heatmap of Sharpe × threshold combinations

**B. Volatility Targeting**
Instead of fixed allocation %:
```
target_vol = 15%  # annualized
position_size = target_vol / realized_vol * base_allocation
```
When BTC vol is 80%, size down. When it's 40%, size up.
Same for TQQQ — realized vol of ~60% means smaller positions than raw signal suggests.

**C. Factor Model Enhancement**
Treat each sub-strategy score as a factor:
- Estimate factor covariance matrix (7×7)
- Use factor loadings to construct minimum-variance composite
- Reduces overfitting vs. static weights
- Can adapt weights over time as market regime changes

**D. Sentiment Signal (NEW — S8)**
Use our Twitter/news scraping infrastructure:
- CMNN scraper → political/macro headlines
- AI intel feed → market-moving tweets
- Score sentiment via LLM (bullish/bearish/neutral)
- Add as S8_news_sentiment with 0.10 weight

### Phase 3: Prediction Market Integration
Add Polymarket as a separate strategy module:
- Market making on high-volume political markets (1-3%/mo)
- AI probability arbitrage using CMNN news feed
- Requires: Polygon wallet, USDC, separate cron job

## Implementation Order
1. **BTC/ETH on Alpaca** — reuse existing infra, add crypto data + 4h cron
2. **Grid search optimization** — backtest sweep for optimal thresholds
3. **Volatility targeting** — position sizing improvement
4. **News sentiment signal** — leverage existing scraping infra
5. **Polymarket bot** — separate project, uses Polymarket bot repo as base
