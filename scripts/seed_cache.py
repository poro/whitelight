#!/usr/bin/env python3
"""One-time seed script: download full history for all tickers into the Parquet cache.

Usage:
    python -m scripts.seed_cache --api-key YOUR_KEY
    python -m scripts.seed_cache                     # reads WL_POLYGON_API_KEY

The script chunks requests into yearly segments so that no single Polygon API
call spans more than ~365 days, avoiding result-count limits on the free tier.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta

# Ensure the project ``src/`` directory is importable when running the script
# directly (i.e. ``python scripts/seed_cache.py``).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from whitelight.config import WhiteLightConfig
from whitelight.data.cache import CacheManager
from whitelight.data.polygon_client import PolygonClient, PolygonAPIError

logger = logging.getLogger("whitelight.seed_cache")

# Download in yearly chunks to respect Polygon API result limits.
_CHUNK_DAYS = 365


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the local Parquet cache with full history from Polygon.io",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("WL_POLYGON_API_KEY"),
        help="Polygon.io API key (default: WL_POLYGON_API_KEY env var)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override cache directory (default: from config)",
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=None,
        help="Override ticker list (default: from config)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Override history start date YYYY-MM-DD (default: from config)",
    )
    return parser.parse_args()


def _year_chunks(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end] into yearly (or shorter) non-overlapping segments."""
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=_CHUNK_DAYS - 1), end)
        chunks.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def seed(
    api_key: str,
    cache_dir: str,
    tickers: list[str],
    history_start: str,
) -> None:
    """Download and cache full history for every ticker."""
    client = PolygonClient(api_key=api_key)
    cache = CacheManager(cache_dir=cache_dir)

    start = date.fromisoformat(history_start)
    end = date.today()
    chunks = _year_chunks(start, end)
    total_chunks = len(chunks)

    for ticker in tickers:
        logger.info("=== Seeding %s (%s to %s, %d chunks) ===", ticker, start, end, total_chunks)

        for idx, (chunk_start, chunk_end) in enumerate(chunks, 1):
            logger.info(
                "  [%d/%d] %s: %s to %s",
                idx,
                total_chunks,
                ticker,
                chunk_start,
                chunk_end,
            )
            try:
                df = client.get_daily_bars(ticker, chunk_start, chunk_end)
            except PolygonAPIError as exc:
                logger.error("  API error for %s chunk %d: %s", ticker, idx, exc)
                continue

            if df.empty:
                logger.info("  No data returned for this chunk")
                continue

            cache.append(ticker, df)
            logger.info("  Cached %d bars (through %s)", len(df), df["date"].max().date())

        # Final validation.
        if cache.validate(ticker):
            total = len(cache.read(ticker))
            logger.info("=== %s seeding complete: %d total bars, validation passed ===", ticker, total)
        else:
            logger.warning("=== %s seeding complete but validation FAILED ===", ticker)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = _parse_args()

    if not args.api_key:
        logger.error(
            "No API key provided. Pass --api-key or set WL_POLYGON_API_KEY env var."
        )
        sys.exit(1)

    cfg = WhiteLightConfig.load()
    cache_dir = args.cache_dir or cfg.data.cache_dir
    tickers = args.tickers or cfg.data.tickers
    start_date = args.start_date or cfg.data.history_start_date

    logger.info("Seed configuration:")
    logger.info("  Cache dir   : %s", cache_dir)
    logger.info("  Tickers     : %s", tickers)
    logger.info("  Start date  : %s", start_date)

    seed(
        api_key=args.api_key,
        cache_dir=cache_dir,
        tickers=tickers,
        history_start=start_date,
    )

    logger.info("Seed complete.")


if __name__ == "__main__":
    main()
