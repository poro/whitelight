"""Order execution engine: translates target allocations into concrete orders."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Optional

from whitelight.models import (
    OrderRequest,
    OrderResult,
    OrderStatus,
    PortfolioSnapshot,
    Side,
    TargetAllocation,
)
from whitelight.providers.base import AlertProvider, BrokerageError

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Summary of execution outcomes for the session."""

    snapshot: PortfolioSnapshot
    target: TargetAllocation
    intents: list[OrderRequest]
    orders: list[OrderResult]
    all_filled: bool
    partial_fills: list[OrderResult]
    failures: list[str]


class OrderExecutor:
    """Translates target allocations into concrete orders and executes them.

    Workflow:
    1. Snapshot portfolio across all connected brokerages.
    2. Compute target share counts from total equity and live prices.
    3. Compute deltas (current vs target shares).
    4. Execute sells first (frees buying power), then buys.
    5. Wait for fills and report results.
    """

    def __init__(
        self,
        brokerage,  # FailoverBrokerageClient
        get_live_price: Callable[[str], Decimal],
        alert_provider: AlertProvider,
        min_order_value: Decimal = Decimal("10.0"),
    ):
        self._brokerage = brokerage
        self._get_live_price = get_live_price
        self._alert_provider = alert_provider
        self._min_order_value = min_order_value

    async def execute(self, target: TargetAllocation) -> ExecutionResult:
        """Full execution pipeline: snapshot -> deltas -> orders -> confirm."""
        # Step 1: Read current portfolio
        snapshot = await self._brokerage.get_portfolio_snapshot()
        logger.info(
            "Execution starting. Equity: %s, Positions: %s",
            snapshot.total_equity,
            snapshot.positions_by_symbol,
        )

        # Step 2: Compute order intents
        intents = self._compute_intents(snapshot, target)

        if not intents:
            logger.info("No orders needed - portfolio already at target")
            await self._alert_provider.send_alert(
                "No rebalancing needed today.", title="Execution"
            )
            return ExecutionResult(
                snapshot=snapshot,
                target=target,
                intents=[],
                orders=[],
                all_filled=True,
                partial_fills=[],
                failures=[],
            )

        # Step 3: Execute sells first, then buys
        sell_intents = [i for i in intents if i.side == Side.SELL]
        buy_intents = [i for i in intents if i.side == Side.BUY]

        orders: list[OrderResult] = []
        failures: list[str] = []

        # Execute sells
        for intent in sell_intents:
            result = await self._execute_single(intent)
            if result:
                orders.append(result)
            else:
                failures.append(f"SELL {intent.qty} {intent.symbol} failed")

        # Wait for sell fills before buying
        for i, order in enumerate(orders):
            orders[i] = await self._brokerage.wait_for_fill(order, timeout_seconds=60)

        # Execute buys
        for intent in buy_intents:
            result = await self._execute_single(intent)
            if result:
                orders.append(result)
            else:
                failures.append(f"BUY {intent.qty} {intent.symbol} failed")

        # Wait for all remaining fills
        terminal = {
            OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED,
            OrderStatus.EXPIRED, OrderStatus.FAILED,
        }
        for i, order in enumerate(orders):
            if order.status not in terminal:
                orders[i] = await self._brokerage.wait_for_fill(order, timeout_seconds=120)

        # Step 4: Classify results
        partial_fills = [
            o for o in orders
            if o.status == OrderStatus.PARTIALLY_FILLED
            or (o.filled_qty > Decimal("0") and o.status != OrderStatus.FILLED)
        ]
        all_filled = all(o.status == OrderStatus.FILLED for o in orders) and not failures

        # Step 5: Alert
        if all_filled:
            await self._alert_provider.send_alert(
                f"All {len(orders)} orders filled successfully.", title="Execution Complete"
            )
        elif failures:
            await self._alert_provider.send_alert(
                f"Execution failures: {failures}", priority="critical", title="Execution Error"
            )
        elif partial_fills:
            await self._alert_provider.send_alert(
                f"Partial fills on {len(partial_fills)} orders.",
                priority="high",
                title="Execution Warning",
            )

        return ExecutionResult(
            snapshot=snapshot,
            target=target,
            intents=intents,
            orders=orders,
            all_filled=all_filled,
            partial_fills=partial_fills,
            failures=failures,
        )

    def _compute_intents(
        self,
        snapshot: PortfolioSnapshot,
        target: TargetAllocation,
    ) -> list[OrderRequest]:
        """Compute share deltas to reach target allocation."""
        total_equity = snapshot.total_equity
        if total_equity <= 0:
            logger.error("Total equity is zero or negative: %s", total_equity)
            return []

        intents: list[OrderRequest] = []

        for symbol, target_pct in [
            ("TQQQ", target.tqqq_pct),
            ("SQQQ", target.sqqq_pct),
            ("BIL", target.cash_pct),  # Invest "cash" portion in T-bill ETF
        ]:
            try:
                price = self._get_live_price(symbol)
            except (ValueError, KeyError) as e:
                logger.warning("No price for %s, skipping: %s", symbol, e)
                continue
            if price <= 0:
                logger.error("Invalid price for %s: %s", symbol, price)
                continue

            target_value = total_equity * target_pct
            target_shares = int(
                (target_value / price).to_integral_value(rounding=ROUND_DOWN)
            )
            current_shares = int(
                snapshot.positions_by_symbol.get(symbol, Decimal("0"))
            )
            delta = target_shares - current_shares

            if delta == 0:
                continue

            # Skip tiny orders
            order_value = abs(delta) * price
            if order_value < self._min_order_value:
                logger.info(
                    "Skipping %s order: value $%s below minimum $%s",
                    symbol, order_value, self._min_order_value,
                )
                continue

            side = Side.BUY if delta > 0 else Side.SELL
            rationale = (
                f"Target {float(target_pct)*100:.1f}% = ${float(target_value):.2f} = "
                f"{target_shares} shares @ ${float(price):.2f}. "
                f"Currently {current_shares}. Delta: {delta:+d}."
            )

            intents.append(
                OrderRequest(
                    symbol=symbol,
                    qty=abs(delta),
                    side=side,
                    rationale=rationale,
                )
            )
            logger.info("Intent: %s %d %s - %s", side.value, abs(delta), symbol, rationale)

        return intents

    async def _execute_single(self, intent: OrderRequest) -> Optional[OrderResult]:
        """Submit a single order. Returns None on total failure."""
        try:
            result = await self._brokerage.submit_order(
                symbol=intent.symbol,
                qty=intent.qty,
                side=intent.side,
            )
            await self._alert_provider.send_alert(
                f"Order placed: {intent.side.value.upper()} {intent.qty} {intent.symbol} "
                f"via {result.brokerage.value} (id={result.order_id})",
                title="Order Placed",
            )
            return result
        except BrokerageError as e:
            logger.error("Failed to execute %s %d %s: %s", intent.side.value, intent.qty, intent.symbol, e)
            await self._alert_provider.send_alert(
                f"Order FAILED: {intent.side.value.upper()} {intent.qty} {intent.symbol}: {e}",
                priority="critical",
                title="Order Failed",
            )
            return None
