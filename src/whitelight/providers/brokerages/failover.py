"""Failover brokerage client wrapping primary + secondary with retry logic."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    OrderResult,
    OrderStatus,
    Position,
    PortfolioSnapshot,
    Side,
    OrderType,
)
from whitelight.providers.base import (
    AlertProvider,
    BrokerageClient,
    BrokerageConnectionError,
    BrokerageError,
)

logger = logging.getLogger(__name__)


class FailoverBrokerageClient(BrokerageClient):
    """Wraps primary and secondary brokerages with automatic failover.

    Order routing: try primary with retries -> failover to secondary.
    Portfolio reads: aggregate across both brokerages.
    """

    def __init__(
        self,
        primary: BrokerageClient,
        secondary: BrokerageClient,
        alert_provider: AlertProvider,
        max_retries: int = 5,
        retry_backoff_base: float = 2.0,
        retry_backoff_max: float = 60.0,
        market_close_buffer_seconds: int = 60,
        market_close_time: Optional[datetime] = None,
    ):
        self._primary = primary
        self._secondary = secondary
        self._alert_provider = alert_provider
        self._max_retries = max_retries
        self._retry_backoff_base = retry_backoff_base
        self._retry_backoff_max = retry_backoff_max
        self._market_close_buffer = market_close_buffer_seconds
        self._market_close_time = market_close_time
        self._primary_healthy = False
        self._secondary_healthy = False

    @property
    def brokerage_id(self) -> BrokerageID:
        return self._primary.brokerage_id

    @property
    def is_paper(self) -> bool:
        return self._primary.is_paper

    async def connect(self) -> None:
        """Connect to both brokerages. At least one must succeed."""
        try:
            await self._primary.connect()
            self._primary_healthy = await self._primary.health_check()
        except BrokerageError as e:
            logger.error("Primary brokerage connection failed: %s", e)
            self._primary_healthy = False
            await self._alert_provider.send_alert(
                f"Primary brokerage unavailable: {e}", priority="high", title="Failover Warning"
            )

        try:
            await self._secondary.connect()
            self._secondary_healthy = await self._secondary.health_check()
        except BrokerageError as e:
            logger.error("Secondary brokerage connection failed: %s", e)
            self._secondary_healthy = False
            await self._alert_provider.send_alert(
                f"Secondary brokerage unavailable: {e}", priority="high", title="Failover Warning"
            )

        if not self._primary_healthy and not self._secondary_healthy:
            raise BrokerageConnectionError(
                "Both brokerages unreachable", brokerage="all"
            )

        logger.info(
            "Failover client initialized: primary=%s (healthy=%s), secondary=%s (healthy=%s)",
            self._primary.brokerage_id.value, self._primary_healthy,
            self._secondary.brokerage_id.value, self._secondary_healthy,
        )

    async def disconnect(self) -> None:
        for client in [self._primary, self._secondary]:
            try:
                await client.disconnect()
            except Exception as e:
                logger.warning("Error disconnecting %s: %s", client.brokerage_id.value, e)

    def is_connected(self) -> bool:
        return self._primary_healthy or self._secondary_healthy

    async def get_account(self) -> AccountInfo:
        """Get account from the primary healthy brokerage."""
        if self._primary_healthy:
            try:
                return await self._primary.get_account()
            except BrokerageError:
                pass
        if self._secondary_healthy:
            return await self._secondary.get_account()
        raise BrokerageConnectionError("No healthy brokerage", brokerage="all")

    async def get_positions(self) -> list[Position]:
        """Get positions from ALL healthy brokerages."""
        positions: list[Position] = []
        for client, healthy in [
            (self._primary, self._primary_healthy),
            (self._secondary, self._secondary_healthy),
        ]:
            if not healthy:
                continue
            try:
                positions.extend(await client.get_positions())
            except BrokerageError as e:
                logger.warning("Failed to get positions from %s: %s", client.brokerage_id.value, e)
        return positions

    async def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Aggregated snapshot across all connected brokerages."""
        accounts: list[AccountInfo] = []
        positions: list[Position] = []

        for client, healthy in [
            (self._primary, self._primary_healthy),
            (self._secondary, self._secondary_healthy),
        ]:
            if not healthy:
                continue
            try:
                accounts.append(await client.get_account())
                positions.extend(await client.get_positions())
            except BrokerageError as e:
                logger.warning("Failed to read from %s: %s", client.brokerage_id.value, e)

        total_equity = sum(a.equity for a in accounts)
        total_cash = sum(a.cash for a in accounts)

        positions_by_symbol: dict[str, Decimal] = {}
        for p in positions:
            positions_by_symbol[p.symbol] = (
                positions_by_symbol.get(p.symbol, Decimal("0")) + p.qty
            )

        return PortfolioSnapshot(
            accounts=accounts,
            positions=positions,
            total_equity=total_equity,
            total_cash=total_cash,
            positions_by_symbol=positions_by_symbol,
        )

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderResult:
        """Submit with retry on primary, failover to secondary."""
        if self._primary_healthy:
            try:
                return await self._submit_with_retry(
                    self._primary, symbol, qty, side, order_type
                )
            except BrokerageError as e:
                logger.warning("Primary exhausted retries: %s. Failing over.", e)
                await self._alert_provider.send_alert(
                    f"Failover: {self._primary.brokerage_id.value} -> "
                    f"{self._secondary.brokerage_id.value}. Reason: {e}",
                    priority="high",
                    title="Brokerage Failover",
                )

        if self._secondary_healthy:
            try:
                return await self._submit_with_retry(
                    self._secondary, symbol, qty, side, order_type
                )
            except BrokerageError as e:
                await self._alert_provider.send_alert(
                    f"CRITICAL: Both brokerages failed. Last error: {e}",
                    priority="critical",
                    title="Execution Failure",
                )
                raise

        raise BrokerageConnectionError("No healthy brokerage for order", brokerage="all")

    async def _submit_with_retry(
        self,
        client: BrokerageClient,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType,
    ) -> OrderResult:
        delay = self._retry_backoff_base
        last_error: Optional[BrokerageError] = None

        for attempt in range(1, self._max_retries + 1):
            if self._is_past_deadline():
                raise last_error or BrokerageConnectionError(
                    "Retry deadline reached", brokerage=client.brokerage_id.value
                )

            try:
                logger.info(
                    "Order attempt %d/%d on %s: %s %d %s",
                    attempt, self._max_retries, client.brokerage_id.value,
                    side.value, qty, symbol,
                )
                return await client.submit_order(symbol, qty, side, order_type)
            except BrokerageError as e:
                last_error = e
                logger.warning(
                    "Attempt %d/%d failed: %s (retriable=%s)",
                    attempt, self._max_retries, e, e.retriable,
                )
                if not e.retriable:
                    raise
                if attempt < self._max_retries:
                    logger.info("Backing off %.1fs", delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self._retry_backoff_max)

        raise last_error or BrokerageConnectionError(
            f"All {self._max_retries} attempts failed", brokerage=client.brokerage_id.value
        )

    async def get_order_status(self, order_id: str) -> OrderResult:
        # Try primary first, then secondary
        for client in [self._primary, self._secondary]:
            try:
                return await client.get_order_status(order_id)
            except BrokerageError:
                continue
        raise BrokerageConnectionError(f"Order {order_id} not found", brokerage="all")

    async def cancel_order(self, order_id: str) -> bool:
        for client in [self._primary, self._secondary]:
            try:
                if await client.cancel_order(order_id):
                    return True
            except BrokerageError:
                continue
        return False

    async def is_market_open(self) -> bool:
        if self._primary_healthy:
            try:
                return await self._primary.is_market_open()
            except BrokerageError:
                pass
        if self._secondary_healthy:
            try:
                return await self._secondary.is_market_open()
            except BrokerageError:
                pass
        return False

    async def wait_for_fill(self, order: OrderResult, timeout_seconds: int = 120) -> OrderResult:
        """Poll order until terminal state or timeout."""
        terminal = {
            OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
            OrderStatus.EXPIRED, OrderStatus.FAILED,
        }
        deadline = time.monotonic() + timeout_seconds
        current = order

        while time.monotonic() < deadline:
            try:
                current = await self.get_order_status(order.order_id)
                if current.status in terminal:
                    return current
            except BrokerageError as e:
                logger.warning("Error polling order %s: %s", order.order_id, e)
            await asyncio.sleep(2)

        logger.warning("Order %s timed out after %ds", order.order_id, timeout_seconds)
        return current

    def _is_past_deadline(self) -> bool:
        if self._market_close_time is None:
            return False
        buffer = timedelta(seconds=self._market_close_buffer)
        return datetime.utcnow() >= (self._market_close_time - buffer)
