"""Main pipeline orchestrator and CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal
from pathlib import Path

from whitelight.config import WhiteLightConfig
from whitelight.logging_config import setup_logging

logger = logging.getLogger(__name__)


async def run_pipeline(config: WhiteLightConfig, dry_run: bool = False) -> None:
    """Full daily pipeline: boot -> sync -> strategy -> execute -> telemetry -> shutdown."""
    from whitelight.data.sync import DataSyncer
    from whitelight.data.massive_client import MassiveClient
    from whitelight.data.cache import CacheManager
    from whitelight.data.calendar import MarketCalendar
    from whitelight.execution.executor import OrderExecutor
    from whitelight.execution.reconciler import check_rebalance_needed
    from whitelight.providers import (
        create_alert_provider,
        create_brokerage_client,
        create_secrets_provider,
    )
    from whitelight.strategy.engine import StrategyEngine
    from whitelight.strategy.combiner import SignalCombiner
    from whitelight.strategy.substrats.s1_primary_trend import S1PrimaryTrend
    from whitelight.strategy.substrats.s2_intermediate_trend import S2IntermediateTrend
    from whitelight.strategy.substrats.s3_short_term_trend import S3ShortTermTrend
    from whitelight.strategy.substrats.s4_trend_strength import S4TrendStrength
    from whitelight.strategy.substrats.s5_momentum_velocity import S5MomentumVelocity
    from whitelight.strategy.substrats.s6_mean_rev_bollinger import S6MeanRevBollinger
    from whitelight.strategy.substrats.s7_volatility_regime import S7VolatilityRegime
    from whitelight.telemetry.reporter import TelemetryReporter

    # ---- 1. BOOT ----
    secrets = create_secrets_provider(config.secrets)
    alerts = create_alert_provider(config.alerts, secrets)
    reporter = TelemetryReporter(alerts)

    await reporter.report_pipeline_start()

    brokerage = create_brokerage_client(config.brokerages, secrets, alerts)

    try:
        if not dry_run:
            await brokerage.connect()

        # ---- 2. DATA SYNC ----
        api_key = secrets.get_secret("polygon/api_key")
        data_client = MassiveClient(api_key=api_key)
        cache = CacheManager(cache_dir=config.data.cache_dir)
        syncer = DataSyncer(
            polygon_client=data_client,
            cache_manager=cache,
            data_config=config.data,
        )

        data = syncer.sync(config.data.tickers)
        ndx_data = data.get("NDX")
        if ndx_data is None or ndx_data.empty:
            raise RuntimeError("No NDX data available after sync")

        logger.info("NDX data loaded: %d rows, latest date: %s", len(ndx_data), ndx_data.index[-1])

        # ---- 2b. INTRADAY SUPPLEMENT ----
        # Append today's real-time prices so ALL signals reflect the current
        # session, not just yesterday's close.  NDX comes from yfinance
        # (intraday), TQQQ/SQQQ/BIL come from Alpaca real-time quotes.
        try:
            import yfinance as yf
            import pandas as pd
            from datetime import date as _date

            today = _date.today()

            # --- NDX from yfinance (index — not available via Alpaca) ---
            last_cached = ndx_data.index[-1]
            if hasattr(last_cached, 'date'):
                last_date = last_cached.date() if hasattr(last_cached, 'date') else last_cached
            else:
                last_date = pd.Timestamp(last_cached).date()

            if last_date < today:
                intraday = yf.download("^NDX", period="1d", interval="1m", progress=False)
                if len(intraday) > 0:
                    latest_close = float(intraday["Close"].iloc[-1].values[0])
                    today_row = pd.DataFrame(
                        {"open": latest_close, "high": latest_close, "low": latest_close, "close": latest_close, "volume": 0},
                        index=[pd.Timestamp(today)],
                    )
                    ndx_data = pd.concat([ndx_data, today_row])
                    data["NDX"] = ndx_data
                    logger.info("Appended today's intraday NDX: %.2f (total rows: %d)", latest_close, len(ndx_data))
                else:
                    logger.warning("No intraday NDX data from yfinance — using cached data only")

            # --- TQQQ/SQQQ/BIL from Alpaca real-time quotes ---
            try:
                from alpaca.data.historical import StockHistoricalDataClient
                from alpaca.data.requests import StockLatestQuoteRequest

                alpaca_data_client = StockHistoricalDataClient(
                    secrets.get_secret("alpaca/api_key"),
                    secrets.get_secret("alpaca/api_secret"),
                )
                equity_tickers = ["TQQQ", "SQQQ", "BIL"]
                raw_quotes = alpaca_data_client.get_stock_latest_quote(
                    StockLatestQuoteRequest(symbol_or_symbols=equity_tickers)
                )
                for sym in equity_tickers:
                    if sym not in raw_quotes:
                        continue
                    q = raw_quotes[sym]
                    mid_price = float((q.bid_price + q.ask_price) / 2)
                    if mid_price <= 0:
                        logger.warning("Alpaca quote for %s has zero/negative mid price, skipping", sym)
                        continue

                    sym_data = data.get(sym)
                    if sym_data is None or sym_data.empty:
                        logger.warning("No cached data for %s to supplement", sym)
                        continue

                    sym_last = sym_data.index[-1]
                    sym_last_date = sym_last.date() if hasattr(sym_last, 'date') else pd.Timestamp(sym_last).date()

                    if sym_last_date < today:
                        today_row = pd.DataFrame(
                            {"open": mid_price, "high": mid_price, "low": mid_price, "close": mid_price, "volume": 0},
                            index=[pd.Timestamp(today)],
                        )
                        data[sym] = pd.concat([sym_data, today_row])
                        logger.info("Appended Alpaca real-time %s: $%.2f (total rows: %d)", sym, mid_price, len(data[sym]))
                    else:
                        logger.info("Cache for %s already has today's data", sym)

            except Exception as e:
                logger.warning("Alpaca real-time supplement failed (non-fatal): %s", e)

        except Exception as e:
            logger.warning("Intraday supplement failed (non-fatal): %s", e)

        # ---- 3. STRATEGY ENGINE ----
        weights = config.strategy.substrategy_weights
        params = config.strategy.params

        strategies = [
            S1PrimaryTrend(weight=weights["s1_primary_trend"], **params.get("s1_primary_trend", {})),
            S2IntermediateTrend(weight=weights["s2_intermediate_trend"], **params.get("s2_intermediate_trend", {})),
            S3ShortTermTrend(weight=weights["s3_short_term_trend"], **params.get("s3_short_term_trend", {})),
            S4TrendStrength(weight=weights["s4_trend_strength"], **params.get("s4_trend_strength", {})),
            S5MomentumVelocity(weight=weights["s5_momentum_velocity"], **params.get("s5_momentum_velocity", {})),
            S6MeanRevBollinger(weight=weights["s6_mean_rev_bollinger"], **params.get("s6_mean_rev_bollinger", {})),
            S7VolatilityRegime(weight=weights["s7_volatility_regime"], **params.get("s7_volatility_regime", {})),
        ]

        # Select combiner version
        combiner_version = getattr(config.strategy, 'combiner_version', 1)
        if combiner_version == 2:
            from whitelight.strategy.combiner_v2 import SignalCombinerV2
            combiner = SignalCombinerV2()
            logger.info("Using v2 combiner (vol-adaptive + ATR stops)")
        else:
            combiner = SignalCombiner()
            logger.info("Using v1 combiner (volatility targeting)")
        engine = StrategyEngine(strategies=strategies, combiner=combiner)
        target = engine.evaluate(ndx_data)

        await reporter.report_target_allocation(target)
        logger.info(
            "Target: TQQQ=%.1f%% SQQQ=%.1f%% BIL=%.1f%% (score=%.3f)",
            float(target.tqqq_pct) * 100,
            float(target.sqqq_pct) * 100,
            float(target.cash_pct) * 100,
            target.composite_score,
        )

        if dry_run:
            logger.info("DRY RUN - skipping order execution")
            await reporter.report_pipeline_complete()
            return

        # ---- 4. EXECUTION ----
        calendar = MarketCalendar()
        if not calendar.is_within_execution_window(
            config.execution.window_start_minutes_before_close,
            config.execution.window_end_minutes_before_close,
        ):
            logger.warning("Outside execution window - skipping orders")
            await alerts.send_alert(
                "Outside execution window. Skipping.", priority="high", title="Skipped"
            )
            return

        # Check rebalance threshold
        snapshot = await brokerage.get_portfolio_snapshot()
        if not check_rebalance_needed(
            snapshot, target, config.strategy.min_rebalance_threshold
        ):
            logger.info("Rebalance threshold not met - no trades needed")
            await alerts.send_alert(
                "Portfolio within threshold. No trades.", title="No Action"
            )
            return

        # Get live prices for execution via Alpaca real-time quotes
        _live_quotes: dict[str, Decimal] = {}
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockLatestQuoteRequest
            _data_client = StockHistoricalDataClient(
                secrets.get_secret("alpaca/api_key"),
                secrets.get_secret("alpaca/api_secret"),
            )
            _raw_quotes = _data_client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbol_or_symbols=["TQQQ", "SQQQ", "BIL"])
            )
            for sym, q in _raw_quotes.items():
                mid = (q.bid_price + q.ask_price) / 2
                _live_quotes[sym] = Decimal(str(round(mid, 4)))
                logger.info("Live quote %s: bid=%.2f ask=%.2f mid=%.4f", sym, q.bid_price, q.ask_price, mid)
        except Exception as e:
            logger.warning("Alpaca live quotes failed, falling back to cached prices: %s", e)

        def get_live_price(symbol: str) -> Decimal:
            # Prefer real-time Alpaca quote, fall back to cached close
            if symbol in _live_quotes:
                return _live_quotes[symbol]
            ticker_data = data.get(symbol)
            if ticker_data is not None and not ticker_data.empty:
                return Decimal(str(ticker_data["close"].iloc[-1]))
            raise ValueError(f"No price data for {symbol}")

        executor = OrderExecutor(
            brokerage=brokerage,
            get_live_price=get_live_price,
            alert_provider=alerts,
            min_order_value=Decimal(str(config.execution.min_order_value_usd)),
        )
        result = await executor.execute(target)

        # ---- 5. TELEMETRY ----
        await reporter.report_execution_results(result)

    except Exception as exc:
        logger.critical("Pipeline failed: %s", exc, exc_info=True)
        await reporter.report_error(exc)
        raise

    finally:
        # ---- 6. SHUTDOWN ----
        if not dry_run:
            await brokerage.disconnect()
        await reporter.report_pipeline_complete()


def cli_entry() -> None:
    """CLI entry point for `whitelight` command."""
    parser = argparse.ArgumentParser(
        prog="whitelight",
        description="White Light Automated Trading System",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute the trading pipeline")
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run strategy engine without placing orders",
    )
    run_parser.add_argument(
        "--mode",
        choices=["aws", "local", "paper"],
        help="Deployment mode override",
    )
    run_parser.add_argument(
        "--config-dir",
        type=Path,
        help="Path to config directory",
    )

    # sync command
    subparsers.add_parser("sync", help="Sync market data only")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    config = WhiteLightConfig.load(
        deployment_mode=getattr(args, "mode", None),
        config_dir=getattr(args, "config_dir", None),
    )

    setup_logging(
        level=config.deployment.log_level,
        log_format=config.deployment.log_format,
        log_dir=config.deployment.log_dir,
    )

    if args.command == "run":
        asyncio.run(run_pipeline(config, dry_run=args.dry_run))
    elif args.command == "sync":
        from whitelight.data.sync import DataSyncer
        from whitelight.data.massive_client import MassiveClient
        from whitelight.data.cache import CacheManager
        from whitelight.providers import create_secrets_provider

        secrets = create_secrets_provider(config.secrets)
        api_key = secrets.get_secret("polygon/api_key")
        client = MassiveClient(api_key=api_key)
        cache = CacheManager(cache_dir=config.data.cache_dir)
        syncer = DataSyncer(
            polygon_client=client,
            cache_manager=cache,
            data_config=config.data,
        )
        syncer.sync(config.data.tickers)
        logger.info("Data sync complete")
