"""AWS SNS alert provider."""

from __future__ import annotations

import logging
from typing import Optional

import boto3

from whitelight.providers.base import AlertProvider

logger = logging.getLogger(__name__)


class SNSAlertProvider(AlertProvider):
    """Sends alerts via AWS SNS."""

    def __init__(self, topic_arn: str, region: str = "us-east-1"):
        self._client = boto3.client("sns", region_name=region)
        self._topic_arn = topic_arn

    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        subject = title or "White Light Alert"
        if priority == "critical":
            subject = f"CRITICAL: {subject}"

        try:
            self._client.publish(
                TopicArn=self._topic_arn,
                Subject=subject[:100],  # SNS subject max 100 chars
                Message=message,
            )
            logger.info("SNS alert sent: %s", subject)
            return True
        except Exception as e:
            logger.error("SNS alert failed: %s", e)
            return False
