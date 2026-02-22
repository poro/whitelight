"""Interactive Brokers integration using ib_async."""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Optional

from ib_async import IB, Stock, MarketOrder, Trade

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    Fill,
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
    GatewayRestartError,
    InsufficientFundsError,
    OrderRejectedError,
)

logger = logging.getLogger(__name__)

PAPER_PORT = 7497
LIVE_PORT = 7496

_IB_STATUS_MAP = {
    "PendingSubmit": OrderStatus.PENDING,
    "PendingCancel": OrderStatus.ACCEPTED,
    "PreSubmitted": OrderStatus.ACCEPTED,
    "Submitted": OrderStatus.ACCEPTED,
    "ApiCancelled": OrderStatus.CANCELLED,
    "Cancelled": OrderStatus.CANCELLED,
    "Filled": OrderStatus.FILLED,
    "Inactive": OrderStatus.REJECTED,
}


class IBKRClient(BrokerageClient):
    """Interactive Brokers client via IB Gateway.

    Requires IB Gateway running locally. Paper: port 7497, Live: port 7496.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        client_id: int = 1,
        paper: bool = True,
        connect_timeout: int = 10,
        max_reconnect_attempts: int = 3,
    ):
        self._host = host
        self._port = port if port is not None else (PAPER_PORT if paper else LIVE_PORT)
        self._client_id = client_id
        self._paper = paper
        self._connect_timeout = connect_timeout
        self._max_reconnect_attempts = max_reconnect_attempts
        self._ib: Optional[IB] = None

    @property
    def brokerage_id(self) -> BrokerageID:
        return BrokerageID.IBKR

    @property
    def is_paper(self) -> bool:
        return self._paper

    async def connect(self) -> None:
        logger.info(
            "Connecting to IB Gateway at %s:%d (client_id=%d, paper=%s)",
            self._host, self._port, self._client_id, self._paper,
        )
        self._ib = IB()
        try:
            await self._ib.connectAsync(
                host=self._host,
                port=self._port,
                clientId=self._client_id,
                timeout=self._connect_timeout,
            )
            logger.info("IB Gateway connection established")
        except ConnectionRefusedError:
            self._ib = None
            raise GatewayRestartError(
                f"IB Gateway not running at {self._host}:{self._port}"
            )
        except Exception as e:
            self._ib = None
            err = str(e).lower()
            if "login" in err or "auth" in err:
                raise AuthenticationError(f"IB auth failed: {e}", brokerage="ibkr")
            raise BrokerageConnectionError(f"IB connection failed: {e}", brokerage="ibkr")

    async def disconnect(self) -> None:
        if self._ib and self._ib.isConnected():
            logger.info("Disconnecting from IB Gateway")
            self._ib.disconnect()
        self._ib = None

    def is_connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    def _require_connection(self) -> IB:
        if self._ib is None:
            raise BrokerageConnectionError("IBKRClient not connected", brokerage="ibkr")
        if not self._ib.isConnected():
            raise BrokerageConnectionError("IB Gateway connection lost", brokerage="ibkr")
        return self._ib

    async def get_account(self) -> AccountInfo:
        ib = self._require_connection()
        try:
            summary = ib.accountSummary()
            values = {item.tag: item.value for item in summary}
            return AccountInfo(
                brokerage=BrokerageID.IBKR,
                cash=Decimal(values.get("TotalCashValue", "0")),
                buying_power=Decimal(values.get("BuyingPower", "0")),
                equity=Decimal(values.get("NetLiquidation", "0")),
            )
        except Exception as e:
            raise BrokerageConnectionError(f"IB get_account failed: {e}", brokerage="ibkr")

    async def get_positions(self) -> list[Position]:
        ib = self._require_connection()
        try:
            raw = ib.positions()
            result = []
            for p in raw:
                qty = Decimal(str(p.position))
                avg_cost = Decimal(str(p.avgCost))
                result.append(
                    Position(
                        brokerage=BrokerageID.IBKR,
                        symbol=p.contract.symbol,
                        qty=qty,
                        market_value=qty * avg_cost,
                        avg_cost=avg_cost,
                    )
                )
            return result
        except Exception as e:
            raise BrokerageConnectionError(f"IB get_positions failed: {e}", brokerage="ibkr")

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderResult:
        ib = self._require_connection()
        logger.info("IB submit_order: %s %d %s", side.value, qty, symbol)

        contract = Stock(symbol, "SMART", "USD")
        qualified = ib.qualifyContracts(contract)
        if not qualified:
            raise OrderRejectedError(
                f"IB could not qualify contract for {symbol}", brokerage="ibkr"
            )

        action = "BUY" if side == Side.BUY else "SELL"
        ib_order = MarketOrder(action=action, totalQuantity=qty)
        ib_order.tif = "DAY"

        try:
            trade: Trade = ib.placeOrder(contract, ib_order)
            await asyncio.sleep(1)  # Let IB event loop process

            result = self._normalize_trade(trade, symbol, side, qty)
            logger.info("IB order submitted: id=%s status=%s", result.order_id, result.status)
            return result
        except Exception as e:
            err = str(e).lower()
            if "insufficient" in err or "margin" in err:
                raise InsufficientFundsError(f"IB insufficient funds: {e}", brokerage="ibkr")
            raise OrderRejectedError(f"IB order failed: {e}", brokerage="ibkr")

    async def get_order_status(self, order_id: str) -> OrderResult:
        ib = self._require_connection()
        try:
            target_id = int(order_id)
            for trade in ib.trades():
                if trade.order.orderId == target_id:
                    symbol = trade.contract.symbol
                    side = Side.BUY if trade.order.action == "BUY" else Side.SELL
                    return self._normalize_trade(
                        trade, symbol, side, int(trade.order.totalQuantity)
                    )
            raise BrokerageConnectionError(f"IB order {order_id} not found", brokerage="ibkr")
        except ValueError:
            raise BrokerageConnectionError(
                f"Invalid IB order ID: {order_id}", brokerage="ibkr"
            )

    async def cancel_order(self, order_id: str) -> bool:
        ib = self._require_connection()
        try:
            target_id = int(order_id)
            for trade in ib.openTrades():
                if trade.order.orderId == target_id:
                    ib.cancelOrder(trade.order)
                    await asyncio.sleep(1)
                    logger.info("IB order cancelled: %s", order_id)
                    return True
            return False
        except Exception as e:
            logger.warning("IB cancel_order failed for %s: %s", order_id, e)
            return False

    async def is_market_open(self) -> bool:
        return True  # Delegated to router/scheduler

    async def health_check(self) -> bool:
        try:
            ib = self._require_connection()
            ib.reqCurrentTime()
            return True
        except Exception:
            return False

    def _normalize_trade(
        self, trade: Trade, symbol: str, side: Side, requested_qty: int
    ) -> OrderResult:
        ib_status = trade.orderStatus.status
        filled_qty = Decimal(str(trade.orderStatus.filled))
        avg_price = (
            Decimal(str(trade.orderStatus.avgFillPrice))
            if trade.orderStatus.avgFillPrice
            else None
        )

        fills = []
        for f in trade.fills:
            fills.append(
                Fill(
                    fill_id=str(f.execution.execId),
                    order_id=str(trade.order.orderId),
                    symbol=symbol,
                    qty=Decimal(str(f.execution.shares)),
                    price=Decimal(str(f.execution.price)),
                    side=side,
                    filled_at=f.execution.time,
                )
            )

        return OrderResult(
            order_id=str(trade.order.orderId),
            brokerage=BrokerageID.IBKR,
            symbol=symbol,
            side=side,
            requested_qty=requested_qty,
            filled_qty=filled_qty,
            filled_avg_price=avg_price,
            status=_IB_STATUS_MAP.get(ib_status, OrderStatus.PENDING),
            fills=fills,
            raw_response={"ib_order_id": trade.order.orderId, "ib_status": ib_status},
        )
