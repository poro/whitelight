# Earnings & News Events Strategy (Development)

*Created: 2026-02-26 — Thinking stage, not yet implemented*

## Trigger
TQQQ position on NVDA earnings day (Feb 26, 2026). Price rose ~1% after-hours on earnings beat, then fell on profit-taking. Classic "buy the rumor, sell the news" amplified by 3x leverage.

## Key Insight
Known catalysts (earnings, Fed, CPI) create binary outcomes. Momentum/mean-reversion strategies assume continuous price action, not gap events. Leveraged ETFs amplify the risk.

## Concentration Risk
- QQQ top 10 holdings = ~50% of index
- TQQQ = 3x QQQ → single stock earnings can move TQQQ 2-5% overnight
- NVDA alone: ~4% QQQ weight → ~12% effective TQQQ exposure

## Possible Approaches

### 1. Earnings Calendar Filter
- Maintain list of top-10 QQQ holdings earnings dates
- On earnings day (or day before): skip TQQQ entry or reduce size by 50%
- Sources: earnings-calendar APIs (Polygon, Alpha Vantage)

### 2. Post-Earnings Re-entry
- Wait T+1 or T+2 after major earnings to let profit-taking/gap-fill play out
- Enter on confirmed direction rather than pre-announcement momentum

### 3. Volatility Stand-Aside
- If VIX > threshold (e.g., 20) or TQQQ implied vol spikes, skip leveraged entries
- Use VIX as a meta-signal for "binary event risk is elevated"

### 4. Sector Rotation on Event Days
- On mega-cap earnings days, rotate allocation to non-correlated assets
- BIL (T-bills), TLT (bonds), GLD (gold) as safe harbors

### 5. Position Sizing Based on Event Calendar
- Normal days: full position
- Earnings week for top holdings: half position
- Fed/CPI days: minimal or no leveraged exposure

## Implementation Priority
1. Earnings calendar data integration (low effort, high value)
2. Simple "skip TQQQ on earnings day" rule
3. VIX filter (medium effort)
4. Full event-aware position sizing (later)

## Status
**Thinking only** — no code changes yet. Revisit when ready to enhance the pipeline.
