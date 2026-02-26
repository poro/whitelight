"""Crypto runner — main loop: fetch → signal → execute."""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

from whitelight.crypto.data import CryptoDataClient
from whitelight.crypto.strategy import CryptoStrategy
from whitelight.crypto.executor import CryptoExecutor

logger = logging.getLogger(__name__)


class CryptoRunner:
    """Orchestrates the crypto trading pipeline.

    Parameters
    ----------
    api_key, secret_key : str
        Alpaca API credentials.
    paper : bool
        Use paper trading endpoint.
    symbols : list[str]
        Crypto symbols to trade (e.g. ["BTC/USD", "ETH/USD"]).
    base_allocation : Decimal
        Total dollar allocation across all crypto assets.
    target_vol : float
        Target annualized volatility for position sizing.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        paper: bool = True,
        symbols: Optional[list[str]] = None,
        base_allocation: Decimal = Decimal("10000"),
        target_vol: float = 0.15,
    ):
        self.symbols = symbols or ["BTC/USD", "ETH/USD"]
        self.base_allocation = base_allocation
        self.per_symbol_allocation = base_allocation / len(self.symbols)

        self.data_client = CryptoDataClient(api_key, secret_key)
        self.strategy = CryptoStrategy(target_vol=target_vol)
        self.executor = CryptoExecutor(api_key, secret_key, paper=paper)

    def run(self, dry_run: bool = False) -> list[dict]:
        """Execute one cycle: fetch data → compute signals → trade.

        Returns list of execution results per symbol.
        """
        results = []

        for symbol in self.symbols:
            logger.info("Processing %s...", symbol)

            # 1. Fetch data
            try:
                df = self.data_client.get_bars(symbol, timeframe="4Hour")
                if len(df) < 400:
                    logger.warning("Insufficient data for %s: %d bars (need 400+)", symbol, len(df))
                    results.append({"symbol": symbol, "action": "skip", "reason": "insufficient_data"})
                    continue
            except Exception as e:
                logger.error("Data fetch failed for %s: %s", symbol, e)
                results.append({"symbol": symbol, "action": "error", "error": str(e)})
                continue

            # 2. Compute signal
            try:
                signal = self.strategy.evaluate(df, symbol=symbol)
            except Exception as e:
                logger.error("Strategy failed for %s: %s", symbol, e)
                results.append({"symbol": symbol, "action": "error", "error": str(e)})
                continue

            # 3. Execute
            try:
                result = self.executor.execute_target_allocation(
                    symbol=symbol,
                    target_alloc=signal.target_allocation,
                    base_allocation=self.per_symbol_allocation,
                    dry_run=dry_run,
                )
                result["composite_score"] = signal.composite_score
                result["realized_vol"] = signal.realized_vol
                result["signal_details"] = signal.signal_details
                results.append(result)
            except Exception as e:
                logger.error("Execution failed for %s: %s", symbol, e)
                results.append({"symbol": symbol, "action": "error", "error": str(e)})

        return results

    def print_summary(self, results: list[dict]) -> None:
        """Print a human-readable summary of the run."""
        print("\n" + "=" * 60)
        print("  WHITE LIGHT CRYPTO RUNNER SUMMARY")
        print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
        print("=" * 60)

        for r in results:
            symbol = r.get("symbol", "?")
            action = r.get("action", "?")
            print(f"\n  {symbol}:")
            print(f"    Action:          {action}")

            if "composite_score" in r:
                print(f"    Composite Score: {r['composite_score']:+.4f}")
            if "realized_vol" in r:
                print(f"    Realized Vol:    {r['realized_vol']:.2%}")
            if "target_alloc" in r:
                print(f"    Target Alloc:    {r['target_alloc']:.2%}")
            if "target_value" in r:
                print(f"    Target Value:    ${r['target_value']:,.2f}")
            if "current_value" in r:
                print(f"    Current Value:   ${r['current_value']:,.2f}")
            if "delta" in r:
                print(f"    Delta:           ${r['delta']:+,.2f}")
            if "notional" in r:
                print(f"    Order Notional:  ${r['notional']:,.2f}")
            if "order_id" in r:
                print(f"    Order ID:        {r['order_id']}")
            if "error" in r:
                print(f"    Error:           {r['error']}")
            if "reason" in r:
                print(f"    Reason:          {r['reason']}")

        print("\n" + "=" * 60)
