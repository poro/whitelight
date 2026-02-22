"""Backtesting engine for the White Light trading system.

Replays historical NDX, TQQQ, and SQQQ data through the strategy engine
day-by-day, simulating portfolio rebalancing at closing prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_DOWN
from typing import Optional

import pandas as pd

from whitelight.backtest import metrics as bt_metrics
from whitelight.models import TargetAllocation
from whitelight.strategy.base import SubStrategy
from whitelight.strategy.combiner import SignalCombiner
from whitelight.strategy.engine import StrategyEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    start_date: date
    end_date: date
    initial_capital: Decimal = Decimal("100000")
    # Minimum lookback days for the longest indicator (250-day SMA + buffer).
    warmup_days: int = 260


@dataclass
class DailySnapshot:
    """State of the portfolio on a single trading day."""

    date: date
    target: TargetAllocation
    tqqq_shares: int
    sqqq_shares: int
    cash: Decimal
    portfolio_value: Decimal
    tqqq_price: float
    sqqq_price: float
    composite_score: float


@dataclass
class BacktestResult:
    """Complete output of a backtest run."""

    config: BacktestConfig
    daily_snapshots: list[DailySnapshot]
    trades: list[dict]  # {date, symbol, side, shares, price, pnl?, duration_days?}
    metrics: dict  # performance metrics
    monthly_returns: pd.DataFrame  # for C2 comparison

    def summary(self) -> str:
        """Return a human-readable summary of the backtest results."""
        lines = [
            "",
            "=" * 60,
            "  WHITE LIGHT BACKTEST RESULTS",
            "=" * 60,
            f"  Period:         {self.config.start_date} to {self.config.end_date}",
            f"  Initial Capital: ${self.config.initial_capital:,.2f}",
            f"  Trading Days:    {self.metrics.get('trading_days', 0)}",
            "-" * 60,
        ]

        final_val = float(self.daily_snapshots[-1].portfolio_value) if self.daily_snapshots else 0
        lines.append(f"  Final Value:     ${final_val:,.2f}")

        m = self.metrics
        lines.extend([
            f"  Total Return:    {m.get('total_return', 0) * 100:+.2f}%",
            f"  Annual Return:   {m.get('annual_return', 0) * 100:+.2f}%  (CAGR)",
            f"  Max Drawdown:    {m.get('max_drawdown', 0) * 100:.2f}%",
            f"  Sharpe Ratio:    {m.get('sharpe_ratio', 0):.2f}",
            f"  Sortino Ratio:   {m.get('sortino_ratio', 0):.2f}",
            f"  Calmar Ratio:    {m.get('calmar_ratio', 0):.2f}",
            "-" * 60,
            f"  Total Trades:    {m.get('total_trades', 0)}",
            f"  Win Rate:        {m.get('win_rate', 0) * 100:.1f}%",
            f"  Profit Factor:   {m.get('profit_factor', 0):.2f}",
            f"  Avg Win:         {m.get('avg_winning_trade', 0) * 100:+.2f}%",
            f"  Avg Loss:        {m.get('avg_losing_trade', 0) * 100:+.2f}%",
            f"  Avg Duration:    {m.get('avg_trade_duration', 0):.1f} days",
            "=" * 60,
            "",
        ])
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BacktestRunner:
    """Replay historical data through the strategy engine day-by-day.

    For each trading day after the warmup period:

    1. Slice NDX data from the beginning of history up to (and including)
       the current day.
    2. Feed that slice to the :class:`StrategyEngine` to get a
       :class:`TargetAllocation`.
    3. Simulate portfolio rebalancing at closing prices.
    4. Record the daily snapshot (positions, cash, portfolio value).

    The runner simulates market orders at closing prices, matching the live
    system's execution model.  No slippage is modelled because TQQQ and SQQQ
    are highly liquid ETFs.

    Parameters
    ----------
    strategies:
        List of sub-strategies (S1--S7).
    combiner:
        A :class:`SignalCombiner` instance.  The combiner is **stateful**
        (it tracks the previous allocation for the no-flip rule), so days
        must be processed sequentially.
    backtest_config:
        Backtest parameters (date range, initial capital, warmup).
    """

    def __init__(
        self,
        strategies: list[SubStrategy],
        combiner: SignalCombiner,
        backtest_config: BacktestConfig,
    ) -> None:
        self._strategies = strategies
        self._combiner = combiner
        self._config = backtest_config
        self._engine = StrategyEngine(strategies, combiner)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        ndx_data: pd.DataFrame,
        tqqq_data: pd.DataFrame,
        sqqq_data: pd.DataFrame,
    ) -> BacktestResult:
        """Execute the full backtest.

        Parameters
        ----------
        ndx_data:
            NDX daily OHLCV data.  Must be indexed by date with columns
            ``[open, high, low, close, volume]``.  Should cover the warmup
            period *before* ``start_date``.
        tqqq_data:
            TQQQ daily OHLCV data (same format).
        sqqq_data:
            SQQQ daily OHLCV data (same format).

        Returns
        -------
        BacktestResult
            The complete backtest output with snapshots, trades, and metrics.
        """
        # Ensure data is indexed by date.
        ndx = self._ensure_date_index(ndx_data)
        tqqq = self._ensure_date_index(tqqq_data)
        sqqq = self._ensure_date_index(sqqq_data)

        # Determine the universe of trading days within the requested range.
        start = pd.Timestamp(self._config.start_date)
        end = pd.Timestamp(self._config.end_date)

        # All days where we have data for all three tickers within the range.
        common_dates = ndx.index.intersection(tqqq.index).intersection(sqqq.index)
        trading_days = sorted(d for d in common_dates if start <= d <= end)

        if not trading_days:
            logger.warning("No trading days found in the requested range")
            return BacktestResult(
                config=self._config,
                daily_snapshots=[],
                trades=[],
                metrics={},
                monthly_returns=pd.DataFrame(columns=["year", "month", "return_pct"]),
            )

        logger.info(
            "Backtesting %d trading days: %s to %s",
            len(trading_days),
            trading_days[0].date(),
            trading_days[-1].date(),
        )

        # Portfolio state.
        cash = self._config.initial_capital
        tqqq_shares = 0
        sqqq_shares = 0

        snapshots: list[DailySnapshot] = []
        all_trades: list[dict] = []

        # Track open positions for round-trip trade calculation.
        open_positions: dict[str, _OpenPosition] = {}

        for day in trading_days:
            # 1. Get closing prices for today.
            tqqq_price = float(tqqq.loc[day, "close"])
            sqqq_price = float(sqqq.loc[day, "close"])

            # 2. Slice NDX data up to and including this day.
            ndx_slice = ndx.loc[:day]

            # 3. Check we have enough history for the warmup.
            if len(ndx_slice) < self._config.warmup_days:
                logger.debug(
                    "Skipping %s: only %d days of NDX history (need %d)",
                    day.date(),
                    len(ndx_slice),
                    self._config.warmup_days,
                )
                continue

            # 4. Run the strategy engine.
            try:
                target = self._engine.evaluate(ndx_slice)
            except Exception:
                logger.exception("Strategy engine failed on %s; holding positions", day.date())
                # Record snapshot with current state.
                portfolio_val = cash + Decimal(str(tqqq_shares * tqqq_price)) + Decimal(str(sqqq_shares * sqqq_price))
                snapshots.append(DailySnapshot(
                    date=day.date(),
                    target=TargetAllocation(
                        tqqq_pct=Decimal("0"), sqqq_pct=Decimal("0"), cash_pct=Decimal("1"),
                    ),
                    tqqq_shares=tqqq_shares,
                    sqqq_shares=sqqq_shares,
                    cash=cash,
                    portfolio_value=portfolio_val,
                    tqqq_price=tqqq_price,
                    sqqq_price=sqqq_price,
                    composite_score=0.0,
                ))
                continue

            # 5. Calculate current portfolio value.
            portfolio_val = (
                cash
                + Decimal(str(tqqq_shares * tqqq_price))
                + Decimal(str(sqqq_shares * sqqq_price))
            )

            # 6. Determine target positions.
            target_tqqq_value = portfolio_val * target.tqqq_pct
            target_sqqq_value = portfolio_val * target.sqqq_pct

            target_tqqq_shares = int(
                (target_tqqq_value / Decimal(str(tqqq_price))).to_integral_value(rounding=ROUND_DOWN)
            ) if tqqq_price > 0 else 0

            target_sqqq_shares = int(
                (target_sqqq_value / Decimal(str(sqqq_price))).to_integral_value(rounding=ROUND_DOWN)
            ) if sqqq_price > 0 else 0

            # 7. Execute rebalance trades.
            day_trades, cash, tqqq_shares, sqqq_shares = self._rebalance(
                day=day,
                cash=cash,
                tqqq_shares=tqqq_shares,
                sqqq_shares=sqqq_shares,
                target_tqqq_shares=target_tqqq_shares,
                target_sqqq_shares=target_sqqq_shares,
                tqqq_price=tqqq_price,
                sqqq_price=sqqq_price,
                open_positions=open_positions,
            )
            all_trades.extend(day_trades)

            # 8. Recalculate portfolio value after trades.
            portfolio_val = (
                cash
                + Decimal(str(tqqq_shares * tqqq_price))
                + Decimal(str(sqqq_shares * sqqq_price))
            )

            # 9. Record the snapshot.
            snapshots.append(DailySnapshot(
                date=day.date(),
                target=target,
                tqqq_shares=tqqq_shares,
                sqqq_shares=sqqq_shares,
                cash=cash,
                portfolio_value=portfolio_val,
                tqqq_price=tqqq_price,
                sqqq_price=sqqq_price,
                composite_score=target.composite_score,
            ))

        # Compute performance metrics.
        completed_trades = [t for t in all_trades if "pnl" in t]
        result_metrics = bt_metrics.compute_all(snapshots, completed_trades)

        # Compute monthly returns.
        monthly_rets = bt_metrics.monthly_returns(
            dates=[s.date for s in snapshots],
            portfolio_values=[s.portfolio_value for s in snapshots],
        )

        result = BacktestResult(
            config=self._config,
            daily_snapshots=snapshots,
            trades=all_trades,
            metrics=result_metrics,
            monthly_returns=monthly_rets,
        )

        logger.info("Backtest complete: %d snapshots, %d trades", len(snapshots), len(all_trades))
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_date_index(df: pd.DataFrame) -> pd.DataFrame:
        """Ensure the DataFrame is indexed by a normalised DatetimeIndex.

        Handles both the "date column" format (from PolygonClient / YFinanceClient)
        and the "date index" format (from the test fixture).
        """
        if "date" in df.columns:
            df = df.copy()
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()
            df = df.set_index("date")
        elif not isinstance(df.index, pd.DatetimeIndex):
            df = df.copy()
            df.index = pd.to_datetime(df.index).normalize()

        df = df.sort_index()
        df.index.name = "date"
        return df

    @staticmethod
    def _rebalance(
        *,
        day: pd.Timestamp,
        cash: Decimal,
        tqqq_shares: int,
        sqqq_shares: int,
        target_tqqq_shares: int,
        target_sqqq_shares: int,
        tqqq_price: float,
        sqqq_price: float,
        open_positions: dict[str, _OpenPosition],
    ) -> tuple[list[dict], Decimal, int, int]:
        """Simulate rebalancing to target share counts at closing prices.

        Returns:
            (trades_today, new_cash, new_tqqq_shares, new_sqqq_shares)
        """
        trades: list[dict] = []

        # --- TQQQ ---
        tqqq_delta = target_tqqq_shares - tqqq_shares
        if tqqq_delta != 0:
            if tqqq_delta > 0:
                # Buy TQQQ.
                cost = Decimal(str(tqqq_delta * tqqq_price))
                cash -= cost
                tqqq_shares += tqqq_delta
                trades.append({
                    "date": day.date(),
                    "symbol": "TQQQ",
                    "side": "buy",
                    "shares": tqqq_delta,
                    "price": tqqq_price,
                })
                # Track open position.
                if "TQQQ" not in open_positions:
                    open_positions["TQQQ"] = _OpenPosition(
                        symbol="TQQQ",
                        entry_date=day.date(),
                        entry_price=tqqq_price,
                        shares=tqqq_delta,
                    )
                else:
                    pos = open_positions["TQQQ"]
                    # Average in.
                    total_shares = pos.shares + tqqq_delta
                    avg_price = (
                        (pos.entry_price * pos.shares + tqqq_price * tqqq_delta)
                        / total_shares
                    )
                    open_positions["TQQQ"] = _OpenPosition(
                        symbol="TQQQ",
                        entry_date=pos.entry_date,
                        entry_price=avg_price,
                        shares=total_shares,
                    )
            else:
                # Sell TQQQ.
                sell_qty = abs(tqqq_delta)
                proceeds = Decimal(str(sell_qty * tqqq_price))
                cash += proceeds
                tqqq_shares -= sell_qty
                trades.append({
                    "date": day.date(),
                    "symbol": "TQQQ",
                    "side": "sell",
                    "shares": sell_qty,
                    "price": tqqq_price,
                })
                # Close or reduce open position.
                if "TQQQ" in open_positions:
                    pos = open_positions["TQQQ"]
                    pnl = (tqqq_price - pos.entry_price) * sell_qty
                    duration = (day.date() - pos.entry_date).days
                    trades[-1]["pnl"] = pnl
                    trades[-1]["duration_days"] = duration
                    if sell_qty >= pos.shares:
                        del open_positions["TQQQ"]
                    else:
                        open_positions["TQQQ"] = _OpenPosition(
                            symbol="TQQQ",
                            entry_date=pos.entry_date,
                            entry_price=pos.entry_price,
                            shares=pos.shares - sell_qty,
                        )

        # --- SQQQ ---
        sqqq_delta = target_sqqq_shares - sqqq_shares
        if sqqq_delta != 0:
            if sqqq_delta > 0:
                # Buy SQQQ.
                cost = Decimal(str(sqqq_delta * sqqq_price))
                cash -= cost
                sqqq_shares += sqqq_delta
                trades.append({
                    "date": day.date(),
                    "symbol": "SQQQ",
                    "side": "buy",
                    "shares": sqqq_delta,
                    "price": sqqq_price,
                })
                if "SQQQ" not in open_positions:
                    open_positions["SQQQ"] = _OpenPosition(
                        symbol="SQQQ",
                        entry_date=day.date(),
                        entry_price=sqqq_price,
                        shares=sqqq_delta,
                    )
                else:
                    pos = open_positions["SQQQ"]
                    total_shares = pos.shares + sqqq_delta
                    avg_price = (
                        (pos.entry_price * pos.shares + sqqq_price * sqqq_delta)
                        / total_shares
                    )
                    open_positions["SQQQ"] = _OpenPosition(
                        symbol="SQQQ",
                        entry_date=pos.entry_date,
                        entry_price=avg_price,
                        shares=total_shares,
                    )
            else:
                # Sell SQQQ.
                sell_qty = abs(sqqq_delta)
                proceeds = Decimal(str(sell_qty * sqqq_price))
                cash += proceeds
                sqqq_shares -= sell_qty
                trades.append({
                    "date": day.date(),
                    "symbol": "SQQQ",
                    "side": "sell",
                    "shares": sell_qty,
                    "price": sqqq_price,
                })
                if "SQQQ" in open_positions:
                    pos = open_positions["SQQQ"]
                    pnl = (sqqq_price - pos.entry_price) * sell_qty
                    duration = (day.date() - pos.entry_date).days
                    trades[-1]["pnl"] = pnl
                    trades[-1]["duration_days"] = duration
                    if sell_qty >= pos.shares:
                        del open_positions["SQQQ"]
                    else:
                        open_positions["SQQQ"] = _OpenPosition(
                            symbol="SQQQ",
                            entry_date=pos.entry_date,
                            entry_price=pos.entry_price,
                            shares=pos.shares - sell_qty,
                        )

        return trades, cash, tqqq_shares, sqqq_shares


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@dataclass
class _OpenPosition:
    """Track an open position for round-trip trade accounting."""

    symbol: str
    entry_date: date
    entry_price: float
    shares: int
