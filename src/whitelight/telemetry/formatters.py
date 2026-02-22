"""Message formatting for alerts and telemetry."""

from __future__ import annotations

from decimal import Decimal

from whitelight.models import OrderResult, TargetAllocation


def format_target_allocation(target: TargetAllocation) -> str:
    """Format target allocation for alert message."""
    lines = [
        f"TQQQ: {float(target.tqqq_pct)*100:.1f}%",
        f"SQQQ: {float(target.sqqq_pct)*100:.1f}%",
        f"Cash: {float(target.cash_pct)*100:.1f}%",
    ]
    if target.composite_score != 0.0:
        lines.append(f"Composite Score: {target.composite_score:+.3f}")

    if target.signals:
        lines.append("")
        lines.append("Sub-strategy signals:")
        for sig in target.signals:
            lines.append(f"  {sig.strategy_name}: {sig.signal.name} ({sig.raw_score:+.2f})")

    return "\n".join(lines)


def format_order_placed(result: OrderResult) -> str:
    """Format order placement notification."""
    return (
        f"{result.side.value.upper()} {result.requested_qty} {result.symbol} @ market "
        f"via {result.brokerage.value} (id: {result.order_id})"
    )


def format_order_filled(result: OrderResult) -> str:
    """Format order fill confirmation."""
    price_str = f"@ ${float(result.filled_avg_price):.2f}" if result.filled_avg_price else ""
    return (
        f"FILLED: {result.side.value.upper()} {result.filled_qty} {result.symbol} "
        f"{price_str} via {result.brokerage.value}"
    )


def format_execution_summary(
    orders: list[OrderResult],
    failures: list[str],
) -> str:
    """Format end-of-session execution summary."""
    lines = []

    if orders:
        filled = [o for o in orders if o.status.value == "filled"]
        lines.append(f"Orders: {len(filled)}/{len(orders)} filled")
        for o in orders:
            price = f"@ ${float(o.filled_avg_price):.2f}" if o.filled_avg_price else ""
            lines.append(
                f"  {o.side.value.upper()} {o.filled_qty}/{o.requested_qty} "
                f"{o.symbol} {price} [{o.status.value}]"
            )
    else:
        lines.append("No orders executed.")

    if failures:
        lines.append("")
        lines.append("Failures:")
        for f in failures:
            lines.append(f"  {f}")

    return "\n".join(lines)
