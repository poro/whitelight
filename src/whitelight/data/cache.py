"""Parquet-based local cache for daily OHLCV data."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from whitelight.data.polygon_client import OHLCV_COLUMNS

logger = logging.getLogger(__name__)

# Filename convention: ndx_daily.parquet, tqqq_daily.parquet, etc.
_FILENAME_TEMPLATE = "{ticker}_daily.parquet"


class CacheManager:
    """Read/write daily OHLCV DataFrames as Parquet files.

    Each ticker gets its own file inside *cache_dir*.  Files are always
    stored sorted by ``date`` ascending with no duplicate dates.
    """

    def __init__(self, cache_dir: str | Path) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("CacheManager initialised: cache_dir=%s", self._cache_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, ticker: str) -> pd.DataFrame:
        """Read the cached DataFrame for *ticker*.

        Returns an empty DataFrame (with correct columns) if the cache
        file does not exist.
        """
        path = self._path_for(ticker)
        if not path.exists():
            logger.debug("Cache miss for %s (file does not exist)", ticker)
            return _empty_dataframe()

        df = pd.read_parquet(path)
        df = _normalise(df)
        logger.debug("Cache hit for %s: %d rows", ticker, len(df))
        return df

    def write(self, ticker: str, df: pd.DataFrame) -> None:
        """Overwrite the entire cache file for *ticker*."""
        df = _normalise(df)
        path = self._path_for(ticker)
        df.to_parquet(path, index=False, engine="pyarrow")
        logger.info("Wrote %d rows to %s", len(df), path)

    def append(self, ticker: str, new_data: pd.DataFrame) -> pd.DataFrame:
        """Append *new_data* to the cached file, deduplicate by date, and return
        the combined DataFrame.

        If the cache file does not exist, this is equivalent to ``write``.
        """
        existing = self.read(ticker)
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined = _normalise(combined)

        # Deduplicate: keep the latest occurrence (i.e. fresh data wins).
        combined = combined.drop_duplicates(subset="date", keep="last")
        combined = combined.sort_values("date").reset_index(drop=True)

        self.write(ticker, combined)
        logger.info(
            "Appended %d new rows for %s (total %d)",
            len(new_data),
            ticker,
            len(combined),
        )
        return combined

    def last_date(self, ticker: str) -> Optional[date]:
        """Return the most recent date in the cache for *ticker*, or ``None``
        if the cache is empty/missing.
        """
        df = self.read(ticker)
        if df.empty:
            return None
        last_ts = df["date"].max()
        return pd.Timestamp(last_ts).date()

    def validate(self, ticker: str) -> bool:
        """Run basic integrity checks on the cached data.

        Checks:
        1. File exists and is non-empty.
        2. All required columns are present.
        3. Data is sorted by date ascending.
        4. No duplicate dates.
        5. No calendar-day gaps larger than 5 days (accounts for long weekends
           and holidays but catches gross gaps).
        """
        df = self.read(ticker)
        if df.empty:
            logger.warning("Validation failed for %s: cache is empty", ticker)
            return False

        # Column check.
        missing_cols = set(OHLCV_COLUMNS) - set(df.columns)
        if missing_cols:
            logger.warning("Validation failed for %s: missing columns %s", ticker, missing_cols)
            return False

        # Sorted check.
        dates = df["date"]
        if not dates.is_monotonic_increasing:
            logger.warning("Validation failed for %s: dates not sorted", ticker)
            return False

        # Duplicate check.
        if dates.duplicated().any():
            logger.warning("Validation failed for %s: duplicate dates found", ticker)
            return False

        # Gap check: no gap > 5 calendar days (handles typical holidays).
        if len(dates) > 1:
            gaps = dates.diff().dropna()
            max_gap = gaps.max()
            if max_gap > pd.Timedelta(days=5):
                logger.warning(
                    "Validation failed for %s: max gap of %s exceeds 5 days",
                    ticker,
                    max_gap,
                )
                return False

        logger.debug("Validation passed for %s (%d rows)", ticker, len(df))
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _path_for(self, ticker: str) -> Path:
        filename = _FILENAME_TEMPLATE.format(ticker=ticker.lower())
        return self._cache_dir / filename


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure standard column types and ordering."""
    if df.empty:
        return _empty_dataframe()

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["volume"] = df["volume"].astype(int)
    df = df[OHLCV_COLUMNS]
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _empty_dataframe() -> pd.DataFrame:
    """Return an empty DataFrame with the standard OHLCV schema."""
    return pd.DataFrame(columns=OHLCV_COLUMNS)
