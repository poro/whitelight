# White Light

Automated position-trading engine that trades **TQQQ/SQQQ/BIL** (3x leveraged NASDAQ 100 ETFs + T-bill bonds) using volatility-targeted allocation. The system dynamically scales leverage based on realized volatility, protecting against leveraged decay during turbulent markets while capturing full upside in calm conditions.

## Strategy Overview

### Core Rule: Volatility Targeting

```
TQQQ weight = min(target_vol / realized_vol_20d, 1.0)
```

When volatility is low, the strategy allocates up to **100% TQQQ** (this is when 3x leverage compounds best). When volatility spikes, the position is automatically reduced and the remainder is parked in **BIL** (1-3 Month T-Bill ETF, ~5% yield), protecting against leveraged decay while earning risk-free yield.

### SQQQ Crash Sprint

During the **first 15 trading days** after NDX crosses below the 200-day SMA *and* realized volatility exceeds 25%, the strategy allocates **30% to SQQQ**. This captures the initial leg of a crash where SQQQ outperforms cash. After 15 days, SQQQ decays too fast and the strategy rotates to BIL instead.

### Safety Rules

- **No direct flip**: The system never switches directly from TQQQ to SQQQ (or vice versa). It must pass through 100% cash/BIL for one day to prevent whipsaws.
- **Sells before buys**: The executor always sells existing positions before buying new ones, freeing buying power.
- **Minimum rebalance threshold**: Skips trades if allocation shift is less than 5%, reducing unnecessary turnover.

## Instruments

| Symbol | Description | Role |
|--------|-------------|------|
| **TQQQ** | ProShares UltraPro QQQ (3x Long) | Primary growth instrument |
| **SQQQ** | ProShares UltraPro Short QQQ (3x Short) | Crash sprint hedge (first 15 days) |
| **BIL** | SPDR Bloomberg 1-3 Month T-Bill ETF | Safe haven, earns ~5% yield |
| **NDX** | NASDAQ-100 Index | Signal source (not traded) |

## Backtest Results

### Performance Summary (2011 - 2025)

Backtest period: **March 2011 to December 2025** (~14.8 years), starting with $100,000.

| Metric | Vol-Target Strategy | Buy & Hold TQQQ |
|--------|-------------------|-----------------|
| **Final Value** | **$15,499,273** | $14,579,784 |
| **CAGR** | **40.6%** | 40.1% |
| **Max Drawdown** | **-52.1%** | -81.7% |
| **Sharpe Ratio** | 0.87 | -- |
| **Sortino Ratio** | 0.82 | -- |
| **Calmar Ratio** | 0.78 | -- |

The strategy beats buy-and-hold TQQQ by ~$920,000 while **cutting the worst drawdown nearly in half** (-52% vs -82%).

### Trade Statistics

| Metric | Value |
|--------|-------|
| Total Trades | 528 |
| Win Rate | 75.0% |
| Profit Factor | 5.14 |
| Avg Winning Trade | -- |
| Avg Trade Duration | -- |

### Yearly Returns

| Year | Start Value | End Value | Return | Max DD | Avg TQQQ | Avg SQQQ | Avg BIL |
|------|------------|-----------|--------|--------|----------|----------|---------|
| 2011 | $100,000 | $97,753 | -2.2% | -32.8% | 87.2% | 1.2% | 11.6% |
| 2012 | $97,753 | $124,050 | +26.9% | -14.5% | 88.3% | 0.0% | 11.7% |
| 2013 | $124,050 | $272,029 | +119.3% | -7.5% | 100.0% | 0.0% | 0.0% |
| 2014 | $272,029 | $356,891 | +31.2% | -13.9% | 91.8% | 0.0% | 8.2% |
| 2015 | $356,891 | $369,803 | +3.6% | -24.8% | 84.2% | 0.0% | 15.8% |
| 2016 | $369,803 | $415,398 | +12.3% | -26.2% | 84.3% | 0.8% | 14.9% |
| 2017 | $415,398 | $884,547 | +112.9% | -3.3% | 100.0% | 0.0% | 0.0% |
| 2018 | $884,547 | $655,789 | -25.9% | -34.5% | 77.5% | 2.4% | 20.1% |
| 2019 | $655,789 | $1,456,768 | +122.2% | -9.7% | 96.7% | 0.0% | 3.3% |
| 2020 | $1,456,768 | $3,166,965 | +117.4% | -23.3% | 86.7% | 1.5% | 11.8% |
| 2021 | $3,166,965 | $6,447,879 | +103.6% | -7.3% | 97.5% | 0.0% | 2.5% |
| 2022 | $6,447,879 | $3,745,879 | -41.9% | -52.1% | 52.8% | 4.5% | 42.6% |
| 2023 | $3,745,879 | $10,905,101 | +191.1% | -8.3% | 96.3% | 0.0% | 3.7% |
| 2024 | $10,905,101 | $14,419,093 | +32.2% | -17.3% | 91.5% | 0.0% | 8.5% |
| 2025 | $14,419,093 | $15,499,273 | +7.5% | -6.6% | 100.0% | 0.0% | 0.0% |

**Key observations:**
- **11 positive years, 4 negative years** (2011, 2018, 2022, and a flat 2015)
- **Best year: 2023** at +191.1% — the strategy went nearly all-in on TQQQ during the AI rally
- **Worst year: 2022** at -41.9% — but the strategy correctly de-risked to 53% TQQQ / 43% BIL, saving significant capital vs buy-and-hold
- **Bull markets (2013, 2017, 2021)**: 100% TQQQ allocation captures full upside
- **Bear markets (2018, 2022)**: Automatic de-risking to 50-78% TQQQ with remainder in BIL

### Behavior During Market Crashes

| Period | Strategy Return | TQQQ B&H Return | Avg TQQQ | Avg SQQQ | Avg BIL |
|--------|----------------|-----------------|----------|----------|---------|
| 2011 Debt Ceiling | -32.3% | -41.5% | 82% | 2% | 16% |
| 2015-16 China/Oil | -19.4% | -30.2% | 78% | 1% | 21% |
| 2018 Q4 Selloff | -45.0% | -48.2% | 76% | 3% | 21% |
| COVID Crash (Feb-Mar 2020) | -41.5% | -69.8% | 71% | 5% | 24% |
| 2022 Bear Market | -44.7% | -81.0% | 53% | 5% | 43% |

The strategy's primary value-add is **drawdown reduction**. During COVID, it limited losses to -42% vs -70% for buy-and-hold. During 2022, it lost -45% vs -81%. This is achieved by automatically scaling back TQQQ exposure when volatility spikes and parking capital in BIL.

### Rolling 5-Year Windows

Analysis of all possible 5-year holding periods (2,717 windows):

| Metric | Value |
|--------|-------|
| Median ending multiple | 6.0x |
| Median CAGR | 43.7% |
| Worst case | 2.4x (19.6% CAGR) |
| Best case | 12.8x (66.7% CAGR) |
| % positive | 100% |
| % doubled | 100% |
| % achieved 5x | 66.9% |

**$20,000 invested for 5 years** would have grown to a median of **$120,000** across all historical windows. The worst-case 5-year outcome was still a 2.4x return ($48,000). No 5-year period lost money.

### Dollar-Cost Averaging

$10,000 invested annually on March 1st from 2011 through 2025:

| Metric | Value |
|--------|-------|
| Total invested | $150,000 |
| Final value | ~$7,991,237 |
| Return multiple | ~53x |

## Architecture

```
whitelight/
├── src/whitelight/
│   ├── main.py               # Pipeline orchestrator
│   ├── config.py              # Pydantic Settings (YAML + env vars)
│   ├── models.py              # Domain models (TargetAllocation, etc.)
│   ├── constants.py           # Tickers, SMA windows, time constants
│   ├── data/
│   │   ├── polygon_client.py  # Market data from Polygon.io / Massive
│   │   ├── cache.py           # Parquet cache manager
│   │   ├── sync.py            # Fetch delta -> append -> validate
│   │   └── calendar.py        # Market calendar
│   ├── strategy/
│   │   ├── engine.py          # Runs all 7 sub-strategies
│   │   ├── combiner.py        # Volatility-targeted allocation
│   │   ├── indicators.py      # SMA, ROC, Bollinger, RSI, volatility
│   │   └── substrats/         # 7 sub-strategy implementations
│   ├── execution/
│   │   ├── executor.py        # Portfolio rebalancing (TQQQ, SQQQ, BIL)
│   │   ├── reconciler.py      # Target vs current positions
│   │   └── retry.py           # Exponential backoff
│   ├── providers/
│   │   ├── brokerages/        # Alpaca + IBKR with failover
│   │   ├── alerts/            # Telegram, Pushover, SNS, noop
│   │   └── secrets/           # AWS, pass, env vars
│   └── backtest/
│       ├── runner.py          # Historical replay engine
│       └── metrics.py         # Sharpe, Sortino, Calmar, etc.
├── config/
│   ├── default.yaml           # Base configuration
│   ├── paper.yaml             # Paper trading config
│   └── aws.yaml               # AWS deployment overrides
├── tests/                     # Unit + integration tests
├── data/                      # Parquet cache (gitignored)
└── scripts/                   # Seed cache, validate, etc.
```

### Sub-Strategies (Signal Generation)

7 sub-strategies generate signals from NDX price data. These feed the composite score for reporting, while the combiner uses volatility targeting for actual allocation.

| # | Strategy | Type | Weight | Key Indicators |
|---|----------|------|--------|----------------|
| S1 | Primary Trend | Trend | 0.25 | 50/250 SMA regime with hysteresis |
| S2 | Intermediate Trend | Trend | 0.15 | 20/100 SMA crossover |
| S3 | Short-Term Trend | Trend | 0.10 | 10/30 SMA |
| S4 | Trend Strength | Trend | 0.10 | 60-day regression slope, z-scored |
| S5 | Momentum Velocity | Mean Rev | 0.15 | 14-day ROC + acceleration |
| S6 | Bollinger Mean Rev | Mean Rev | 0.15 | 20-day Bollinger %B + trend filter |
| S7 | Volatility Regime | Mean Rev | 0.10 | 20/60-day realized vol ratio |

### Execution Pipeline

```
Boot -> Data Sync (Polygon/Massive -> Parquet cache)
     -> Strategy Engine (7 sub-strategies -> signals)
     -> Combiner (vol-targeting -> TQQQ/SQQQ/BIL allocation)
     -> Executor (compute deltas -> sell first -> buy)
     -> Telemetry (alerts via Telegram/Pushover/SNS)
     -> Shutdown
```

### Brokerage Integration

- **Primary**: Alpaca (paper + live)
- **Secondary**: IBKR (Interactive Brokers via ib_async)
- **Failover**: Automatic failover from primary to secondary
- Portfolio reads aggregate positions across both brokerages

## Setup

### Prerequisites

- Python 3.11+
- Alpaca account (paper or live)
- Polygon.io or Massive API key for market data

### Installation

```bash
git clone <repo-url> whitelight
cd whitelight
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required environment variables:

```env
WL_DEPLOYMENT_MODE=paper          # paper or local
WL_POLYGON_API_KEY=your_key       # Polygon.io or Massive API key
WL_ALPACA_API_KEY=your_key        # Alpaca API key
WL_ALPACA_API_SECRET=your_secret  # Alpaca API secret
```

### Seed Historical Data

```bash
python scripts/seed_cache.py
```

This downloads NDX, TQQQ, and SQQQ daily data back to 1985 (or inception).

### Run (Dry Run)

```bash
python -m whitelight run --dry-run
```

This runs the full pipeline (data sync, strategy, allocation) without placing any orders.

### Run (Live/Paper)

```bash
python -m whitelight run
```

### Cron Setup (Linux)

Run daily at 3:45 PM ET (15 minutes before market close):

```bash
45 15 * * 1-5 cd /path/to/whitelight && source .venv/bin/activate && python -m whitelight run >> logs/cron.log 2>&1
```

## Testing

```bash
# All unit tests
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ --cov=whitelight --cov-report=term-missing
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Volatility targeting | Mathematically optimal for leveraged ETFs: reduce exposure when vol is high (leverage decay zone) |
| BIL for idle cash | Earns ~5% risk-free yield vs 0% sitting in brokerage cash |
| SQQQ sprint (15 days max) | SQQQ only works in fast crashes; after 15 days volatility decay dominates |
| Parquet cache | 10-100x faster than CSV for columnar time-series reads |
| Decimal for money | Eliminates floating-point rounding errors in financial calculations |
| Stateless sub-strategies | `compute()` derives signal purely from input data; trivial to test |
| Sells before buys | Frees buying power for the next trade |

## Risk Disclaimer

This software is for educational and research purposes. Past backtested performance does not guarantee future results. Leveraged ETFs (TQQQ, SQQQ) carry significant risk including potential total loss. The maximum drawdown in backtesting was -52.1%. Always use paper trading to validate before risking real capital.
