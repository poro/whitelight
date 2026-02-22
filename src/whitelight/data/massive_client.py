"""Massive REST API client for fetching daily OHLCV bars.

Massive (massive.com) provides a Polygon-compatible REST API at
``https://api.massive.com``.  This client talks directly to that endpoint
via httpx, avoiding a dependency on the ``polygon-api-client`` library.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import httpx
import pandas as pd
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.massive.com"

# Indices use the "I:" prefix (same convention as Polygon).
_INDEX_TICKERS = {"NDX", "SPX", "DJI", "RUT"}

# Standard column order for all downstream consumers.
OHLCV_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


class MassiveAPIError(Exception):
    """Raised when a Massive API call fails after all retries."""

    def __init__(self, message: str, ticker: str = "", retriable: bool = False):
        super().__init__(message)
        self.ticker = ticker
        self.retriable = retriable


class MassiveClient:
    """Fetch daily OHLCV bars from the Massive REST API.

    The response schema is identical to Polygon.io v2 aggregates:
    ``{v, vw, o, c, h, l, t, n}`` per bar.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: Optional[str] = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or BASE_URL).rstrip("/")
        self._http = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Fetch daily OHLCV bars for *ticker* between *start_date* and *end_date*.

        Returns a DataFrame with columns ``[date, open, high, low, close, volume]``
        sorted by date ascending.  Returns an empty DataFrame when no data is
        available.
        """
        wire_ticker = self._to_wire_ticker(ticker)
        logger.info(
            "Fetching daily bars: ticker=%s (%s) from=%s to=%s",
            ticker,
            wire_ticker,
            start_date,
            end_date,
        )

        try:
            results = self._fetch_aggs(wire_ticker, start_date, end_date)
        except Exception as exc:
            raise MassiveAPIError(
                f"Failed to fetch bars for {ticker}: {exc}",
                ticker=ticker,
                retriable=isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)),
            ) from exc

        if not results:
            logger.warning("No bars returned for %s (%s - %s)", ticker, start_date, end_date)
            return _empty_dataframe()

        rows = []
        for bar in results:
            rows.append(
                {
                    "date": pd.Timestamp(bar["t"], unit="ms").normalize(),
                    "open": float(bar["o"]),
                    "high": float(bar["h"]),
                    "low": float(bar["l"]),
                    "close": float(bar["c"]),
                    "volume": int(bar.get("v", 0) or 0),
                }
            )

        df = pd.DataFrame(rows, columns=OHLCV_COLUMNS)
        df = df.sort_values("date").reset_index(drop=True)
        logger.info("Fetched %d bars for %s", len(df), ticker)
        return df

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._http.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(
            (httpx.TimeoutException, httpx.ConnectError, ConnectionError)
        ),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _fetch_aggs(
        self,
        wire_ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict]:
        url = (
            f"{self._base_url}/v2/aggs/ticker/{wire_ticker}"
            f"/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}"
        )
        resp = self._http.get(url, params={"apiKey": self._api_key, "limit": 50000, "sort": "asc"})
        resp.raise_for_status()

        data = resp.json()
        results = data.get("results") or []
        count = len(results)

        if count == 0:
            logger.debug("API returned 0 results for %s", wire_ticker)

        return results

    @staticmethod
    def _to_wire_ticker(ticker: str) -> str:
        upper = ticker.upper()
        if upper in _INDEX_TICKERS:
            return f"I:{upper}"
        return upper


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=OHLCV_COLUMNS)
