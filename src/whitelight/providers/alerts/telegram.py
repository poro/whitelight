"""Telegram Bot API alert provider."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)


class TelegramAlertProvider(AlertProvider):
    """Sends alerts via Telegram Bot API."""

    API_URL = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, bot_token: str, chat_id: str):
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        text = f"*{title}*\n{message}" if title else message
        if priority == "critical":
            text = f"🚨 CRITICAL 🚨\n{text}"

        url = self.API_URL.format(token=self._bot_token)
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                logger.info("Telegram alert sent: %s", title or message[:50])
                return True
        except Exception as e:
            logger.error("Telegram alert failed: %s", e)
            return False
