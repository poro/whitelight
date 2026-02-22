"""In-memory paper brokerage client for testing."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    OrderResult,
    OrderStatus,
    Position,
    Side,
    OrderType,
)
from whitelight.providers.base import BrokerageClient

logger = logging.getLogger(__name__)


class PaperBrokerageClient(BrokerageClient):
    """In-memory mock brokerage for unit tests and dry runs."""

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000"),
        positions: Optional[list[Position]] = None,
    ):
        self._cash = initial_cash
        self._equity = initial_cash
        self._positions: list[Position] = positions or []
        self._orders: dict[str, OrderResult] = {}
        self._connected = False

    @property
    def brokerage_id(self) -> BrokerageID:
        return BrokerageID.PAPER

    @property
    def is_paper(self) -> bool:
        return True

    async def connect(self) -> None:
        self._connected = True
        logger.info("Paper brokerage connected")

    async def disconnect(self) -> None:
        self._connected = False
        logger.info("Paper brokerage disconnected")

    def is_connected(self) -> bool:
        return self._connected

    async def get_account(self) -> AccountInfo:
        return AccountInfo(
            brokerage=BrokerageID.PAPER,
            equity=self._equity,
            cash=self._cash,
            buying_power=self._cash,
        )

    async def get_positions(self) -> list[Position]:
        return list(self._positions)

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderResult:
        order_id = str(uuid.uuid4())[:8]
        result = OrderResult(
            order_id=order_id,
            brokerage=BrokerageID.PAPER,
            symbol=symbol,
            side=side,
            requested_qty=qty,
            filled_qty=Decimal(str(qty)),
            filled_avg_price=Decimal("50.00"),  # mock price
            status=OrderStatus.FILLED,
            submitted_at=datetime.utcnow(),
            filled_at=datetime.utcnow(),
        )
        self._orders[order_id] = result
        logger.info("Paper order filled: %s %d %s", side.value, qty, symbol)
        return result

    async def get_order_status(self, order_id: str) -> OrderResult:
        if order_id not in self._orders:
            raise KeyError(f"Order not found: {order_id}")
        return self._orders[order_id]

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def is_market_open(self) -> bool:
        return True
