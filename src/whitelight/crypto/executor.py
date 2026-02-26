"""Crypto trade executor via Alpaca."""

from __future__ import annotations

import logging
from decimal import Decimal

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError

logger = logging.getLogger(__name__)


class CryptoExecutor:
    """Execute crypto trades on Alpaca.

    Alpaca supports fractional crypto trading, so we use notional (dollar)
    orders rather than share quantities.
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
        )

    def get_account_equity(self) -> Decimal:
        """Return account equity."""
        acct = self._client.get_account()
        return Decimal(str(acct.equity))

    def get_position(self, symbol: str) -> dict | None:
        """Get current position for a crypto symbol, or None."""
        try:
            pos = self._client.get_open_position(symbol.replace("/", ""))
            return {
                "symbol": pos.symbol,
                "qty": Decimal(str(pos.qty)),
                "market_value": Decimal(str(pos.market_value)),
                "avg_entry_price": Decimal(str(pos.avg_entry_price)),
                "unrealized_pl": Decimal(str(pos.unrealized_pl)),
            }
        except APIError:
            return None

    def execute_target_allocation(
        self,
        symbol: str,
        target_alloc: float,
        base_allocation: Decimal,
        dry_run: bool = False,
    ) -> dict:
        """Rebalance a crypto position to the target allocation.

        Parameters
        ----------
        symbol : str
            e.g. "BTC/USD" or "ETH/USD"
        target_alloc : float
            Target fraction of base_allocation (0.0 to 1.0)
        base_allocation : Decimal
            Dollar amount allocated to this crypto asset
        dry_run : bool
            If True, log but don't execute

        Returns
        -------
        dict with keys: action, symbol, notional, order_id (if executed)
        """
        target_value = float(base_allocation) * target_alloc
        current_pos = self.get_position(symbol)
        current_value = float(current_pos["market_value"]) if current_pos else 0.0

        delta = target_value - current_value
        min_order = 1.0  # $1 minimum for crypto

        result = {
            "symbol": symbol,
            "target_alloc": target_alloc,
            "target_value": round(target_value, 2),
            "current_value": round(current_value, 2),
            "delta": round(delta, 2),
        }

        if abs(delta) < min_order:
            result["action"] = "hold"
            logger.info("[%s] Hold — delta $%.2f below minimum", symbol, abs(delta))
            return result

        side = OrderSide.BUY if delta > 0 else OrderSide.SELL
        notional = round(abs(delta), 2)

        if dry_run:
            result["action"] = f"DRY_RUN_{side.value.upper()}"
            result["notional"] = notional
            logger.info("[DRY RUN] %s %s $%.2f of %s", side.value, symbol, notional, symbol)
            return result

        try:
            # Alpaca crypto uses the symbol without slash for trading
            trading_symbol = symbol.replace("/", "")
            order = self._client.submit_order(
                MarketOrderRequest(
                    symbol=trading_symbol,
                    notional=notional,
                    side=side,
                    time_in_force=TimeInForce.GTC,
                )
            )
            result["action"] = side.value
            result["notional"] = notional
            result["order_id"] = str(order.id)
            logger.info("Executed %s $%.2f of %s → order %s", side.value, notional, symbol, order.id)
        except APIError as e:
            result["action"] = "error"
            result["error"] = str(e)
            logger.error("Order failed for %s: %s", symbol, e)

        return result
