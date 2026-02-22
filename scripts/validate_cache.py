#!/usr/bin/env python3
"""Validate the integrity of all cached Parquet files.

Usage:
    python scripts/validate_cache.py
    python scripts/validate_cache.py --cache-dir ./data --tickers NDX TQQQ SQQQ
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "src"))

from whitelight.config import WhiteLightConfig
from whitelight.data.cache import CacheManager

logger = logging.getLogger("whitelight.validate_cache")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Validate local Parquet cache files")
    parser.add_argument("--cache-dir", default=None, help="Override cache directory")
    parser.add_argument("--tickers", nargs="+", default=None, help="Tickers to validate")
    args = parser.parse_args()

    cfg = WhiteLightConfig.load()
    cache_dir = args.cache_dir or cfg.data.cache_dir
    tickers = args.tickers or cfg.data.tickers

    cache = CacheManager(cache_dir=cache_dir)

    all_passed = True
    for ticker in tickers:
        df = cache.read(ticker)
        if df.empty:
            logger.warning("[%s] NO DATA - cache file missing or empty", ticker)
            all_passed = False
            continue

        last = cache.last_date(ticker)
        valid = cache.validate(ticker)
        status = "PASS" if valid else "FAIL"

        logger.info(
            "[%s] %s - %d rows, first=%s, last=%s",
            ticker,
            status,
            len(df),
            df.index.min().date() if hasattr(df.index.min(), "date") else df.index.min(),
            last,
        )

        if not valid:
            all_passed = False

    if all_passed:
        logger.info("All tickers passed validation.")
    else:
        logger.error("One or more tickers FAILED validation.")
        sys.exit(1)


if __name__ == "__main__":
    main()
