# Product Requirements Document (PRD): "White Light" Automated Trading System

**Version:** 1.5
**Date:** February 22, 2026
**Author:** Mark Ollila
**Status:** Draft
**Classification:** Confidential
**Collective2 Strategy:** [Whitelight (K6Q9FDJ8A)](https://collective2.com/my/K6Q9FDJ8A)

---

## 1. Product Overview

The "White Light" system is a fully automated, systematic trading engine designed to execute a hands-free position-trading strategy. Built for professionals with full-time jobs, the system removes emotional and discretionary decision-making by programmatically evaluating market regimes and executing trades without human intervention.

The strategy trades the NASDAQ 100 via triple-leveraged ETFs and a T-bill bond ETF for idle cash. The system operates on a low-frequency basis, typically executing 1 to 2 trades per week, with core positions potentially held for months or years depending on the prevailing trend.

### 1.1 Verified Performance (Collective2)

The strategy has been tracked on Collective2 (an independent third-party platform) since July 23, 2022. All results below are hypothetical performance as reported by Collective2. Past results are not necessarily indicative of future results.

| Metric | Value | Source |
|--------|-------|--------|
| Annual Return (Compounded) | +26.5% | Collective2 |
| Max Peak-to-Valley Drawdown | -37.58% | Collective2 |
| Drawdown Period | July 10, 2024 — March 26, 2025 | Collective2 |
| Total Trades | 81 | Collective2 |
| Win Rate | 40.7% (33 wins / 48 losses) | Collective2 |
| Avg Trade Duration | 14.2 days | Collective2 |
| Alpha | 0.0415 | Collective2 |
| Beta | 0.7998 | Collective2 |
| Follower Live Capital | $1.2 million | Collective2 |
| Min Capital Suggested | $15,000 | Collective2 |
| Classification | Momentum | Collective2 |
| Strategy Age | 1,309 days (as of 2/21/2026) | Collective2 |
| Subscriber Price | $50/month | Collective2 |

### 1.2 Monthly Returns (Hypothetical)

| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | **YTD** |
|------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|---------|
| 2022 | — | — | — | — | — | — | +7.5% | +5.5% | -16.2% | -1.0% | +13.2% | -16.4% | **-10.9%** |
| 2023 | +12.8% | -5.1% | +7.3% | -0.9% | +23.8% | +12.1% | +10.1% | -1.8% | -6.1% | -2.9% | +9.7% | +3.6% | **+77.1%** |
| 2024 | +7.3% | +4.5% | -0.6% | -8.6% | +19.2% | +1.7% | -3.3% | +1.0% | -4.0% | -0.7% | -9.1% | +5.2% | **+9.8%** |
| 2025 | +2.8% | -3.5% | -21.2% | +2.6% | +17.7% | +21.2% | +5.4% | +4.0% | +11.5% | -0.7% | +1.4% | -1.8% | **+38.3%** |
| 2026 | -4.9% | +2.1% | | | | | | | | | | | **-2.9%** |

**Key observations:** The 40.7% win rate combined with positive compounded returns indicates that winning trades are significantly larger than losing trades — a hallmark of trend-following strategies that cut losses short and let winners run. The best year (2023: +77.1%) demonstrates the system's ability to capture strong bull trends, while the worst drawdown (-37.58%) shows the risk during prolonged choppy or bearish markets.

---

## 2. Scope & Target Assets

### 2.1 Traded Instruments

The system trades three instruments:

- **TQQQ** (ProShares UltraPro QQQ) — 3x Long NASDAQ 100 exposure for bullish positions.
- **SQQQ** (ProShares UltraPro Short QQQ) — 3x Short NASDAQ 100 exposure, used only during crash sprints (first 15 days of a bear regime).
- **BIL** (SPDR Bloomberg 1-3 Month T-Bill ETF) — Safe haven for idle capital, earning ~5% risk-free yield instead of leaving cash uninvested in the brokerage account.

The system does not trade individual stocks, options, futures, or any other asset class.

### 2.2 Benchmark / Reference Index

All trend calculations, moving average computations, and regime detection use the **NDX (NASDAQ 100 Index)** as the primary reference. Historical NDX data dating back to 1985 serves as the foundation for backtesting and live signal generation.

### 2.3 Trading Frequency

The system operates as a low-frequency position-trading engine. It averages 1 to 2 trades per week (81 trades over 1,309 days = ~1 trade every 16 days). Core positions may be held for extended periods (months to years) during strong, sustained trends. Average trade duration is 14.2 days.

---

## 3. System Architecture & Infrastructure

| Component | Specification |
|-----------|--------------|
| Hosting | AWS EC2 instance (t3.small or t3.medium), us-east-1 region — OR — Local Linux/macOS server |
| Scheduling | AWS EventBridge + Lambda trigger — OR — cron job (local) |
| Data Provider | Massive API (primary, Polygon-compatible) / Polygon.io (fallback) / Yahoo Finance via yfinance (backtesting, free) |
| Brokerage | Alpaca (REST API — commission-free, purpose-built for algo trading) |
| Secrets Management | AWS Secrets Manager — OR — `pass` (GPG-encrypted, local) — OR — environment variables |
| Monitoring | AWS CloudWatch — OR — systemd + logrotate (local) |
| Alerts | Telegram Bot / Pushover / AWS SNS / Ntfy.sh |
| Networking | VPC with private subnet (AWS) — OR — UFW firewall (local) |

The system is designed around a serverless-adjacent model: the cloud VM is only running during the critical trading window (approximately 15-20 minutes per day), minimizing infrastructure costs while ensuring the system is active when it matters. Alternatively, the system can run on a local server with near-zero infrastructure cost.

### 3.1 Why Alpaca

Alpaca serves as the sole execution venue. It offers a modern REST API purpose-built for algorithmic trading, commission-free US equity/ETF trades, and excellent developer documentation. Alpaca is ideal for rapid development and low-friction automation. Key advantages:

- **Paper trading:** Free paper trading environment for testing the full pipeline without risking real capital.
- **REST API + Python SDK:** The `alpaca-py` library provides typed access to account info, positions, and order submission.
- **No minimum account size:** Suitable for accounts of any size.
- **Commission-free:** No per-trade costs for US equities and ETFs.

### 3.2 Option A: AWS Cloud Deployment

**Region:** us-east-1 (N. Virginia) — lowest latency to US equity exchanges and data provider servers.

**Instance type:** t3.small (2 vCPUs, 2 GiB RAM) is sufficient for the strategy engine's computational needs. The workload is light: downloading a few hundred KB of price data, computing moving averages, and placing a handful of API calls.

**Scheduling:** An AWS EventBridge rule triggers a Lambda function at 3:40 PM ET each trading day. The Lambda function starts the EC2 instance, which runs a boot script that executes the full trading pipeline (data sync → strategy engine → order execution → telemetry). After completion, the instance self-terminates.

**Storage:** A persistent EBS volume (gp3, 10-20 GB) stores the historical price cache, application code, and logs. This volume persists across instance start/stop cycles.

**Networking:** The EC2 instance runs inside a VPC with a private subnet. A NAT Gateway provides outbound internet access for API calls. Security Groups restrict all inbound traffic except SSH from a whitelisted IP (for emergency access).

### 3.3 Option B: Local Server Deployment

The system can alternatively be deployed on a personal server (Linux or macOS) running on your home or office network. This eliminates nearly all AWS infrastructure costs while maintaining the same trading logic and brokerage integration.

**Minimum hardware requirements:** The computational workload is extremely light. Any machine with 1+ CPU cores, 1 GB RAM, and a few GB of disk space is more than sufficient. A Raspberry Pi 4, an old laptop, or a low-end Intel NUC would all work.

**Scheduling:** Replace AWS EventBridge with a standard cron job. The cron entry fires at 3:40 PM ET each trading day and launches the trading pipeline script. Example: `40 15 * * 1-5 /opt/whitelight/run.sh` (adjust for your timezone). A helper script should check a market holiday calendar and skip execution on non-trading days.

**Secrets management (local):** Replace AWS Secrets Manager with one of the following options:

| Option | Complexity | Security Level | Notes |
|--------|-----------|---------------|-------|
| Environment variables (`.env`) | Low | Moderate | Simplest; loaded at runtime via Pydantic Settings |
| `pass` (GPG-encrypted store) | Low | High | Standard Linux password manager; GPG-encrypted at rest; CLI-friendly |
| HashiCorp Vault (dev mode) | Medium | Very High | Full-featured secrets engine; overkill for a single-user system but future-proof |
| GPG-encrypted `.env` file | Low | Moderate | Simple approach; script decrypts at runtime, loads into memory, shreds plaintext |

**Recommended approach for development:** Use environment variables via a `.env` file (loaded by the config system). For production, use `pass` (the standard Unix password manager). The trading script calls `pass show whitelight/alpaca-key` at runtime to retrieve credentials, which are loaded into memory and never written to disk in plaintext.

**Alerts (local):** Replace AWS SNS with a free self-hosted alternative:

- **Telegram Bot API ($0):** Create a private Telegram bot; the trading script sends HTTP POST requests to the Telegram API to push alerts to your phone. No server infrastructure required.
- **Pushover ($5 one-time):** A mobile app with a simple REST API for push notifications. One-time purchase, no subscription.
- **Ntfy.sh ($0):** Open-source push notification service; self-hosted or use the free public server.

**Logging (local):** Use `systemd journal` or rotate logs to `/var/log/whitelight/`. Implement log rotation via `logrotate` to prevent disk fill. For long-term retention, optionally sync compressed logs to a cloud backup (S3, Backblaze B2) weekly.

**Auto-recovery (local):** Configure the trading script as a `systemd` service with `Restart=on-failure` and `RestartSec=5`. A watchdog timer ensures the service is alive during the critical trading window. If the process crashes, systemd automatically restarts it within seconds.

**Network security (local):**

- **Firewall:** Configure UFW or iptables to deny all inbound traffic except SSH from trusted IPs. The trading bot only makes outbound HTTPS connections.
- **Router-level:** Disable UPnP, use a strong WPA3 Wi-Fi password, and consider placing the server on a separate VLAN or DMZ if your router supports it.
- **SSH hardening:** Key-only authentication, Fail2Ban, disable root login — same as the AWS approach.

**Reliability tradeoffs vs. AWS:**

| Factor | AWS EC2 | Local Server |
|--------|---------|--------------|
| Uptime guarantee | 99.99% SLA | Depends on your power + internet |
| Power outage protection | Built-in | Requires UPS ($50-150 one-time) |
| Internet redundancy | Multiple backbone providers | Single ISP; consider cellular failover ($10-20/mo) |
| Maintenance | AWS-managed hardware | You handle OS updates, disk health, hardware failures |
| Latency to exchanges | ~1-2ms from us-east-1 | ~10-50ms from residential ISP (irrelevant for EOD trading) |
| Monthly infrastructure cost | ~$10-15/mo | ~$0 (electricity only) |
| Security posture | VPC isolation, managed services | Your home network; depends on configuration |

**Recommendation:** For a system that only trades once per day at end-of-day, local deployment is highly practical. The latency difference is irrelevant for EOD order execution, and a $75 UPS battery backup eliminates the biggest risk (power outage). The primary advantage of AWS is guaranteed uptime and zero-maintenance infrastructure. The primary advantage of local is near-zero cost and full physical control over your hardware.

### 3.4 Deployment Comparison Summary

| | AWS Cloud | Local Server |
|---|-----------|-------------|
| Monthly infra cost | ~$37-117/mo | ~$29-79/mo (data API only) |
| Annual infra cost | ~$444-1,404/yr | ~$348-948/yr |
| Setup complexity | Medium (IAM, VPC, EventBridge) | Low (cron, systemd, env vars) |
| Ongoing maintenance | Low (AWS-managed) | Medium (OS updates, hardware) |
| Secrets management | AWS Secrets Manager | `pass` (GPG), env vars |
| Scheduling | EventBridge + Lambda | cron |
| Alerts | AWS SNS | Telegram Bot / Pushover / Ntfy |
| Auto-recovery | CloudWatch + auto-restart | systemd watchdog |
| Best for | Maximum reliability, hands-off | Cost savings, full control |

---

## 4. Core Functional Requirements

### Module A: Data Ingestion & Caching

**Historical Base**

The system must maintain a local cache of daily price data (Open, High, Low, Close, Volume) for NDX, TQQQ, SQQQ, and BIL dating back to 1985 (or instrument inception). This historical dataset is the foundation for all moving average, volatility, and velocity calculations.

**Daily Sync**

- Upon boot (VM or local server), the system connects to the Massive API (Polygon-compatible REST endpoint at `api.massive.com`) and downloads the current day's price data for all tracked tickers.
- New data is appended to the local Parquet cache.
- The local cache serves as both the computational dataset and a fault-tolerance fallback if the API becomes unavailable.
- Index tickers use the `I:` prefix on the wire (e.g., `I:NDX`), matching the Polygon convention.

**Cache Format**

All historical data is stored as Parquet files (one per ticker) in the `data/` directory. Parquet provides 10-100x faster reads than CSV for columnar time-series data and is the only supported cache format.

### Module B: Strategy Engine

The strategy engine is the core intelligence of the system. It runs 7 concurrent sub-strategies organized around two primary market tendencies, then feeds the results into a volatility-targeted allocation combiner.

**Trend Following Logic**

- Compute the 50-day simple moving average (SMA) of the NDX.
- Compute the 250-day simple moving average (SMA) of the NDX.
- When the NDX price is trading above both moving averages, the system enters or holds a heavily long position (TQQQ), capturing sustained bull-market trends.
- When the NDX crosses below key moving averages, the system reduces or eliminates long exposure.

**Mean Reversion (Velocity) Logic**

- Measure the "rate of change" (velocity) of the trend — i.e., whether momentum is accelerating or decelerating.
- Example: If momentum readings progress from 40 to 50 to 60, the trend is accelerating (bullish).
- Example: If momentum readings progress from 40 to 30 to 20, the trend is decelerating (bearish).
- If deceleration is detected, the system triggers logic to trim long positions, take profits, or rotate into defensive positions.

#### B.1 Sub-Strategy Specifications

The 7 sub-strategies are split into two groups: trend-following (60% total weight) and mean-reversion (40% total weight). Each strategy produces a continuous `raw_score` in [-1.0, +1.0] and a discrete signal strength. All strategies are stateless: signals are derived entirely from the NDX price history passed in.

| # | Strategy | Type | Weight | Key Indicators | Description |
|---|----------|------|--------|----------------|-------------|
| S1 | Primary Trend | Trend | 0.25 | NDX vs 50/250 SMA | Longest-term regime detector. Uses hysteresis (0.5% threshold, 2-day confirmation) to prevent whipsaw at crossovers. Above both = +1.0 (STRONG_BULL), below both = -0.5 (STRONG_BEAR). |
| S2 | Intermediate Trend | Trend | 0.15 | 20/100 SMA crossover | Captures intermediate swings. Checks price vs 20 SMA and 20 SMA vs 100 SMA alignment. Four states: +1.0 / +0.3 / 0.0 / -0.5. |
| S3 | Short-Term Trend | Trend | 0.10 | 10/30 SMA | Most responsive trend signal. Checks SMA crossover direction and price position relative to 10 SMA. Four states: +1.0 / +0.5 / 0.0 / -0.3. |
| S4 | Trend Strength | Trend | 0.10 | 60-day regression slope, z-scored vs 252-day history | Measures trend quality rather than direction. Cross-references with 200 SMA filter. Five states from +1.0 to -0.5. |
| S5 | Momentum Velocity | Mean Rev | 0.15 | 14-day ROC smoothed with 3-day SMA + first derivative | Directly implements the PRD "acceleration/deceleration" logic. Accelerating bull = +1.0, decelerating bear = -0.7. 5-day ROC < -5% triggers -0.2 crash penalty. |
| S6 | Bollinger Mean Reversion | Mean Rev | 0.15 | 20-day Bollinger %B + 200 SMA filter | Buys dips in uptrends (%B < 0.2 bullish = +1.0), fades rallies in downtrends (%B > 0.95 bearish = -0.3). Extreme crashes (%B < 0.05) trigger tactical bounce regardless of trend. |
| S7 | Volatility Regime | Mean Rev | 0.10 | 20-day vs 60-day realized volatility ratio + 100 SMA | Reduces exposure when vol spikes (protects against 3x leverage decay). vol_ratio > 2.0 = -0.3 override. Calm bull (vol_ratio < 0.8, bullish) = +1.0. |

**Shared Indicators Library:**
- `sma(series, period)` — Simple Moving Average
- `roc(series, period)` — Rate of Change (percentage)
- `rsi(series, period)` — Relative Strength Index (0-100)
- `bollinger_bands(series, period, std_mult)` — Returns (upper, lower, %B)
- `realized_volatility(series, period)` — Annualized std of log returns
- `linear_regression_slope(series, period)` — Rolling OLS slope
- `zscore(series, period)` — Rolling z-score normalization

#### B.2 Signal Combiner: Volatility-Targeted Allocation

The combiner translates sub-strategy signals into a target allocation using **volatility targeting** as the primary allocation mechanism. The 7 sub-strategy signals feed a composite score for reporting and diagnostics, but the actual portfolio allocation is driven by realized volatility.

**Primary Rule: Volatility Targeting**

```
TQQQ weight = min(target_vol / realized_vol_20d, 1.0)
```

- **`target_vol`** = 20% annualized (hardcoded constant).
- **`realized_vol_20d`** = 20-day realized volatility of NDX, annualized (computed as rolling 20-day standard deviation of daily returns × sqrt(252)).
- When volatility is low (e.g., 12%), the strategy allocates up to 100% TQQQ — this is when 3x leverage compounds best.
- When volatility spikes (e.g., 30%), the strategy reduces TQQQ to ~67%, parking the remainder in BIL.
- When volatility is extreme (e.g., 50%), TQQQ drops to ~40%, with 60% in BIL for capital preservation.

The remainder of the portfolio (1.0 - TQQQ%) is allocated to **BIL** (T-bill bond ETF), earning ~5% risk-free yield rather than sitting as uninvested cash in the brokerage account.

**SQQQ Crash Sprint**

During the **first 15 trading days** after NDX crosses below the 200-day SMA *and* realized volatility exceeds 25%, the combiner allocates **30% to SQQQ** and 0% to TQQQ. This captures the initial leg of a crash where SQQQ outperforms cash. After 15 days, SQQQ decays too fast (due to daily rebalancing of the 3x inverse leverage) and the strategy rotates the full portfolio to BIL instead.

Sprint activation criteria (all must be true):
1. NDX closing price is below its 200-day SMA.
2. 20-day realized volatility >= 25% annualized.
3. Consecutive days below the 200-day SMA <= 15.

When the sprint is active: 30% SQQQ, 0% TQQQ, 70% BIL.

**Override: No Direct Flip**

The system never goes directly from TQQQ to SQQQ or vice versa. If the previous allocation had TQQQ > 0 and the new allocation would have SQQQ > 0 (or reverse), the combiner forces 100% BIL for one day. Rationale: prevents overtrading during regime transitions and gives the market a day to confirm the new direction.

**Composite Score (Diagnostic)**

A composite score is still computed as `sum(weight_i * raw_score_i)` across all 7 strategies. This score is logged, reported in telemetry alerts, and used for performance analysis, but it does **not** directly drive the allocation. The volatility-targeting rule is the sole allocation mechanism.

**Target Output**

At the conclusion of all sub-strategy calculations, the engine outputs an exact target portfolio allocation for the upcoming overnight hold. For example:

| Instrument | Target Allocation |
|------------|------------------|
| TQQQ | 67% |
| SQQQ | 0% |
| BIL | 33% |

### Module C: Order Execution

- The system reads the current share count and cash balance from the Alpaca brokerage account via REST API.
- It calculates the exact number of shares to buy or sell for each of the three instruments (TQQQ, SQQQ, BIL) to match the engine's target percentage allocation.
- All buy/sell orders are executed exclusively during the final 15 minutes of the trading day (configurable: `window_start_minutes_before_close` and `window_end_minutes_before_close`).
- Orders are placed as market orders to ensure execution before the closing bell.
- **Sells are executed before buys** to free up buying power for subsequent purchases.
- Orders below a configurable minimum value (default: $10) are skipped to avoid unnecessary micro-trades.
- The executor waits for fill confirmation on sell orders before proceeding to buy orders.

### Module D: Telemetry & Alerting

The system pushes real-time telemetry and alerts to the user's mobile phone via a pluggable alert provider (Telegram, Pushover, AWS SNS, or Ntfy.sh). Alert categories include:

- **Pipeline start/complete:** Notification when the daily pipeline begins and ends.
- **Target allocation:** Current strategy position targets (e.g., "Target: 67% TQQQ, 33% BIL (composite: 0.542)").
- **Order placement:** Order details (e.g., "Order placed: BUY 150 shares TQQQ via alpaca (id=abc123)").
- **Execution results:** Summary of all fills, partial fills, and failures.
- **Error alerts:** High-priority failure alerts if an execution error occurs, requiring potential manual intervention.

---

## 5. Non-Functional Requirements & Fault Tolerance

### 5.1 Brokerage Retry Loops

If Alpaca rejects an order (e.g., due to extreme market volatility, insufficient buying power, or transient API errors), the system retries with exponential backoff (base: 2 seconds, max: 60 seconds) for up to 5 attempts, or until the final minute before market close. Each attempt is logged with full details.

### 5.2 Data Source Fallbacks

- **Primary source:** Massive API (`api.massive.com`) — Polygon-compatible REST API providing real-time and end-of-day OHLCV data. Uses the same `v2/aggs/ticker` endpoint format as Polygon.io. Requires an API key.
- **Fallback:** Polygon.io API — Full Polygon REST API via the `polygon-api-client` library. Requires a paid plan ($29+/mo) for index data (NDX) and full history.
- **Development source:** Yahoo Finance via `yfinance` library (free, no API key required). Provides daily OHLCV for NDX (`^NDX`), TQQQ, SQQQ, and BIL. Suitable for backtesting and development but not recommended for production trading due to rate limits and occasional data gaps.
- **Offline fallback:** Local Parquet cache (allows the system to operate using cached data if all APIs are unavailable).

### 5.3 Auto-Recovery

If the virtual machine (or local server process) crashes during the critical execution window, the system must have the capability to immediately restart and resume the execution process before the market closes. On AWS, this requires CloudWatch health-check monitoring and automated restart mechanisms. On a local server, this is handled by systemd with `Restart=on-failure`.

### 5.4 Logging & Audit Trail

Every action taken by the system — from data download to order placement to retry attempts — must be logged with timestamps for post-session auditing and debugging. The system uses structured JSON logging via `structlog`, with logs written to the configured log directory (default: `/var/log/whitelight/`).

---

## 6. Brokerage Compatibility

| Brokerage | API Type | Commission | Integration Status | Notes |
|-----------|----------|------------|-------------------|-------|
| Alpaca | REST API | $0 (retail) | Implemented — Primary | Purpose-built for algo trading; paper + live |
| Interactive Brokers | TWS API (Python) | $0 (Lite) / $0.005/share (Pro) | Phase 2 — Planned | Institutional-grade; requires IB Gateway |
| E-Trade | REST API (OAuth) | $0 | Phase 2 — Evaluate | Morgan Stanley subsidiary |
| Fidelity | None (unofficial only) | $0 | Not planned | No public retail API; high risk |
| Robinhood | None (unofficial only) | $0 | Not recommended | No official API; TOS risk |

### 6.1 Alpaca Integration Details

Alpaca provides a straightforward REST API with excellent Python SDK support via the `alpaca-py` library. Key integration points include:

- **Account info:** Retrieve equity, cash, and buying power.
- **Positions:** Query current open positions with quantities and market values.
- **Order submission:** Submit market orders for TQQQ, SQQQ, and BIL.
- **Order status:** Poll order status until filled, cancelled, or rejected.
- **Market hours:** Check if the market is currently open.
- **Paper trading:** Available for free at `https://paper-api.alpaca.markets`, making it ideal for testing the full pipeline before going live.

Authentication uses an API key/secret pair, configured via environment variables (`WL_ALPACA_API_KEY`, `WL_ALPACA_API_SECRET`) or a secrets provider.

---

## 7. Security & Secrets Management

This section defines how the system protects sensitive credentials, secures infrastructure, and prevents unauthorized access.

### 7.1 Secrets Storage

All sensitive credentials must be stored in a secrets management system. **No API keys, tokens, or passwords may be hardcoded in source code or committed to version control.**

| Secret | AWS Deployment | Local Deployment | Rotation Schedule |
|--------|---------------|-----------------|------------------|
| Alpaca API Key + Secret | AWS Secrets Manager | `pass` (GPG) or env vars | Every 90 days |
| Massive / Polygon API Key | AWS Secrets Manager | `pass` (GPG) or env vars | Every 90 days |
| Alert service token | IAM Role (SNS) | `pass` or env vars (Telegram/Pushover token) | Every 90 days |

The system supports three secrets providers, selectable via configuration:

1. **`env`** — Reads secrets from environment variables (e.g., `WL_ALPACA_API_KEY`). Simplest option for development and single-server deployments.
2. **`pass`** — Retrieves secrets from GNU `pass` (GPG-encrypted password store). Recommended for production local deployments.
3. **`aws_secrets_manager`** — Fetches secrets from AWS Secrets Manager with caching. Recommended for AWS deployments.

**AWS deployment:** $0.40/secret/month via Secrets Manager. Store related credentials as a single JSON object to minimize cost. The EC2 instance authenticates via an IAM Instance Profile (no static AWS keys on the machine). Credentials are held in memory only for the duration of the trading session and are never written to disk.

**Local deployment:** For development, environment variables via a `.env` file are sufficient. For production, use `pass` (the standard Unix password manager). Each secret is stored as a GPG-encrypted file in `~/.password-store/whitelight/`. The trading script retrieves credentials at runtime via `pass show whitelight/alpaca-key`, loads them into memory, and never writes plaintext to disk.

### 7.2 IAM & Access Control (AWS)

- **EC2 Instance Profile:** The EC2 instance uses an IAM Role (not static access keys) to authenticate with AWS services. This role grants access to Secrets Manager, CloudWatch Logs, and SNS — nothing else.
- **Principle of least privilege:** Each IAM policy grants only the minimum permissions required. The instance cannot create/delete other AWS resources, access S3 buckets, or modify IAM policies.
- **No root account usage:** All operations use dedicated IAM users/roles. The AWS root account has MFA enabled and is used only for billing.

### 7.3 Network Security

- **AWS — VPC isolation:** The EC2 instance runs in a private subnet within a dedicated VPC. It has no public IP address. A NAT Gateway provides outbound internet access. Security Groups restrict all inbound traffic except SSH from a single whitelisted IP.
- **Local — Firewall:** UFW or iptables configured to deny all inbound traffic except SSH from trusted IPs. The trading bot only makes outbound HTTPS connections (to Alpaca, Massive/Polygon, and alert services).

### 7.4 Instance Hardening

- **SSH key-only authentication:** Password-based SSH is disabled. Access requires a private key stored securely on your local machine (never on the server).
- **Fail2Ban:** Installed and configured to ban IPs after 3 failed SSH attempts.
- **Automatic security updates:** Unattended upgrades enabled for critical security patches.
- **No withdrawal permissions:** Alpaca API keys are configured with trade and read permissions only. Withdrawal/transfer capabilities are never enabled on API keys.

### 7.5 Brokerage-Level Security

- **Alpaca:** API keys are scoped to trading and account-read permissions only. IP whitelisting is enabled, restricting API access to the server's public IP.
- **Separate credentials per service:** Each external service (brokerage, data provider, alert service) gets its own dedicated credentials. Compromise of one does not affect the others.

### 7.6 Audit & Incident Response

- All API calls, order placements, and credential retrievals are logged with timestamps.
- **AWS deployment:** Logs go to CloudWatch Logs. CloudWatch Alarms trigger SNS notifications if unexpected activity is detected (e.g., more than 10 orders in a single session, API authentication failures, or instance running longer than 30 minutes).
- **Local deployment:** Logs go to `/var/log/whitelight/` with `logrotate` managing retention. The trading script itself sends alert notifications (via Telegram/Pushover) for anomalous activity.
- Logs are retained for 90 days minimum for post-incident analysis.

---

## 8. Backtesting & Validation

### 8.1 Backtesting Framework

The system includes a built-in backtesting engine that replays historical NDX/TQQQ/SQQQ/BIL data through the full strategy pipeline day-by-day. This enables validation of strategy logic against known historical performance before deploying to live trading.

**How it works:**

1. Load historical OHLCV data for NDX, TQQQ, SQQQ, and BIL (from Parquet cache, Massive, Polygon.io, or Yahoo Finance).
2. For each trading day after a 260-day warmup period (required for the 250-day SMA lookback):
   - Run the full 7-strategy engine on NDX data up to that day.
   - Get the target allocation from the volatility-targeting combiner (including SQQQ sprint and no-flip rules).
   - Simulate execution at closing prices (market orders, same as live system).
   - Track portfolio value, positions, cash, and trades.
3. Compute performance metrics and compare against Collective2 benchmark returns.

**Data sources for backtesting:**

| Source | Cost | API Key Required | NDX History | Best For |
|--------|------|-----------------|-------------|----------|
| Yahoo Finance (`yfinance`) | Free | No | ~2000-present | Development, quick validation |
| Massive API | Varies | Yes | 1985-present | Full historical backtest |
| Polygon.io | $29+/mo | Yes | 1985-present | Full historical backtest |
| Local Parquet cache | Free | No (pre-seeded) | Depends on seed | Offline development |

**Usage:**

```bash
# Quick backtest with free Yahoo Finance data (no API key needed)
python scripts/backtest.py --source yfinance

# Full backtest from C2 inception date
python scripts/backtest.py --start 2022-07-23 --source yfinance

# Backtest with Massive data (requires API key)
python scripts/backtest.py --source massive --api-key YOUR_KEY

# Compare results against Collective2 monthly returns
python scripts/backtest.py --compare-c2
```

### 8.2 Performance Metrics

The backtesting framework calculates the following metrics for comparison against Collective2 benchmarks:

| Metric | Description | C2 Benchmark |
|--------|-------------|--------------|
| Annual Return (CAGR) | Compound annual growth rate | +26.5% |
| Max Drawdown | Largest peak-to-valley decline | -37.58% |
| Sharpe Ratio | Risk-adjusted return (annualized) | — |
| Sortino Ratio | Downside risk-adjusted return | — |
| Calmar Ratio | CAGR / max drawdown | — |
| Win Rate | Winning trades / total trades | 40.7% |
| Profit Factor | Gross profits / gross losses | — |
| Avg Trade Duration | Mean days per trade | 14.2 days |
| Total Trades | Number of completed round-trip trades | 81 (over 1,309 days) |
| Monthly Returns | Month-by-month return table | See Section 1.2 |

### 8.3 Validation Targets

The backtested strategy should approximate (not exactly match) the Collective2 performance, accounting for:

- **Execution differences:** The backtest simulates market orders at closing prices, while live C2 trades may have executed at slightly different intraday prices.
- **Strategy evolution:** The discretionary strategy on C2 may have evolved over time; the automated system implements the volatility-targeting rules as of v1.5 of this PRD.
- **No-flip rule:** The automated system enforces a mandatory cash/BIL day between TQQQ and SQQQ positions, which the discretionary strategy may not have always followed.
- **BIL yield:** The backtest includes estimated BIL returns during cash periods, which the C2 track record may not account for identically.

A successful validation should show:
- Annual return within +/- 15% of C2 benchmark
- Max drawdown within +/- 10% of C2 benchmark
- Similar trade frequency (within 2x of C2's ~1 trade per 16 days)
- Monthly return correlation > 0.7 with C2 monthly returns during the overlapping period (July 2022 - present)

---

## 9. Future Enhancements (Phase 2)

### 9.1 Interactive Brokers Integration

Add IBKR as a secondary brokerage for redundancy and failover. The codebase includes a preliminary `IBKRClient` implementation using the `ib_async` library, but it has not been tested or deployed. Full implementation requires:

- IB Gateway running on the host machine (headless version of Trader Workstation).
- Dedicated IBKR account with API-only permissions.
- Failover logic: If Alpaca's API is unreachable during the execution window, automatically route orders through IBKR.
- Portfolio aggregation across both brokerages.

IBKR Lite offers commission-free US stock/ETF trades; IBKR Pro charges $0.005/share (min $1) with access to superior order routing. Paper trading uses port 7497 while live uses 7496.

### 9.2 Signal Syndication via Collective2

The strategy is already listed on Collective2 as "Whitelight" (ID: K6Q9FDJ8A) with $1.2M in follower live capital and a $50/month subscription price. Phase 2 will build a direct API integration to automate signal broadcasting from the White Light engine to Collective2, eliminating any manual signal entry.

- Direct API linking to subscriber brokerage accounts.
- SMS-based trade alerts.
- Email-based trade notifications.

### 9.3 Additional Brokerage Integrations

Extend API connectivity to E-Trade and potentially Fidelity (if/when a public API becomes available) to serve a broader user base and provide additional redundancy.

### 9.4 Enhanced Risk Controls

- **Emergency stop (circuit breaker):** Automatic halt of all trading activity if portfolio drawdown exceeds a configurable threshold. Note: the historical max drawdown is -37.58%, so a circuit breaker at -40% to -45% would allow normal operation while catching catastrophic scenarios.
- **Manual override interface:** A secure web or mobile dashboard allowing the user to pause, resume, or manually adjust the system in real-time.

---

## 10. Glossary

| Term | Definition |
|------|-----------|
| NDX | NASDAQ 100 Index — benchmark index of 100 largest non-financial NASDAQ-listed companies |
| TQQQ | ProShares UltraPro QQQ — 3x leveraged ETF tracking the NASDAQ 100 (long) |
| SQQQ | ProShares UltraPro Short QQQ — 3x inverse leveraged ETF tracking the NASDAQ 100 (short) |
| BIL | SPDR Bloomberg 1-3 Month T-Bill ETF — ultra-short-term government bond ETF used as a cash proxy (~5% yield) |
| SMA | Simple Moving Average — arithmetic mean of closing prices over a specified number of days |
| Volatility Targeting | Allocation strategy that scales position size inversely to realized volatility: `weight = target_vol / realized_vol` |
| Realized Volatility | Annualized standard deviation of daily log returns over a lookback window (typically 20 days) |
| Mean Reversion | Strategy based on the tendency of prices to return to their historical average after extreme moves |
| Velocity | Rate of change of a trend; measures whether momentum is accelerating or decelerating |
| Collective2 | Third-party platform for syndicating and mirroring trade signals across subscriber brokerage accounts |
| Alpha | Excess return relative to the benchmark (0.0415 = strategy outperforms benchmark by ~4.15% annually on a risk-adjusted basis) |
| Beta | Sensitivity to market movements (0.7998 = strategy captures ~80% of market moves, indicating some downside protection) |
| Max Drawdown | Largest peak-to-valley decline in portfolio value (-37.58% for this strategy) |
| Sharpe Ratio | Annualized risk-adjusted return: (return - risk_free_rate) / volatility |
| Sortino Ratio | Like Sharpe but only penalizes downside volatility (more relevant for asymmetric return profiles) |
| Calmar Ratio | CAGR divided by max drawdown; measures return per unit of drawdown risk |
| Profit Factor | Gross profits divided by gross losses; values > 1.0 indicate a profitable system |
| CAGR | Compound Annual Growth Rate — smoothed annualized return over a multi-year period |
| Hysteresis | A threshold band that prevents signal oscillation near a crossover point; requires price to exceed the band for multiple days before confirming a regime change |
| Bollinger %B | Normalized position within Bollinger Bands: (price - lower) / (upper - lower); values near 0 = oversold, near 1 = overbought |
| ROC | Rate of Change — percentage change over N periods; used to measure momentum velocity |
| Parquet | Columnar file format optimized for analytical queries; 10-100x faster than CSV for time-series data |
| Massive API | Polygon-compatible REST API at `api.massive.com` used as the primary market data source |

---

## Appendix A: Collective2 Disclaimers

All results shown in Section 1.1 and 1.2 are hypothetical performance results as reported by Collective2, LLC (a member of the National Futures Association). These results have certain inherent limitations: they do not represent actual trading, may have under- or over-compensated for the impact of certain market factors such as lack of liquidity, and are subject to the benefit of hindsight. No representation is being made that any account will or is likely to achieve profits or losses similar to those shown. Trading is risky and you can lose money. Past results are not necessarily indicative of future results.

Source: [collective2.com/my/K6Q9FDJ8A](https://collective2.com/my/K6Q9FDJ8A), captured February 21, 2026.
