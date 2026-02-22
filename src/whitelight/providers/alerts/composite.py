"""Composite alert provider that fans out to multiple backends."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)


class CompositeAlertProvider(AlertProvider):
    """Sends alerts to multiple providers simultaneously."""

    def __init__(self, providers: list[AlertProvider]):
        self._providers = providers

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        tasks = [p.send_alert(message, priority, title) for p in self._providers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        successes = sum(1 for r in results if r is True)
        if successes == 0:
            logger.error("All alert providers failed")
            return False
        if successes < len(self._providers):
            logger.warning(
                "Alert partially delivered: %d/%d providers succeeded",
                successes,
                len(self._providers),
            )
        return True
