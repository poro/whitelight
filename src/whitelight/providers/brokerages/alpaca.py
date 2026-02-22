"""Alpaca brokerage integration using the official alpaca-py SDK."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide as AlpacaOrderSide, TimeInForce
from alpaca.common.exceptions import APIError

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    OrderResult,
    OrderStatus,
    Position,
    Side,
    OrderType,
)
from whitelight.providers.base import (
    BrokerageClient,
    BrokerageConnectionError,
    AuthenticationError,
    InsufficientFundsError,
    OrderRejectedError,
)

logger = logging.getLogger(__name__)

_SIDE_MAP = {
    Side.BUY: AlpacaOrderSide.BUY,
    Side.SELL: AlpacaOrderSide.SELL,
}

_STATUS_MAP = {
    "new": OrderStatus.ACCEPTED,
    "accepted": OrderStatus.ACCEPTED,
    "pending_new": OrderStatus.PENDING,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "done_for_day": OrderStatus.FILLED,
    "canceled": OrderStatus.CANCELLED,
    "expired": OrderStatus.EXPIRED,
    "replaced": OrderStatus.ACCEPTED,
    "pending_cancel": OrderStatus.ACCEPTED,
    "pending_replace": OrderStatus.ACCEPTED,
    "rejected": OrderStatus.REJECTED,
}


class AlpacaClient(BrokerageClient):
    """Alpaca brokerage client using alpaca-py SDK.

    The `paper` flag switches between paper and live endpoints automatically.
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        self._api_key = api_key
        self._secret_key = secret_key
        self._paper = paper
        self._client: Optional[TradingClient] = None

    @property
    def brokerage_id(self) -> BrokerageID:
        return BrokerageID.ALPACA

    @property
    def is_paper(self) -> bool:
        return self._paper

    async def connect(self) -> None:
        logger.info("Connecting to Alpaca (paper=%s)", self._paper)
        try:
            self._client = TradingClient(
                api_key=self._api_key,
                secret_key=self._secret_key,
                paper=self._paper,
            )
            self._client.get_account()
            logger.info("Alpaca connection validated")
        except APIError as e:
            err = str(e).lower()
            if "forbidden" in err or "not authorized" in err or "unauthorized" in err:
                raise AuthenticationError(f"Alpaca auth failed: {e}", brokerage="alpaca")
            raise BrokerageConnectionError(f"Alpaca connection failed: {e}", brokerage="alpaca")
        except Exception as e:
            raise BrokerageConnectionError(f"Alpaca connection failed: {e}", brokerage="alpaca")

    async def disconnect(self) -> None:
        logger.info("Disconnecting Alpaca client")
        self._client = None

    def is_connected(self) -> bool:
        return self._client is not None

    def _require_client(self) -> TradingClient:
        if self._client is None:
            raise BrokerageConnectionError("AlpacaClient not connected", brokerage="alpaca")
        return self._client

    async def get_account(self) -> AccountInfo:
        client = self._require_client()
        try:
            acct = client.get_account()
            return AccountInfo(
                brokerage=BrokerageID.ALPACA,
                cash=Decimal(str(acct.cash)),
                buying_power=Decimal(str(acct.buying_power)),
                equity=Decimal(str(acct.equity)),
            )
        except APIError as e:
            raise BrokerageConnectionError(f"Alpaca get_account failed: {e}", brokerage="alpaca")

    async def get_positions(self) -> list[Position]:
        client = self._require_client()
        try:
            raw = client.get_all_positions()
            return [
                Position(
                    brokerage=BrokerageID.ALPACA,
                    symbol=p.symbol,
                    qty=Decimal(str(p.qty)),
                    market_value=Decimal(str(p.market_value)),
                    avg_cost=Decimal(str(p.avg_entry_price)),
                    unrealized_pnl=Decimal(str(p.unrealized_pl)),
                )
                for p in raw
            ]
        except APIError as e:
            raise BrokerageConnectionError(
                f"Alpaca get_positions failed: {e}", brokerage="alpaca"
            )

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderResult:
        client = self._require_client()
        logger.info("Alpaca submit_order: %s %d %s", side.value, qty, symbol)

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=_SIDE_MAP[side],
            time_in_force=TimeInForce.DAY,
        )

        try:
            raw = client.submit_order(order_data=request)
            result = self._normalize_order(raw)
            logger.info("Alpaca order submitted: id=%s status=%s", result.order_id, result.status)
            return result
        except APIError as e:
            err = str(e).lower()
            if "insufficient" in err or "buying power" in err:
                raise InsufficientFundsError(f"Alpaca insufficient funds: {e}", brokerage="alpaca")
            raise OrderRejectedError(f"Alpaca order rejected: {e}", brokerage="alpaca")

    async def get_order_status(self, order_id: str) -> OrderResult:
        client = self._require_client()
        try:
            raw = client.get_order_by_id(order_id=order_id)
            return self._normalize_order(raw)
        except APIError as e:
            raise BrokerageConnectionError(
                f"Alpaca get_order_status failed: {e}", brokerage="alpaca"
            )

    async def cancel_order(self, order_id: str) -> bool:
        client = self._require_client()
        try:
            client.cancel_order_by_id(order_id=order_id)
            logger.info("Alpaca order cancelled: %s", order_id)
            return True
        except APIError:
            logger.warning("Alpaca cancel_order failed for %s", order_id)
            return False

    async def is_market_open(self) -> bool:
        client = self._require_client()
        try:
            clock = client.get_clock()
            return clock.is_open
        except APIError:
            return False

    async def health_check(self) -> bool:
        try:
            client = self._require_client()
            client.get_clock()
            return True
        except Exception:
            return False

    def _normalize_order(self, raw) -> OrderResult:  # type: ignore[no-untyped-def]
        return OrderResult(
            order_id=str(raw.id),
            brokerage=BrokerageID.ALPACA,
            symbol=raw.symbol,
            side=Side.BUY if str(raw.side) == "buy" else Side.SELL,
            requested_qty=int(raw.qty) if raw.qty else 0,
            filled_qty=Decimal(str(raw.filled_qty)) if raw.filled_qty else Decimal("0"),
            filled_avg_price=(
                Decimal(str(raw.filled_avg_price)) if raw.filled_avg_price else None
            ),
            status=_STATUS_MAP.get(str(raw.status), OrderStatus.PENDING),
            submitted_at=raw.submitted_at,
            filled_at=raw.filled_at,
            raw_response={"alpaca_order_id": str(raw.id)},
        )
