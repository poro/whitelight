# Product Requirements Document (PRD): "White Light" Automated Trading System

**Version:** 1.3
**Date:** February 21, 2026
**Author:** Mark Ollila
**Status:** Draft
**Classification:** Confidential
**Collective2 Strategy:** [Whitelight (K6Q9FDJ8A)](https://collective2.com/my/K6Q9FDJ8A)

---

## 1. Product Overview

The "White Light" system is a fully automated, systematic trading engine designed to execute a hands-free position-trading strategy. Built for professionals with full-time jobs, the system removes emotional and discretionary decision-making by programmatically evaluating market regimes and executing trades without human intervention.

The strategy strictly trades the NASDAQ 100 via triple-leveraged ETFs. The system operates on a low-frequency basis, typically executing 1 to 2 trades per week, with core positions potentially held for months or years depending on the prevailing trend.

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

The system exclusively trades two instruments:

- **TQQQ** (ProShares UltraPro QQQ) — 3x Long NASDAQ 100 exposure for bullish positions.
- **SQQQ** (ProShares UltraPro Short QQQ) — 3x Short NASDAQ 100 exposure for bearish or defensive positions.

The system does not trade individual stocks, options, futures, or any other asset class.

### 2.2 Benchmark / Reference Index

All trend calculations, moving average computations, and regime detection use the **NDX (NASDAQ 100 Index)** as the primary reference. Historical NDX data dating back to 1985 serves as the foundation for backtesting and live signal generation.

### 2.3 Trading Frequency

The system operates as a low-frequency position-trading engine. It averages 1 to 2 trades per week (81 trades over 1,309 days = ~1 trade every 16 days). Core positions may be held for extended periods (months to years) during strong, sustained trends. Average trade duration is 14.2 days.

---

## 3. System Architecture & Infrastructure

| Component | Specification |
|-----------|--------------|
| Hosting | AWS EC2 instance (t3.small or t3.medium), us-east-1 region — OR — Local Linux server |
| Scheduling | AWS EventBridge + Lambda trigger — OR — cron job (local) |
| Data Provider | Polygon.io API — end-of-day and real-time market pricing |
| Primary Brokerage | Alpaca (REST API — commission-free, purpose-built for algo trading) |
| Secondary Brokerage | Interactive Brokers (TWS API — institutional-grade, global reach) |
| Secrets Management | AWS Secrets Manager — OR — `pass` (GPG-encrypted, local) |
| Monitoring | AWS CloudWatch — OR — systemd + logrotate (local) |
| Alerts | AWS SNS — OR — Telegram Bot / Pushover (local) |
| Networking | VPC with private subnet (AWS) — OR — UFW firewall (local) |

The system is designed around a serverless-adjacent model: the cloud VM is only running during the critical trading window (approximately 15-20 minutes per day), minimizing infrastructure costs while ensuring the system is active when it matters. Alternatively, the system can run on a local Linux server with near-zero infrastructure cost.

### 3.1 Why Alpaca + Interactive Brokers

The system uses a dual-brokerage architecture for redundancy and flexibility:

- **Alpaca** serves as the primary execution venue. It offers a modern REST API purpose-built for algorithmic trading, commission-free US equity/ETF trades, and excellent developer documentation. Alpaca is ideal for rapid development and low-friction automation.
- **Interactive Brokers (IBKR)** serves as the secondary execution venue and capital custodian. IBKR is one of the most well-capitalized brokerages in the world, offers the battle-tested TWS API (Python, Java, C++), and provides SIPC protection. IBKR Lite offers commission-free US stock/ETF trades; IBKR Pro charges $0.005/share (min $1) with access to superior order routing.
- **Failover logic:** If Alpaca's API is unreachable or rejects orders during the execution window, the system automatically falls back to IBKR for order routing. This ensures trades are placed even if one brokerage experiences downtime.

### 3.2 Option A: AWS Cloud Deployment

**Region:** us-east-1 (N. Virginia) — lowest latency to US equity exchanges and Polygon.io data centers.

**Instance type:** t3.small (2 vCPUs, 2 GiB RAM) is sufficient for the strategy engine's computational needs. The workload is light: downloading a few hundred KB of price data, computing moving averages, and placing a handful of API calls.

**Scheduling:** An AWS EventBridge rule triggers a Lambda function at 3:40 PM ET each trading day. The Lambda function starts the EC2 instance, which runs a boot script that executes the full trading pipeline (data sync → strategy engine → order execution → telemetry). After completion, the instance self-terminates.

**Storage:** A persistent EBS volume (gp3, 10-20 GB) stores the historical price cache, application code, and logs. This volume persists across instance start/stop cycles.

**Networking:** The EC2 instance runs inside a VPC with a private subnet. A NAT Gateway provides outbound internet access for API calls. Security Groups restrict all inbound traffic except SSH from a whitelisted IP (for emergency access).

### 3.3 Option B: Local Linux Server Deployment

The system can alternatively be deployed on a personal Linux server (physical or virtual) running on your home or office network. This eliminates nearly all AWS infrastructure costs while maintaining the same trading logic and brokerage integrations.

**Minimum hardware requirements:** The computational workload is extremely light. Any machine with 1+ CPU cores, 1 GB RAM, and a few GB of disk space is more than sufficient. A Raspberry Pi 4, an old laptop, or a low-end Intel NUC would all work. The server must be running a modern Linux distribution (Ubuntu 22.04+, Debian 12+, or similar).

**Scheduling:** Replace AWS EventBridge with a standard cron job. The cron entry fires at 3:40 PM ET each trading day and launches the trading pipeline script. Example: `40 15 * * 1-5 /opt/whitelight/run.sh` (adjust for your timezone). A helper script should check a market holiday calendar and skip execution on non-trading days.

**IB Gateway:** Installs directly on the Linux server. Runs as a background process or systemd service. A cron job restarts it daily before market hours to maintain session freshness.

**Secrets management (local):** Replace AWS Secrets Manager with one of the following options:

| Option | Complexity | Security Level | Notes |
|--------|-----------|---------------|-------|
| `pass` (GPG-encrypted store) | Low | High | Standard Linux password manager; GPG-encrypted at rest; CLI-friendly |
| HashiCorp Vault (dev mode) | Medium | Very High | Full-featured secrets engine; overkill for a single-user system but future-proof |
| GPG-encrypted `.env` file | Low | Moderate | Simple approach; script decrypts at runtime, loads into memory, shreds plaintext |
| Linux keyring (`secret-tool`) | Low | Moderate | Uses the system's secure keyring; good for desktop Linux setups |

**Recommended approach:** Use `pass` (the standard Unix password manager). It stores each secret as a GPG-encrypted file. The trading script calls `pass show whitelight/alpaca-key` at runtime to retrieve credentials, which are loaded into memory and never written to disk in plaintext.

**Alerts (local):** Replace AWS SNS with a free self-hosted alternative:

- **Telegram Bot API ($0):** Create a private Telegram bot; the trading script sends HTTP POST requests to the Telegram API to push alerts to your phone. No server infrastructure required.
- **Pushover ($5 one-time):** A mobile app with a simple REST API for push notifications. One-time purchase, no subscription.
- **Ntfy.sh ($0):** Open-source push notification service; self-hosted or use the free public server.
- **Email via SMTP ($0):** Send alerts through Gmail or any SMTP provider as a fallback.

**Logging (local):** Use `systemd journal` or rotate logs to `/var/log/whitelight/`. Implement log rotation via `logrotate` to prevent disk fill. For long-term retention, optionally sync compressed logs to a cloud backup (S3, Backblaze B2) weekly.

**Auto-recovery (local):** Configure the trading script as a `systemd` service with `Restart=on-failure` and `RestartSec=5`. A watchdog timer ensures the service is alive during the critical trading window. If the process crashes, systemd automatically restarts it within seconds.

**Network security (local):**

- **Firewall:** Configure UFW or iptables to deny all inbound traffic except SSH from trusted IPs. The trading bot only makes outbound HTTPS connections.
- **IB Gateway ports:** Bind to `127.0.0.1` only (localhost). Never expose to the network.
- **Router-level:** Disable UPnP, use a strong WPA3 Wi-Fi password, and consider placing the server on a separate VLAN or DMZ if your router supports it.
- **SSH hardening:** Key-only authentication, Fail2Ban, disable root login — same as the AWS approach.

**Reliability tradeoffs vs. AWS:**

| Factor | AWS EC2 | Local Linux Server |
|--------|---------|--------------------|
| Uptime guarantee | 99.99% SLA | Depends on your power + internet |
| Power outage protection | Built-in | Requires UPS ($50-150 one-time) |
| Internet redundancy | Multiple backbone providers | Single ISP; consider cellular failover ($10-20/mo) |
| Maintenance | AWS-managed hardware | You handle OS updates, disk health, hardware failures |
| Latency to exchanges | ~1-2ms from us-east-1 | ~10-50ms from residential ISP (irrelevant for EOD trading) |
| Monthly infrastructure cost | ~$10-15/mo | ~$0 (electricity only) |
| Security posture | VPC isolation, managed services | Your home network; depends on configuration |

**Recommendation:** For a system that only trades once per day at end-of-day, local deployment is highly practical. The latency difference is irrelevant for EOD order execution, and a $75 UPS battery backup eliminates the biggest risk (power outage). The primary advantage of AWS is guaranteed uptime and zero-maintenance infrastructure. The primary advantage of local is near-zero cost and full physical control over your hardware.

### 3.4 Deployment Comparison Summary

| | AWS Cloud | Local Linux Server |
|---|-----------|-------------------|
| Monthly infra cost | ~$37-117/mo | ~$29-79/mo (Polygon.io only) |
| Annual infra cost | ~$444-1,404/yr | ~$348-948/yr |
| Setup complexity | Medium (IAM, VPC, EventBridge) | Low (cron, systemd, pass) |
| Ongoing maintenance | Low (AWS-managed) | Medium (OS updates, hardware) |
| Secrets management | AWS Secrets Manager | `pass` (GPG) or Vault |
| Scheduling | EventBridge + Lambda | cron |
| Alerts | AWS SNS | Telegram Bot / Pushover / Ntfy |
| Auto-recovery | CloudWatch + auto-restart | systemd watchdog |
| Best for | Maximum reliability, hands-off | Cost savings, full control |

---

## 4. Core Functional Requirements

### Module A: Data Ingestion & Caching

**Historical Base**

The system must maintain a local cache of daily price data (Open, High, Low, Close, Volume) for NDX, TQQQ, and SQQQ dating back to 1985. This historical dataset is the foundation for all moving average and velocity calculations.

**Daily Sync**

- Upon boot (VM or local server), the system connects to the Polygon.io API and downloads the current day's real-time price data.
- New data is appended to the local historical cache.
- The local cache serves as both the computational dataset and a fault-tolerance fallback if the API becomes unavailable.

### Module B: Strategy Engine

The strategy engine is the core intelligence of the system. It runs 7 concurrent sub-strategies organized around two primary market tendencies:

**Trend Following Logic**

- Compute the 50-day simple moving average (SMA) of the NDX.
- Compute the 250-day simple moving average (SMA) of the NDX.
- When the NDX price is trading above both moving averages, the system enters or holds a heavily long position (TQQQ), capturing sustained bull-market trends.
- When the NDX crosses below key moving averages, the system reduces or eliminates long exposure.

**Mean Reversion (Velocity) Logic**

- Measure the "rate of change" (velocity) of the trend — i.e., whether momentum is accelerating or decelerating.
- Example: If momentum readings progress from 40 to 50 to 60, the trend is accelerating (bullish).
- Example: If momentum readings progress from 40 to 30 to 20, the trend is decelerating (bearish).
- If deceleration is detected, the system triggers logic to trim long positions, take profits, or rotate into SQQQ.

**Target Output**

At the conclusion of all sub-strategy calculations, the engine outputs an exact target portfolio allocation for the upcoming overnight hold. For example:

| Instrument | Target Allocation |
|------------|------------------|
| TQQQ | 30% |
| SQQQ | 0% |
| Cash | 70% |

### Module C: Order Execution

- The system reads the current share count and cash balance from all connected brokerage accounts via API.
- It calculates the exact number of shares to buy or sell in order to match the engine's target percentage allocation.
- All buy/sell orders are executed exclusively during the final 10 to 15 minutes of the trading day.
- Orders are placed as market orders to ensure execution before the closing bell.

### Module D: Telemetry & Alerting

The system must push real-time telemetry and alerts to the user's mobile phone. Alert categories include:

- Current strategy position targets (e.g., "Target: 30% TQQQ, 70% Cash").
- Order placement status (e.g., "Order placed: BUY 150 shares TQQQ @ market").
- Execution confirmations (e.g., "Order filled: 150 TQQQ @ $42.15").
- High-priority failure alerts if an execution error occurs, requiring potential manual intervention.

---

## 5. Non-Functional Requirements & Fault Tolerance

### 5.1 Brokerage Retry Loops

If a broker rejects an order (e.g., due to extreme market volatility, insufficient buying power, or transient API errors), the system must continuously retry placing the order for 5 to 10 minutes, up until the final minute before market close. Retry logic must include exponential backoff and detailed logging of each attempt.

### 5.2 Data Source Fallbacks

- **Primary source:** Polygon.io API (real-time and end-of-day data).
- **Fallback:** Local historical cache (allows the system to operate using cached data if the API is unavailable).
- **Secondary fallback:** Integration with a secondary data provider (to be determined) for seamless failover.

### 5.3 Auto-Recovery

If the virtual machine (or local server process) crashes during the critical execution window, the system must have the capability to immediately restart and resume the execution process before the market closes. On AWS, this requires CloudWatch health-check monitoring and automated restart mechanisms. On a local server, this is handled by systemd with `Restart=on-failure`.

### 5.4 Logging & Audit Trail

Every action taken by the system — from data download to order placement to retry attempts — must be logged with timestamps for post-session auditing and debugging.

---

## 6. Brokerage Compatibility

| Brokerage | API Type | Commission | Integration Status | Notes |
|-----------|----------|------------|-------------------|-------|
| Alpaca | REST API | $0 (retail) | Phase 1 — Primary | Purpose-built for algo trading |
| Interactive Brokers | TWS API (Python/Java/C++) | $0 (Lite) / $0.005/share (Pro) | Phase 1 — Secondary | Institutional-grade; requires IB Gateway |
| Fidelity | None (unofficial only) | $0 | Phase 2 — Evaluate | No public retail API; high risk |
| E-Trade | REST API (OAuth) | $0 | Phase 2 — Planned | Morgan Stanley subsidiary |
| Robinhood | None (unofficial only) | $0 | Not recommended | No official API; TOS risk |

### 6.1 Alpaca Integration Details

Alpaca provides a straightforward REST API with excellent Python SDK support. Key integration points include account info retrieval, position queries, and order submission — all via simple HTTP calls with an API key/secret pair. Paper trading is available for free, making it ideal for testing the full pipeline before going live.

### 6.2 Interactive Brokers Integration Details

IBKR's TWS API requires running IB Gateway (a headless version of Trader Workstation) on the host machine (EC2 instance or local Linux server). The gateway authenticates with IBKR's servers and exposes a local socket that the trading bot connects to. Key considerations include: IB Gateway requires a daily restart (handled via cron), paper trading uses port 7497 while live uses 7496, and the API supports all order types including market, limit, and adaptive orders.

---

## 7. Security & Secrets Management

This section defines how the system protects sensitive credentials, secures infrastructure, and prevents unauthorized access.

### 7.1 Secrets Storage

All sensitive credentials must be stored in a secrets management system. **No API keys, tokens, or passwords may be hardcoded in source code, environment variables, or configuration files.**

| Secret | AWS Deployment | Local Deployment | Rotation Schedule |
|--------|---------------|-----------------|------------------|
| Alpaca API Key + Secret | AWS Secrets Manager | `pass` (GPG-encrypted) | Every 90 days |
| IBKR account credentials | AWS Secrets Manager | `pass` (GPG-encrypted) | Every 90 days |
| Polygon.io API Key | AWS Secrets Manager | `pass` (GPG-encrypted) | Every 90 days |
| Alert service token | IAM Role (SNS) | `pass` (Telegram/Pushover token) | Every 90 days |

**AWS deployment:** $0.40/secret/month via Secrets Manager. Store related credentials as a single JSON object to minimize cost. The EC2 instance authenticates via an IAM Instance Profile (no static AWS keys on the machine). Credentials are held in memory only for the duration of the trading session and are never written to disk.

**Local deployment:** Use `pass`, the standard Unix password manager. Each secret is stored as a GPG-encrypted file in `~/.password-store/whitelight/`. The trading script retrieves credentials at runtime via `pass show whitelight/alpaca-key`, loads them into memory, and never writes plaintext to disk. The GPG private key should be protected with a strong passphrase, and the keyring should be backed up securely (e.g., encrypted USB drive stored off-site).

### 7.2 IAM & Access Control (AWS)

- **EC2 Instance Profile:** The EC2 instance uses an IAM Role (not static access keys) to authenticate with AWS services. This role grants access to Secrets Manager, CloudWatch Logs, and SNS — nothing else.
- **Principle of least privilege:** Each IAM policy grants only the minimum permissions required. The instance cannot create/delete other AWS resources, access S3 buckets, or modify IAM policies.
- **No root account usage:** All operations use dedicated IAM users/roles. The AWS root account has MFA enabled and is used only for billing.

### 7.3 Network Security

- **AWS — VPC isolation:** The EC2 instance runs in a private subnet within a dedicated VPC. It has no public IP address. A NAT Gateway provides outbound internet access. Security Groups restrict all inbound traffic except SSH from a single whitelisted IP.
- **Local — Firewall:** UFW or iptables configured to deny all inbound traffic except SSH from trusted IPs. The trading bot only makes outbound HTTPS connections.
- **IB Gateway ports (7496/7497):** These are bound to localhost only — they are not exposed to the network (both deployments).

### 7.4 Instance Hardening

- **SSH key-only authentication:** Password-based SSH is disabled. Access requires a private key stored securely on your local machine (never on the server).
- **Fail2Ban:** Installed and configured to ban IPs after 3 failed SSH attempts.
- **Automatic security updates:** Unattended upgrades enabled for critical security patches.
- **No withdrawal permissions:** Brokerage API keys are configured with trade and read permissions only. Withdrawal/transfer capabilities are never enabled on API keys.

### 7.5 Brokerage-Level Security

- **Alpaca:** API keys are scoped to trading and account-read permissions only. IP whitelisting is enabled, restricting API access to the server's public IP.
- **Interactive Brokers:** IB Gateway runs with a dedicated "API-only" user that has trading permissions but cannot initiate wire transfers or ACH withdrawals. Two-factor authentication is enabled on the master account.
- **Separate API keys per brokerage:** Each brokerage gets its own dedicated API credentials. Compromise of one does not affect the other.

### 7.6 Audit & Incident Response

- All API calls, order placements, and credential retrievals are logged with timestamps.
- **AWS deployment:** Logs go to CloudWatch Logs. CloudWatch Alarms trigger SNS notifications if unexpected activity is detected (e.g., more than 10 orders in a single session, API authentication failures, or instance running longer than 30 minutes).
- **Local deployment:** Logs go to `/var/log/whitelight/` with `logrotate` managing retention. The trading script itself sends alert notifications (via Telegram/Pushover) for anomalous activity. A simple watchdog script checks log output after each session and flags errors.
- Logs are retained for 90 days minimum for post-incident analysis.

---

## 8. Future Enhancements (Phase 2)

### 8.1 Signal Syndication via Collective2

The strategy is already listed on Collective2 as "Whitelight" (ID: K6Q9FDJ8A) with $1.2M in follower live capital and a $50/month subscription price. Phase 2 will build a direct API integration to automate signal broadcasting from the White Light engine to Collective2, eliminating any manual signal entry.

- Direct API linking to subscriber brokerage accounts.
- SMS-based trade alerts.
- Email-based trade notifications.

### 8.2 Additional Brokerage Integrations

Extend API connectivity to E-Trade and potentially Fidelity (if/when a public API becomes available) to serve a broader user base and provide additional redundancy.

### 8.3 Enhanced Risk Controls

- **Emergency stop (circuit breaker):** Automatic halt of all trading activity if portfolio drawdown exceeds a configurable threshold. Note: the historical max drawdown is -37.58%, so a circuit breaker at -40% to -45% would allow normal operation while catching catastrophic scenarios.
- **Volatility filters:** Additional logic to reduce position sizing during periods of extreme market turbulence.
- **Manual override interface:** A secure web or mobile dashboard allowing the user to pause, resume, or manually adjust the system in real-time.

---

## 9. Glossary

| Term | Definition |
|------|-----------|
| NDX | NASDAQ 100 Index — benchmark index of 100 largest non-financial NASDAQ-listed companies |
| TQQQ | ProShares UltraPro QQQ — 3x leveraged ETF tracking the NASDAQ 100 (long) |
| SQQQ | ProShares UltraPro Short QQQ — 3x inverse leveraged ETF tracking the NASDAQ 100 (short) |
| SMA | Simple Moving Average — arithmetic mean of closing prices over a specified number of days |
| Mean Reversion | Strategy based on the tendency of prices to return to their historical average after extreme moves |
| Velocity | Rate of change of a trend; measures whether momentum is accelerating or decelerating |
| Collective2 | Third-party platform for syndicating and mirroring trade signals across subscriber brokerage accounts |
| Alpha | Excess return relative to the benchmark (0.0415 = strategy outperforms benchmark by ~4.15% annually on a risk-adjusted basis) |
| Beta | Sensitivity to market movements (0.7998 = strategy captures ~80% of market moves, indicating some downside protection) |
| Max Drawdown | Largest peak-to-valley decline in portfolio value (-37.58% for this strategy) |

---

## Appendix A: Collective2 Disclaimers

All results shown in Section 1.1 and 1.2 are hypothetical performance results as reported by Collective2, LLC (a member of the National Futures Association). These results have certain inherent limitations: they do not represent actual trading, may have under- or over-compensated for the impact of certain market factors such as lack of liquidity, and are subject to the benefit of hindsight. No representation is being made that any account will or is likely to achieve profits or losses similar to those shown. Trading is risky and you can lose money. Past results are not necessarily indicative of future results.

Source: [collective2.com/my/K6Q9FDJ8A](https://collective2.com/my/K6Q9FDJ8A), captured February 21, 2026.
