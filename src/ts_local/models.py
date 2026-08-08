from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4


class Side(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"
    STOP = "Stop"
    STOP_LIMIT = "StopLimit"


class ExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    LIVE = "live"


@dataclass(frozen=True)
class TradovateAccount:
    id: UUID
    login_id: UUID
    account_id: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class TradovateLogin:
    id: UUID
    label: str
    username: str
    environment: str = "live"
    accounts: tuple[TradovateAccount, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FollowerConfig:
    account_id: UUID
    multiplier: Decimal = Decimal("1")
    enabled: bool = True

    def scaled_quantity(self, leader_quantity: int) -> int:
        if leader_quantity < 0:
            raise ValueError("leader_quantity cannot be negative")
        quantity = int(Decimal(leader_quantity) * self.multiplier)
        if leader_quantity and self.multiplier > 0 and quantity < 1:
            quantity = 1
        return quantity


@dataclass(frozen=True)
class CopyGroup:
    id: UUID
    name: str
    leader_account_id: UUID
    followers: tuple[FollowerConfig, ...]
    enabled: bool = True


@dataclass(frozen=True)
class TradeEvent:
    event_id: UUID
    account_id: UUID
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    price: Decimal | None = None
    source_order_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class JournalEntry:
    id: UUID
    trade_event_id: UUID
    account_id: UUID
    symbol: str
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def new_login(label: str, username: str, environment: str = "live") -> TradovateLogin:
    return TradovateLogin(uuid4(), label, username, environment)
