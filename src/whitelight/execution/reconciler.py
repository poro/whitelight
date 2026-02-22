"""Position reconciliation utilities."""

from __future__ import annotations

import logging
from decimal import Decimal

from whitelight.models import PortfolioSnapshot, TargetAllocation

logger = logging.getLogger(__name__)


def check_rebalance_needed(
    snapshot: PortfolioSnapshot,
    target: TargetAllocation,
    threshold: float = 0.05,
) -> bool:
    """Check if rebalancing is needed based on minimum change threshold.

    Returns True if the allocation shift exceeds the threshold for any instrument.
    This enforces the ~1 trade per 16 days frequency target.
    """
    if snapshot.total_equity <= 0:
        return False

    for symbol, target_pct in [
        ("TQQQ", target.tqqq_pct),
        ("SQQQ", target.sqqq_pct),
    ]:
        current_value = snapshot.positions_by_symbol.get(symbol, Decimal("0"))
        # Approximate current allocation
        if snapshot.total_equity > 0:
            current_pct = current_value / snapshot.total_equity
        else:
            current_pct = Decimal("0")

        delta_pct = abs(float(target_pct) - float(current_pct))
        if delta_pct >= threshold:
            logger.info(
                "Rebalance needed: %s current=%.1f%% target=%.1f%% delta=%.1f%%",
                symbol,
                float(current_pct) * 100,
                float(target_pct) * 100,
                delta_pct * 100,
            )
            return True

    logger.info("No rebalance needed - all instruments within %.1f%% threshold", threshold * 100)
    return False
