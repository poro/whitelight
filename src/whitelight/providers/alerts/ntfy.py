"""Ntfy.sh alert provider."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)

PRIORITY_MAP = {
    "normal": "default",
    "high": "high",
    "critical": "urgent",
}


class NtfyAlertProvider(AlertProvider):
    """Sends alerts via ntfy.sh (self-hosted or public)."""

    def __init__(self, topic: str, server_url: str = "https://ntfy.sh"):
        self._url = f"{server_url.rstrip('/')}/{topic}"

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        headers: dict[str, str] = {
            "Priority": PRIORITY_MAP.get(priority, "default"),
        }
        if title:
            headers["Title"] = title

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self._url, content=message, headers=headers, timeout=10
                )
                resp.raise_for_status()
                logger.info("Ntfy alert sent: %s", title or message[:50])
                return True
        except Exception as e:
            logger.error("Ntfy alert failed: %s", e)
            return False
