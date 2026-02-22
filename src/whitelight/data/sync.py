"""Data synchronisation orchestrator.

Keeps the local Parquet cache up-to-date by fetching delta bars from
Polygon.io when the cache is stale.  Falls back gracefully to cached
data if the API is unavailable.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from whitelight.config import DataConfig
from whitelight.data.cache import CacheManager
from whitelight.data.calendar import MarketCalendar
from whitelight.data.polygon_client import PolygonClient, PolygonAPIError

logger = logging.getLogger(__name__)


class DataSyncer:
    """Coordinate cache reads, staleness checks, API fetches, and validation.

    Typical usage::

        syncer = DataSyncer(polygon_client, cache_manager, data_config)
        frames = syncer.sync(["NDX", "TQQQ", "SQQQ"])
        ndx_df = frames["NDX"]
    """

    def __init__(
        self,
        polygon_client: PolygonClient,
        cache_manager: CacheManager,
        data_config: DataConfig,
        calendar: Optional[MarketCalendar] = None,
    ) -> None:
        self._polygon = polygon_client
        self._cache = cache_manager
        self._config = data_config
        self._calendar = calendar or MarketCalendar()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync(self, tickers: Optional[list[str]] = None) -> dict[str, pd.DataFrame]:
        """Sync all *tickers* (defaults to config list) and return a mapping
        of ``{ticker: DataFrame}``.
        """
        tickers = tickers or self._config.tickers
        results: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            results[ticker] = self.sync_ticker(ticker)
        return results

    def sync_ticker(self, ticker: str) -> pd.DataFrame:
        """Sync a single ticker: check cache, fetch delta, append, validate.

        If the Polygon API is unreachable the method falls back to whatever
        data is already in the cache (which may be stale or empty).
        """
        logger.info("--- Syncing %s ---", ticker)

        # 1. Determine what we already have.
        cached_last = self._cache.last_date(ticker)
        if cached_last is not None:
            logger.info("Cache for %s is current through %s", ticker, cached_last)
        else:
            logger.info("No cached data for %s; will fetch full history", ticker)

        # 2. Decide the fetch window.
        fetch_start = self._fetch_start_date(cached_last)
        fetch_end = self._fetch_end_date()

        if fetch_start > fetch_end:
            logger.info("Cache for %s is already up-to-date", ticker)
            return self._cache.read(ticker)

        # 3. Fetch from Polygon.
        logger.info("Fetching %s from %s to %s", ticker, fetch_start, fetch_end)
        try:
            new_bars = self._polygon.get_daily_bars(ticker, fetch_start, fetch_end)
        except PolygonAPIError as exc:
            logger.error(
                "Polygon API error for %s: %s — falling back to cache", ticker, exc
            )
            return self._cache.read(ticker)
        except Exception as exc:
            logger.error(
                "Unexpected error fetching %s: %s — falling back to cache", ticker, exc
            )
            return self._cache.read(ticker)

        if new_bars.empty:
            logger.warning("Polygon returned no new bars for %s", ticker)
            return self._cache.read(ticker)

        # 4. Merge into cache.
        logger.info("Appending %d new bars for %s", len(new_bars), ticker)
        full_df = self._cache.append(ticker, new_bars)

        # 5. Validate.
        if not self._cache.validate(ticker):
            logger.warning("Cache validation failed for %s after sync", ticker)
        else:
            logger.info("Cache validated for %s (%d total rows)", ticker, len(full_df))

        return full_df

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_start_date(self, cached_last: Optional[date]) -> date:
        """Work out where to start fetching.

        If the cache has data, start the day *after* the last cached date so
        we only download the delta.  Otherwise, go back to the configured
        history start.
        """
        if cached_last is None:
            return date.fromisoformat(self._config.history_start_date)
        # Start one day after the last cached bar.
        return cached_last + timedelta(days=1)

    def _fetch_end_date(self) -> date:
        """Return today (or the most recent past trading day) as the fetch end.

        Polygon data for the current day becomes available after market close,
        so we use today's date and let the API return however many bars are
        available.
        """
        return date.today()
