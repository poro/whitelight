"""Telemetry reporter: dispatches formatted alerts through the alert provider."""

from __future__ import annotations

import logging

from whitelight.execution.executor import ExecutionResult
from whitelight.models import OrderResult, TargetAllocation
from whitelight.providers.base import AlertProvider
from whitelight.telemetry.formatters import (
    format_execution_summary,
    format_order_filled,
    format_order_placed,
    format_target_allocation,
)

logger = logging.getLogger(__name__)


class TelemetryReporter:
    """Sends structured alerts at each stage of the trading pipeline."""

    def __init__(self, alert_provider: AlertProvider):
        self._alerts = alert_provider

    async def report_pipeline_start(self) -> None:
        await self._alerts.send_alert(
            "White Light pipeline starting.", title="Pipeline Start"
        )

    async def report_target_allocation(self, target: TargetAllocation) -> None:
        msg = format_target_allocation(target)
        await self._alerts.send_alert(msg, title="Target Allocation")
        logger.info("Target allocation: %s", msg)

    async def report_order_placed(self, order: OrderResult) -> None:
        msg = format_order_placed(order)
        await self._alerts.send_alert(msg, title="Order Placed")
        logger.info("Order placed: %s", msg)

    async def report_order_filled(self, order: OrderResult) -> None:
        msg = format_order_filled(order)
        await self._alerts.send_alert(msg, title="Order Filled")
        logger.info("Order filled: %s", msg)

    async def report_execution_results(self, result: ExecutionResult) -> None:
        msg = format_execution_summary(result.orders, result.failures)
        priority = "critical" if result.failures else "normal"
        await self._alerts.send_alert(msg, priority=priority, title="Execution Summary")
        logger.info("Execution summary: %s", msg)

    async def report_error(self, error: Exception) -> None:
        msg = f"CRITICAL ERROR: {error}"
        await self._alerts.send_alert(msg, priority="critical", title="Pipeline Failure")
        logger.error("Pipeline error reported: %s", error)

    async def report_pipeline_complete(self) -> None:
        await self._alerts.send_alert(
            "White Light pipeline complete.", title="Pipeline Complete"
        )
