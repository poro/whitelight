"""Yahoo Finance data client for backtesting -- no API key required.

Uses the ``yfinance`` library to download daily OHLCV bars.  This client is
intended for backtesting only; the live system uses :class:`PolygonClient`.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from whitelight.data.polygon_client import OHLCV_COLUMNS

logger = logging.getLogger(__name__)


class YFinanceClient:
    """Free data source for backtesting -- no API key required.

    Translates White Light ticker symbols to their Yahoo Finance equivalents
    and returns DataFrames in the same schema as :class:`PolygonClient`.
    """

    # Yahoo Finance uses "^NDX" for the NASDAQ-100 index.
    TICKER_MAP: dict[str, str] = {
        "NDX": "^NDX",
        "TQQQ": "TQQQ",
        "SQQQ": "SQQQ",
    }

    def get_daily_bars(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """Download daily OHLCV bars from Yahoo Finance.

        Parameters
        ----------
        ticker:
            White Light ticker symbol (e.g. ``"NDX"``, ``"TQQQ"``).
        start_date:
            First date (inclusive).
        end_date:
            Last date (inclusive).

        Returns
        -------
        pd.DataFrame
            DataFrame with columns ``[date, open, high, low, close, volume]``
            sorted by date ascending -- same format as :class:`PolygonClient`.
        """
        yf_ticker = self.TICKER_MAP.get(ticker.upper(), ticker.upper())
        logger.info(
            "Fetching daily bars from Yahoo Finance: ticker=%s (%s) from=%s to=%s",
            ticker,
            yf_ticker,
            start_date,
            end_date,
        )

        # yfinance's ``end`` parameter is exclusive, so add one day.
        end_exclusive = end_date + timedelta(days=1)

        try:
            df = yf.download(
                yf_ticker,
                start=start_date.isoformat(),
                end=end_exclusive.isoformat(),
                auto_adjust=True,
                progress=False,
            )
        except Exception:
            logger.exception("Failed to download data for %s from Yahoo Finance", ticker)
            return _empty_dataframe()

        if df.empty:
            logger.warning("Yahoo Finance returned no data for %s (%s - %s)", ticker, start_date, end_date)
            return _empty_dataframe()

        # yfinance returns a DatetimeIndex; flatten column MultiIndex if present.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.reset_index()

        # Normalise column names to lowercase.
        df.columns = [c.lower() for c in df.columns]

        # Ensure the ``date`` column exists (yfinance may call it ``Date``).
        if "date" not in df.columns and "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})

        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        # Select only the standard columns.
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].astype(float)
        df["volume"] = df["volume"].astype(int)

        df = df[OHLCV_COLUMNS]
        df = df.sort_values("date").reset_index(drop=True)

        logger.info("Fetched %d bars for %s from Yahoo Finance", len(df), ticker)
        return df


def _empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with the standard OHLCV schema."""
    return pd.DataFrame(columns=OHLCV_COLUMNS)
