"""No-op alert provider -- logs alerts but does not send them anywhere."""

from __future__ import annotations

import logging
from typing import Optional

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)


class NoopAlertProvider(AlertProvider):
    """Logs alerts locally without sending to any external service."""

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        logger.info("ALERT [%s] %s: %s", priority, title or "WhiteLight", message)
        return True
