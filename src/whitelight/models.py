"""Shared domain models for the White Light trading system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


# ---- Enums ----


class Ticker(str, Enum):
    NDX = "NDX"
    TQQQ = "TQQQ"
    SQQQ = "SQQQ"


class SignalStrength(int, Enum):
    """Discrete signal levels from each sub-strategy."""

    STRONG_BEAR = -2
    BEAR = -1
    NEUTRAL = 0
    BULL = 1
    STRONG_BULL = 2


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FAILED = "failed"


class BrokerageID(str, Enum):
    ALPACA = "alpaca"
    IBKR = "ibkr"
    PAPER = "paper"


# ---- Data Models ----


@dataclass(frozen=True)
class OHLCVBar:
    """Single day of price data."""

    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


# ---- Strategy Models ----


@dataclass(frozen=True)
class SubStrategySignal:
    """Output of a single sub-strategy."""

    strategy_name: str
    signal: SignalStrength
    weight: float
    raw_score: float  # continuous signal in [-1.0, +1.0]
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TargetAllocation:
    """Final output of the strategy engine. Percentages must sum to ~1.0."""

    tqqq_pct: Decimal
    sqqq_pct: Decimal
    cash_pct: Decimal
    signals: list[SubStrategySignal] = field(default_factory=list)
    composite_score: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        total = self.tqqq_pct + self.sqqq_pct + self.cash_pct
        if abs(total - Decimal("1.0")) > Decimal("0.01"):
            raise ValueError(f"Allocation must sum to ~1.0, got {total}")


# ---- Brokerage Models ----


@dataclass(frozen=True)
class AccountInfo:
    """Brokerage account snapshot."""

    brokerage: BrokerageID
    equity: Decimal
    cash: Decimal
    buying_power: Decimal
    currency: str = "USD"
    as_of: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class Position:
    """A single open position at a brokerage."""

    brokerage: BrokerageID
    symbol: str
    qty: Decimal  # positive = long
    market_value: Decimal
    avg_cost: Decimal
    unrealized_pnl: Decimal = Decimal("0")
    as_of: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class Fill:
    """A single fill on an order."""

    fill_id: str
    order_id: str
    symbol: str
    qty: Decimal
    price: Decimal
    side: Side
    filled_at: datetime


@dataclass(frozen=True)
class OrderRequest:
    """Intent to place an order."""

    symbol: str
    qty: int
    side: Side
    order_type: OrderType = OrderType.MARKET
    rationale: str = ""


@dataclass(frozen=True)
class OrderResult:
    """Result of an order submission."""

    order_id: str
    brokerage: BrokerageID
    symbol: str
    side: Side
    requested_qty: int
    filled_qty: Decimal = Decimal("0")
    filled_avg_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    fills: list[Fill] = field(default_factory=list)
    error_message: Optional[str] = None
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    raw_response: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Aggregated view across ALL connected brokerages."""

    accounts: list[AccountInfo]
    positions: list[Position]
    total_equity: Decimal
    total_cash: Decimal
    positions_by_symbol: dict[str, Decimal]  # symbol -> total qty
    as_of: datetime = field(default_factory=datetime.utcnow)
