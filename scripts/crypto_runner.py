#!/usr/bin/env python3
"""Standalone crypto runner script for cron execution.

Usage:
    python scripts/crypto_runner.py --dry-run          # Simulate trades
    python scripts/crypto_runner.py                     # Execute live (paper)
    python scripts/crypto_runner.py --symbols BTC ETH   # Specific symbols
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from decimal import Decimal
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from whitelight.crypto.runner import CryptoRunner


def main():
    parser = argparse.ArgumentParser(description="White Light Crypto Runner")
    parser.add_argument("--dry-run", action="store_true", help="Simulate trades without executing")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH"], help="Crypto symbols to trade")
    parser.add_argument("--allocation", type=float, default=10000, help="Total dollar allocation (default: $10,000)")
    parser.add_argument("--target-vol", type=float, default=0.15, help="Target annualized volatility (default: 0.15)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    api_key = os.environ.get("APCA_API_KEY_ID", "PKWHF33UCU4A2MQL2Z4HULXDDB")
    secret_key = os.environ.get("APCA_API_SECRET_KEY", "5SpkREVYospTNHhJmx9HwUrckBMUNi9fSKZ59dBWh3Kg")
    paper = os.environ.get("APCA_PAPER", "true").lower() == "true"

    # Map short names to full symbols
    symbol_map = {"BTC": "BTC/USD", "ETH": "ETH/USD"}
    symbols = [symbol_map.get(s, s) for s in args.symbols]

    runner = CryptoRunner(
        api_key=api_key,
        secret_key=secret_key,
        paper=paper,
        symbols=symbols,
        base_allocation=Decimal(str(args.allocation)),
        target_vol=args.target_vol,
    )

    mode = "DRY RUN" if args.dry_run else "LIVE (paper)" if paper else "LIVE"
    print(f"\n🔮 White Light Crypto Runner — {mode}")
    print(f"   Symbols: {', '.join(symbols)}")
    print(f"   Allocation: ${args.allocation:,.2f}")
    print(f"   Target Vol: {args.target_vol:.0%}\n")

    results = runner.run(dry_run=args.dry_run)
    runner.print_summary(results)


if __name__ == "__main__":
    main()
