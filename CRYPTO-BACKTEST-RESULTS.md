# White Light Crypto Backtest Results
## Feb 26, 2026

### Grid Search — Best Thresholds

| Asset | Bull | Bear | Sharpe | CAGR | Max DD | Sortino | Total Return | Period |
|-------|------|------|--------|------|--------|---------|-------------|--------|
| **BTC** | +0.30 | -0.30 | **1.544** | 26.1% | 19.3% | 1.802 | 12.2x | 2014-2026 |
| **ETH** | +0.05 | -0.05 | **1.236** | 16.9% | 21.2% | 1.315 | 3.3x | 2017-2026 |

### Buy & Hold Comparison (full period)

| Asset | CAGR | Sharpe | Max DD |
|-------|------|--------|--------|
| BTC Buy&Hold | 68.8% | 1.122 | 83.4% |
| ETH Buy&Hold | 19.8% | 0.638 | 83.2% |

### Monte Carlo (1000 simulations, random windows)

#### BTC (bull=+0.30, bear=-0.30)
| Metric | White Light | Buy & Hold |
|--------|-------------|------------|
| Median CAGR | 27.0% | 73.9% |
| Median Sharpe | **1.568** | 1.156 |
| Median Max DD | **19.3%** | 83.4% |
| WL beats B&H Sharpe | **89.0%** | - |
| WL beats B&H MaxDD | **100.0%** | - |

#### ETH (bull=+0.05, bear=-0.05)
| Metric | White Light | Buy & Hold |
|--------|-------------|------------|
| Median CAGR | 18.3% | 54.9% |
| Median Sharpe | **1.279** | 0.952 |
| Median Max DD | **18.4%** | 79.4% |
| WL beats B&H Sharpe | **93.9%** | - |
| WL beats B&H MaxDD | **100.0%** | - |

### Key Insight
White Light trades CAGR for dramatically better risk-adjusted returns. BTC buy-and-hold does 69% CAGR but with 83% drawdowns. White Light delivers 26% CAGR with only 19% max drawdown — a Sharpe of 1.54 vs 1.12.

The strategy works as a **risk management layer**: you give up raw upside but sleep at night.
