# White Light — Product Requirements Document

**Last Updated:** February 22, 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Architecture](#2-system-architecture)
3. [Core Trading Engine](#3-core-trading-engine)
4. [Research Dashboard (whitelight.game-agents.com)](#4-research-dashboard)
5. [Backtesting Infrastructure](#5-backtesting-infrastructure)
6. [Monte Carlo Analysis](#6-monte-carlo-analysis)
7. [Strategy Research Pipeline](#7-strategy-research-pipeline)
8. [Deployment & Operations](#8-deployment--operations)
9. [Performance Summary](#9-performance-summary)
10. [Roadmap](#10-roadmap)

---

## 1. Overview

White Light is an **automated position-trading system** that trades TQQQ/SQQQ/BIL (3x leveraged Nasdaq-100 ETFs + T-bill bonds) using volatility-targeted allocation. The system has two distinct components:

### A) Core Trading Engine (`/home/p0r0/clawd/projects/whitelight/`)
The automated trading system that runs daily, evaluates market conditions through 7 sub-strategies, and executes trades via Alpaca (paper or live). This is the "money machine."

### B) Research Dashboard (`/home/p0r0/clawd/projects/whitelight-web/`)
A web application at **whitelight.game-agents.com** that provides backtesting, Monte Carlo analysis, strategy comparison, investment projection, and research tools. This is the "brain" — used for analysis, validation, and planning.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   WHITE LIGHT SYSTEM                         │
├──────────────────────────┬──────────────────────────────────┤
│   CORE TRADING ENGINE    │       RESEARCH DASHBOARD          │
│   (whitelight/)          │       (whitelight-web/)           │
│                          │                                   │
│   7 Sub-Strategies       │   FastAPI + Vanilla JS            │
│   Vol-Targeted Combiner  │   Port 3012                       │
│   SQQQ Crash Sprints     │   whitelight.game-agents.com      │
│   Alpaca Execution       │                                   │
│   Cron: Weekdays 3:45 ET │   Reads from:                     │
│                          │   - strategies.db (SQLite)         │
│   Output:                │   - backtest_results/ (JSON)       │
│   - Daily trades         │   - monte_carlo/ (JSON + Parquet)  │
│   - Alerts (Telegram)    │   - commentary/ (JSON)             │
│   - Backtest results     │   - cache/ (Parquet price data)    │
│                          │                                   │
│   Data:                  │   Features:                        │
│   - NDX/TQQQ/SQQQ/QQQ   │   - 11 tabs (see §4)              │
│   - Parquet cache        │   - Interactive backtesting        │
│   - Polygon + yfinance   │   - Monte Carlo simulations        │
│                          │   - Investment calculator           │
│                          │   - Strategy encyclopedia           │
└──────────────────────────┴──────────────────────────────────┘
```

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Trading Engine | Python 3.12, Pydantic, pandas |
| Brokerage | Alpaca (paper + live), IBKR (secondary) |
| Market Data | yfinance (historical), Polygon.io (delta) |
| Data Storage | Parquet (price cache), SQLite (strategies), JSON (results) |
| Dashboard Backend | FastAPI, uvicorn |
| Dashboard Frontend | Vanilla HTML/JS, Chart.js |
| Hosting | systemd services on myra (Linux) |
| DNS/Tunnel | Cloudflare tunnel → port 3012 |
| Scheduling | OpenClaw cron (weekdays 20:45 UTC) |
| Backtesting | VectorBT 0.28.4, Backtrader 1.9.78 |

---

## 3. Core Trading Engine

### 3.1 Strategy: Volatility-Targeted Allocation

**Core Rule:**
```
TQQQ_weight = min(target_vol / realized_vol_20d, 1.0)
```

When volatility is low → up to 100% TQQQ (3x leverage compounds best).
When volatility spikes → reduce TQQQ, park remainder in BIL (~4-5% yield).

### 3.2 Sub-Strategies (Signal Generation)

7 sub-strategies evaluate NDX price data and produce signals. The combiner uses volatility targeting for actual allocation, while sub-strategy signals feed the composite score.

| # | Name | Type | Weight | Indicators |
|---|------|------|--------|------------|
| S1 | Primary Trend | Trend | 0.25 | 50/250 SMA regime with hysteresis |
| S2 | Intermediate Trend | Trend | 0.15 | 20/100 SMA crossover |
| S3 | Short-Term Trend | Trend | 0.10 | 10/30 SMA |
| S4 | Trend Strength | Trend | 0.10 | 60-day regression slope, z-scored |
| S5 | Momentum Velocity | Mean Rev | 0.15 | 14-day ROC + acceleration |
| S6 | Bollinger Mean Rev | Mean Rev | 0.15 | 20-day Bollinger %B + trend filter |
| S7 | Volatility Regime | Mean Rev | 0.10 | 20/60-day realized vol ratio |

### 3.3 SQQQ Crash Sprint

During the **first 15 trading days** after NDX crosses below the 200-day SMA *and* realized vol > 25%:
- Allocate 30% to SQQQ (captures initial crash leg)
- After 15 days → rotate to BIL (SQQQ decays too fast)

### 3.4 Safety Rules

- **No direct flip:** Never switch TQQQ→SQQQ or SQQQ→TQQQ directly. Must pass through 100% cash for one day.
- **Sells before buys:** Always free buying power first.
- **Minimum rebalance threshold:** Skip trades if allocation shift < 5%.

### 3.5 Instruments

| Symbol | Role |
|--------|------|
| **TQQQ** | Primary growth (3x Long Nasdaq-100) |
| **SQQQ** | Crash sprint hedge (3x Short Nasdaq-100) |
| **BIL** | Safe haven (~4-5% T-bill yield) |
| **NDX** | Signal source (not traded) |

### 3.6 Execution Pipeline

```
Cron trigger (3:45 PM ET, weekdays)
  → Data sync (yfinance/Polygon → Parquet cache)
  → Strategy engine (7 sub-strategies → signals)
  → Combiner (vol-targeting → TQQQ/SQQQ/BIL allocation)
  → Executor (compute deltas → sell first → buy)
  → Alerts (Telegram via OpenClaw)
  → Done
```

### 3.7 v2 Combiner (Experimental)

An enhanced combiner with 5 improvements over v1:
- **Vol-adaptive weights:** Fast signals (S3) get more weight in calm markets; slow signals (S1) dominate in volatile markets
- **ATR-based entry/exit:** Bull entry = MA + 1.5×ATR, Bear entry = MA - 2.0×ATR (asymmetric — harder to go bearish)
- **RSI filter:** Blocks entries when RSI is overbought/oversold
- **Trailing ATR stop (2.5x):** Exits to cash, not reverse (prevents whipsaw cascading)
- **Vol position sizing (50-100%):** Scales position down in high-vol environments

Config-switchable: `strategy.combiner_version: 1` or `2` in YAML.

### 3.8 Configuration

```yaml
# config/paper.yaml
strategy:
  combiner_version: 2
  position_sizing: true
alpaca:
  paper: true
  api_key: ...
  api_secret: ...
```

---

## 4. Research Dashboard

**URL:** https://whitelight.game-agents.com
**Port:** 3012
**Service:** `whitelight-web.service` (systemd)
**Backend:** FastAPI (`/home/p0r0/clawd/projects/whitelight-web/server.py`)
**Frontend:** Vanilla HTML/JS (`/home/p0r0/clawd/projects/whitelight-web/static/index.html`)

### 4.1 Tabs & Features

#### Overview
- System status, cached data info, backtest result count, strategy DB stats

#### Strategies (Leaderboard)
- All 19 strategies with backtest results, sorted by composite score
- Composite score formula: Sharpe 25% + Calmar 25% + Max DD 20% + Profit Factor 15% + Trade Frequency 15%
- Production strategy (White Light) highlighted with ⚡ icon and purple badge

#### Commentary
- Auto-generated analysis for each strategy and backtest run
- Rule-based verdicts: STRONG (≥0.7), MODERATE (≥0.4), WEAK (≥0.2), POOR (<0.2)
- Stored as JSON in `/data/commentary/`

#### Backtest
- Interactive backtest runner: configure start date, end date, initial capital
- Runs actual production backtest engine in background
- Displays results with CAGR, Max DD, Sharpe, Calmar, PF, trades, win rate
- Commentary generated automatically after each run

#### Results
- Historical backtest result files browser

#### Market Data
- Cached TQQQ/SQQQ/NDX/QQQ price data viewer

#### Jobs
- Background job tracker for running backtests

#### Master Leaderboard
- Combined ranking: White Light v1, v2, and 18 research strategies
- All compared over the same 3.5-year period (Jul 2022 – Feb 2026)
- Sortable by CAGR, Calmar, Sharpe, Max DD, Profit Factor, Win Rate
- Explanation panel: what each strategy is, what metrics mean, why WL has structural edge
- CAGR vs Max Drawdown scatter chart

#### v1 vs v2
- Head-to-head comparison of White Light v1 vs v2 vs v2 Conservative
- Across 9 periods: 1yr, 2yr, 3.5yr, COVID, Bear 2022, Bull 2023-24, 5yr, 6yr, 15yr max

#### 3.5yr Compare
- Apples-to-apples: all 18 research strategies + White Light over identical period
- Scatter chart (CAGR vs Max DD)

#### 🎲 Monte Carlo
- **Method:** Historical slice sampling — 500 random time windows from real TQQQ history (2010-2026)
- Random start dates, random durations (1-12 years)
- Every strategy tested on identical real market slices (no synthetic data)
- Duration bucket filters: 1-2yr, 2-3yr, 3-5yr, 5-8yr, 8-12yr, Overall
- Leaderboard table: rank, composite score, median CAGR, P5-P95 range, drawdown, Sharpe, P(profit), P(>20%)
- CAGR distribution bar chart with P5/P95 scatter overlay
- Risk vs Return scatter plot
- **White Light is #1 in every bucket** with 32.9% median CAGR overall

#### 💰 Investment Calculator
- **Interactive DCA simulator** using White Light production engine
- Configure any combination of contributions:
  - One-time lump sums (at any week)
  - Weekly, bi-weekly, monthly, quarterly, yearly recurring
  - Each with configurable start week and optional end week
- Select horizons: 1, 2, 3, 5, 7, 10 years
- Runs 500 simulations on real historical data using pre-computed production allocations
- Results table: invested, P5/P25/Median/P75/P95, probability of profit/2x/10x
- Bar chart showing invested vs outcome ranges
- Detailed "How This Works" explanation panel

#### Strategy Guide (Encyclopedia)
- Detailed explanation of all 18 research strategies + White Light
- How it works, strengths, weaknesses, when it shines
- "View Backtest →" links to actual results

#### Glossary
- Performance metrics, strategy types, technical indicators, instruments, system concepts

### 4.2 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | System status and data overview |
| `/api/data` | GET | Cached data summary |
| `/api/data/{ticker}` | GET | Price data for a ticker |
| `/api/results` | GET | List backtest result files |
| `/api/results/{filename}` | GET | Single result detail |
| `/api/backtest` | POST | Run backtest (background job) |
| `/api/jobs` | GET | List background jobs |
| `/api/jobs/{job_id}` | GET | Job status/result |
| `/api/strategies` | GET | All strategies with results |
| `/api/strategies/{id}` | GET | Single strategy detail + commentary |
| `/api/commentary` | GET | All commentary entries |
| `/api/commentary` | POST | Add commentary |
| `/api/comparison` | GET | 3.5yr apples-to-apples comparison |
| `/api/master-leaderboard` | GET | Combined leaderboard (WL + research) |
| `/api/v2comparison` | GET | v1 vs v2 comparison data |
| `/api/regimes` | GET | Multi-regime comparison results |
| `/api/analysis` | GET | Strategy improvement analysis (markdown) |
| `/api/monte-carlo` | GET | Monte Carlo v2 results (historical slices) |
| `/api/dca-simulate` | POST | DCA investment simulation |

---

## 5. Backtesting Infrastructure

### 5.1 Production Backtester
- Full engine replay: runs all 7 sub-strategies day-by-day
- Located at `scripts/backtest.py`
- Outputs JSON to `data/backtest_results/`
- Configurable: start/end date, initial capital, data source

### 5.2 Research Strategy Backtester
- VectorBT-based evaluator for simplified strategy implementations
- Located at `src/whitelight/research/evaluator.py`
- 18 research strategies implemented in Python
- Results stored in `data/strategies.db` (SQLite)

### 5.3 Strategy Database Schema

```sql
strategies (id, name, description, category, source, source_url, pine_code, python_code, status, discovered_at)
backtest_results (id, strategy_id, ticker, start_date, end_date, initial_capital, final_value, total_return, annual_return, max_drawdown, sharpe_ratio, sortino_ratio, calmar_ratio, profit_factor, win_rate, total_trades, trade_frequency, composite_score, ran_at)
```

### 5.4 19 Strategies in Database

| # | Name | Category |
|---|------|----------|
| 1 | SMA Crossover 50/200 | Trend-Following |
| 2 | SMA Crossover 20/50 | Trend-Following |
| 3 | EMA Crossover 9/21 | Trend-Following |
| 4 | Triple EMA | Trend-Following |
| 5 | Donchian Breakout 20 | Trend-Following |
| 6 | MACD Crossover | Trend-Following |
| 7 | ADX Trend | Trend-Following |
| 8 | RSI Momentum | Momentum |
| 9 | Momentum Breakout | Momentum |
| 10 | Dual Momentum | Momentum |
| 11 | Williams %R Momentum | Momentum |
| 12 | RSI Mean Reversion | Mean-Reversion |
| 13 | Bollinger Mean Reversion | Mean-Reversion |
| 14 | Mean Reversion SMA | Mean-Reversion |
| 15 | ATR Breakout | Volatility |
| 16 | Keltner Channel Breakout | Volatility |
| 17 | Trend+Momentum Combo | Composite |
| 18 | MACD+RSI Combo | Composite |
| 19 | White Light (Production) | Production |

---

## 6. Monte Carlo Analysis

### 6.1 v2 — Historical Slice Sampling (Active)
- **Script:** `scripts/monte_carlo_v2.py`
- **Method:** 500 random time windows from real TQQQ history
- **Used by:** 🎲 Monte Carlo tab
- **Tests:** All 19 strategies (simplified implementations) on identical slices
- **Output:** `data/monte_carlo/mc_v2_latest.json`

### 6.2 Production Engine Monte Carlo (Active)
- **Script:** `scripts/monte_carlo_production.py`
- **Method:** Pre-computes daily allocations for all 3,731 trading days using full production engine, then samples random windows
- **Used by:** 💰 Investment Calculator
- **Optimization:** 47-second one-time precompute, then instant simulations (13,000+ slices/sec)
- **Output:**
  - `data/monte_carlo/production_allocations.parquet` (cached daily allocations)
  - `data/monte_carlo/mc_production_latest.json` (results)

### 6.3 Key Production MC Results

| Horizon | Median CAGR | P5–P95 | Median DD | P(profit) | P(>30% CAGR) |
|---------|-------------|--------|-----------|-----------|---------------|
| 1-2yr | 54.5% | -11% to 134% | 33.4% | 88% | 74% |
| 2-3yr | 57.7% | 26% to 100% | 44.8% | 100% | 85% |
| 3-5yr | 53.1% | 30% to 79% | 45.6% | 100% | 95% |
| 5-8yr | 56.1% | 41% to 67% | 46.2% | 100% | 100% |
| 8-12yr | 52.5% | 45% to 61% | 46.2% | 100% | 100% |

### 6.4 $20K DCA Projections (Production Engine)

Schedule: $1K week 1, $3K/wk weeks 2-4, $500/wk after.

| Horizon | Invested | Median Portfolio | Median ROI |
|---------|----------|-----------------|------------|
| 3yr | $84K | $179K | 113% |
| 5yr | $134K | $507K | 279% |
| 7yr | $185K | $1.51M | 717% |
| 10yr | $260K | $5.52M | 2,021% |

---

## 7. Strategy Research Pipeline

### 7.1 Components
- **Discovery:** `src/whitelight/research/discovery.py` — scrapes TradingView for public Pine scripts
- **Converter:** `src/whitelight/research/converter.py` — Pine Script → Python conversion
- **Evaluator:** `src/whitelight/research/evaluator.py` — VectorBT backtesting
- **Database:** `src/whitelight/research/database.py` — SQLite strategy storage
- **CLI:** `scripts/research_pipeline.py` — chains discover→extract→convert→backtest→rank

### 7.2 Status
- Discovery stage partially blocked (TradingView CSS selectors need updating for ScraperAPI)
- 18 strategies manually seeded and backtested
- Regime comparison complete (5 regimes × 23 strategies)

---

## 8. Deployment & Operations

### 8.1 Trading Engine
- **Cron:** OpenClaw job `8128a126`, weekdays 20:45 UTC (3:45 PM ET)
- **Mode:** Paper trading (Alpaca paper account, $100K)
- **Config:** `config/paper.yaml` (v2 combiner, position sizing enabled)
- **Logs:** Via OpenClaw cron system

### 8.2 Research Dashboard
- **Service:** `whitelight-web.service` (systemd)
- **Port:** 3012
- **DNS:** `whitelight.game-agents.com` → Cloudflare tunnel → localhost:3012
- **Tunnel:** `07dc6a99-97ee-4f15-a098-31762d7cf92e`

### 8.3 Data Cache
- `data/cache/ndx_daily.parquet` — 6,573 rows (1999–2026)
- `data/cache/qqq_daily.parquet` — 6,573 rows
- `data/cache/tqqq_daily.parquet` — 4,031 rows (2010–2026)
- `data/cache/sqqq_daily.parquet` — 4,031 rows (2010–2026)

### 8.4 Credentials
- **Alpaca Paper:** Key `PKWHF33UCU4A2MQL2Z4HULXDDB`
- **Alpaca Live:** Key `AK55N2N3G5ROLWRUEUZQBP5TVP`
- **Polygon:** Key `p2cEdE75X3F50wdYcLnjP3MgkHk0jYbc`

---

## 9. Performance Summary

### 9.1 Production Backtest (2011–2025, $100K)

| Metric | White Light | Buy & Hold TQQQ |
|--------|-------------|-----------------|
| Final Value | $15,499,273 | $14,579,784 |
| CAGR | 40.6% | 40.1% |
| Max Drawdown | -52.1% | **-81.7%** |
| Sharpe | 0.87 | — |
| Calmar | 0.78 | — |
| Win Rate | 75.0% | — |

### 9.2 Monte Carlo (Production Engine, 500 Historical Slices)

- **Overall median CAGR:** 53.8%
- **Overall median Sharpe:** 1.08
- **5-8yr horizon:** 100% probability of profit, 100% probability of >30% returns
- **#1 ranked strategy** across every duration bucket vs 18 research strategies

### 9.3 White Light in Research MC (Simplified, 500 Slices)

- **Overall:** #1 with 32.9% median CAGR, 38.1% DD, 98% P(profit)
- Beats #2 (EMA 9/21, 25.8%) by 7.1 percentage points
- Lowest drawdown of any top-5 strategy

---

## 10. Roadmap

### Near-Term
- [ ] Go live with $20K capital (after paper validation period)
- [ ] Monitor v2 combiner behavior during next volatility spike
- [ ] Fix TradingView discovery selectors for automated strategy scraping
- [ ] Re-run all 18 strategies for 3.5yr period for exact apples-to-apples comparison
- [ ] Add Monte Carlo production results as dashboard tab alongside simplified MC
- [ ] Periodic token refresh for Gmail (prevent OAuth expiry)

### Medium-Term
- [ ] Tune v2 parameters (ATR multipliers, RSI bands, vol thresholds) based on paper results
- [ ] Implement SQQQ-capable versions of top research strategies (ATR Breakout, Vol-Regime Switch)
- [ ] Add equity curve visualization to Investment Calculator
- [ ] Real-time portfolio tracking dashboard (connected to Alpaca)
- [ ] Mobile-responsive dashboard design

### Long-Term
- [ ] Multi-instrument expansion (beyond Nasdaq-100)
- [ ] Machine learning signal overlay (transformer-based regime detection)
- [ ] Public-facing version of Investment Calculator for marketing
- [ ] IBKR failover testing and activation

---

## File Inventory

### Core Trading Engine (`/home/p0r0/clawd/projects/whitelight/`)
```
src/whitelight/
  main.py                          # Pipeline orchestrator
  config.py                        # Pydantic settings (YAML + env)
  models.py                        # Domain models
  constants.py                     # Tickers, windows, constants
  data/                            # Polygon client, cache, sync, calendar
  strategy/
    engine.py                      # Runs all 7 sub-strategies
    combiner.py                    # v1 vol-targeted combiner
    combiner_v2.py                 # v2 experimental combiner
    indicators.py                  # SMA, EMA, ATR, RSI, Bollinger
    base.py                        # SubStrategy ABC
    substrats/s1-s7                # 7 sub-strategy implementations
  execution/                       # Executor, reconciler, retry
  providers/                       # Alpaca, IBKR, alerts, secrets
  backtest/                        # Runner, metrics
  research/                        # Discovery, converter, evaluator, DB
config/
  paper.yaml                       # Paper trading config
  default.yaml                     # Base config
scripts/
  backtest.py                      # CLI backtester
  monte_carlo_v2.py                # Historical slice MC (all strategies)
  monte_carlo_production.py        # Production engine MC
  research_pipeline.py             # Discovery→backtest pipeline
  regime_comparison.py             # Multi-regime analysis
  whitelight_v2_backtest.py        # v1 vs v2 comparison
data/
  cache/                           # NDX/TQQQ/SQQQ/QQQ parquet files
  strategies.db                    # SQLite strategy database
  backtest_results/                # JSON result files
  monte_carlo/                     # MC results + cached allocations
  research/                        # Regime comparison, analysis
```

### Research Dashboard (`/home/p0r0/clawd/projects/whitelight-web/`)
```
server.py                          # FastAPI backend (all API endpoints)
static/index.html                  # Single-page frontend (11 tabs)
data/commentary/                   # Auto-generated commentary JSON
```
