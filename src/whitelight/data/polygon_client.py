"""Polygon.io REST API wrapper for fetching daily OHLCV bars."""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd
from polygon import RESTClient
from polygon.exceptions import BadResponse
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Polygon uses the "I:" prefix for index tickers.
_INDEX_TICKERS = {"NDX", "SPX", "DJI", "RUT"}

# Column order expected by all downstream consumers.
OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class PolygonAPIError(Exception):
    """Raised when a Polygon API call fails after all retries."""

    def __init__(self, message: str, ticker: str = "", retriable: bool = False):
        super().__init__(message)
        self.ticker = ticker
        self.retriable = retriable


class PolygonClient:
    """Thin wrapper around the ``polygon-api-client`` library.

    Handles:
    * Index ticker prefix (``I:NDX``) transparently.
    * Rate-limit retries via tenacity.
    * Normalised DataFrame output with consistent column names.
    """

    def __init__(self, api_key: str, *, base_url: Optional[str] = None) -> None:
        kwargs: dict = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = RESTClient(**kwargs)
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for *ticker* between *start_date* and *end_date* (inclusive).

        Returns a ``pd.DataFrame`` with columns:
            date (datetime64[ns]), open, high, low, close, volume
        sorted by date ascending.  Returns an empty DataFrame (with correct
        columns) when no results are available.
        """
        polygon_ticker = self._to_polygon_ticker(ticker)
        logger.info(
            "Fetching daily bars: ticker=%s (%s) from=%s to=%s",
            ticker,
            polygon_ticker,
            start_date,
            end_date,
        )

        try:
            bars = self._fetch_aggs(
                polygon_ticker,
                start_date.isoformat(),
                end_date.isoformat(),
            )
        except Exception as exc:
            raise PolygonAPIError(
                f"Failed to fetch bars for {ticker}: {exc}",
                ticker=ticker,
                retriable=isinstance(exc, BadResponse),
            ) from exc

        if not bars:
            logger.warning("No bars returned for %s (%s - %s)", ticker, start_date, end_date)
            return _empty_dataframe()

        rows = []
        for bar in bars:
            rows.append(
                {
                    "date": pd.Timestamp(bar.timestamp, unit="ms").normalize(),
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": int(bar.volume) if bar.volume else 0,
                }
            )

        df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
        df = df.sort_values("date").reset_index(drop=True)
        logger.info("Fetched %d bars for %s", len(df), ticker)
        return df

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((BadResponse, ConnectionError, TimeoutError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _fetch_aggs(self, polygon_ticker: str, from_: str, to: str) -> list:
        """Call the Polygon aggregates endpoint with automatic retries."""
        results = list(
            self._client.list_aggs(
                ticker=polygon_ticker,
                multiplier=1,
                timespan="day",
                from_=from_,
                to=to,
                limit=50000,
            )
        )
        return results

    @staticmethod
    def _to_polygon_ticker(ticker: str) -> str:
        """Convert a logical ticker to the Polygon wire format.

        For indices Polygon requires the ``I:`` prefix, e.g. ``I:NDX``.
        """
        upper = ticker.upper()
        if upper in _INDEX_TICKERS:
            return f"I:{upper}"
        return upper


def _empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with the standard OHLCV schema."""
    return pd.DataFrame(columns=OHLCV_COLUMNS)
