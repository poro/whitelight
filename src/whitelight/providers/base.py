"""Abstract base classes for all pluggable provider backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from whitelight.models import (
    AccountInfo,
    BrokerageID,
    OrderResult,
    OrderRequest,
    Position,
    Side,
    OrderType,
)


# ---- Exceptions ----


class BrokerageError(Exception):
    """Base for all brokerage-layer errors."""

    def __init__(self, message: str, brokerage: str = "", retriable: bool = False):
        super().__init__(message)
        self.brokerage = brokerage
        self.retriable = retriable


class BrokerageConnectionError(BrokerageError):
    """Cannot reach the broker API or gateway."""

    def __init__(self, message: str, brokerage: str = ""):
        super().__init__(message, brokerage=brokerage, retriable=True)


class AuthenticationError(BrokerageError):
    """API key rejected or IB Gateway login failed."""

    def __init__(self, message: str, brokerage: str = ""):
        super().__init__(message, brokerage=brokerage, retriable=False)


class OrderRejectedError(BrokerageError):
    """Broker explicitly rejected the order."""

    def __init__(self, message: str, brokerage: str = "", order_id: str = ""):
        super().__init__(message, brokerage=brokerage, retriable=False)
        self.order_id = order_id


class InsufficientFundsError(OrderRejectedError):
    """Not enough buying power for the order."""

    pass


class GatewayRestartError(BrokerageError):
    """IB Gateway is restarting or not yet ready."""

    def __init__(self, message: str):
        super().__init__(message, brokerage="ibkr", retriable=True)


# ---- Provider ABCs ----


class SecretsProvider(ABC):
    """Retrieves sensitive credentials at runtime.

    Credentials are held in memory only; never written to disk in plaintext.
    Keys follow a namespace convention:
        'alpaca/api_key', 'alpaca/api_secret',
        'ibkr/username', 'ibkr/password',
        'polygon/api_key',
        'telegram/bot_token', 'telegram/chat_id'
    """

    @abstractmethod
    def get_secret(self, key: str) -> str:
        """Retrieve a single secret by logical key name."""
        ...

    @abstractmethod
    def get_secret_json(self, key: str) -> dict:
        """Retrieve a JSON-encoded secret."""
        ...


class AlertProvider(ABC):
    """Sends push notifications to the operator's mobile device."""

    @abstractmethod
    async def send_alert(
        self,
        message: str,
        priority: str = "normal",
        title: Optional[str] = None,
    ) -> bool:
        """Send a single alert. Returns True if delivery succeeded."""
        ...


class BrokerageClient(ABC):
    """Unified interface for reading account state and placing orders."""

    @property
    @abstractmethod
    def brokerage_id(self) -> BrokerageID:
        ...

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the brokerage."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the brokerage connection."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...

    @abstractmethod
    async def get_account(self) -> AccountInfo:
        """Return account equity, cash, buying power."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return current open positions."""
        ...

    @abstractmethod
    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: Side,
        order_type: OrderType = OrderType.MARKET,
    ) -> OrderResult:
        """Submit an order. Returns result with initial status."""
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> OrderResult:
        """Poll the status of a previously submitted order."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True if acknowledged."""
        ...

    @abstractmethod
    async def is_market_open(self) -> bool:
        ...

    async def health_check(self) -> bool:
        """Quick connectivity test. Default tries get_account()."""
        try:
            await self.get_account()
            return True
        except Exception:
            return False
