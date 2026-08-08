from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from .models import TradeEvent, TradovateAccount


class LeaderEventSource(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...


class FollowerExecutor(Protocol):
    async def execute(self, account_id: UUID, event: TradeEvent) -> str: ...


class AccountProvider(Protocol):
    async def accounts(self) -> list[TradovateAccount]: ...


@dataclass(frozen=True)
class BrokerCapabilities:
    can_discover_accounts: bool = False
    can_stream_orders: bool = False
    can_submit_orders: bool = False
    supports_demo: bool = False
    requires_api_entitlement: bool = True


class BrokerAdapter(Protocol):
    name: str
    capabilities: BrokerCapabilities


class LocalBridgeExecutor:
    """Safe local bridge stub.

    This is intentionally non-executing for now. It gives TS-Local a clean
    place to integrate a legitimate local/session transport later without
    coupling the copier engine to Tradovate's public API.
    """

    async def execute(self, account_id: UUID, event: TradeEvent) -> str:
        raise RuntimeError(
            "Local bridge execution is not configured. No broker order was submitted."
        )
