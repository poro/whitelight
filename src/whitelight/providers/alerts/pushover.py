"""Pushover alert provider."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)

PRIORITY_MAP = {
    "normal": 0,
    "high": 1,
    "critical": 2,  # Requires acknowledgement
}


class PushoverAlertProvider(AlertProvider):
    """Sends alerts via Pushover API."""

    API_URL = "https://api.pushover.net/1/messages.json"

    def __init__(self, api_token: str, user_key: str):
        self._api_token = api_token
        self._user_key = user_key

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        payload: dict = {
            "token": self._api_token,
            "user": self._user_key,
            "message": message,
            "priority": PRIORITY_MAP.get(priority, 0),
        }
        if title:
            payload["title"] = title
        # Critical priority requires retry/expire params
        if priority == "critical":
            payload["retry"] = 60
            payload["expire"] = 600

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(self.API_URL, data=payload, timeout=10)
                resp.raise_for_status()
                logger.info("Pushover alert sent: %s", title or message[:50])
                return True
        except Exception as e:
            logger.error("Pushover alert failed: %s", e)
            return False
