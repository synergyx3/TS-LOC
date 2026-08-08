from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from .models import OrderType, Side, TradeEvent, TradovateAccount


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


class NinjaTraderOifExecutor:
    """Write orders to NinjaTrader 8's documented local OIF interface.

    The bridge is deliberately disarmed by default. Even when TS-Local is put
    in LIVE mode, callers must explicitly construct this executor with
    ``armed=True`` before a file can appear in NinjaTrader's incoming folder.
    """

    def __init__(
        self,
        incoming_directory: Path,
        account_names: dict[UUID, str],
        *,
        armed: bool = False,
    ) -> None:
        self.incoming_directory = incoming_directory
        self.account_names = dict(account_names)
        self.armed = armed

    async def execute(self, account_id: UUID, event: TradeEvent) -> str:
        if not self.armed:
            raise RuntimeError(
                "NinjaTrader OIF bridge is disarmed. No order instruction was written."
            )
        account_name = self.account_names.get(account_id)
        if not account_name:
            raise ValueError(f"No NinjaTrader account mapping for {account_id}")
        if not self.incoming_directory.is_dir():
            raise RuntimeError("NinjaTrader OIF incoming directory does not exist")
        if event.quantity <= 0:
            raise ValueError("NinjaTrader OIF quantity must be positive")
        if event.order_type is OrderType.STOP_LIMIT:
            raise ValueError(
                "StopLimit orders require distinct limit and stop prices; "
                "the current trade event cannot represent both"
            )

        order_id = f"tslocal-{uuid4().hex}"
        instruction = self._place_instruction(account_name, event, order_id)
        temporary = self.incoming_directory / f".{order_id}.tmp"
        destination = self.incoming_directory / f"oif-{order_id}.txt"
        temporary.write_text(instruction, encoding="ascii", newline="")
        temporary.replace(destination)
        return order_id

    @staticmethod
    def _place_instruction(account_name: str, event: TradeEvent, order_id: str) -> str:
        for label, value in (
            ("account name", account_name),
            ("instrument", event.symbol),
            ("order id", order_id),
        ):
            if not value or ";" in value or "\n" in value or "\r" in value:
                raise ValueError(f"Invalid NinjaTrader OIF {label}")

        order_types = {
            OrderType.MARKET: "MARKET",
            OrderType.LIMIT: "LIMIT",
            OrderType.STOP: "STOPMARKET",
        }
        action = "BUY" if event.side is Side.BUY else "SELL"
        limit_price = ""
        stop_price = ""
        if event.order_type is OrderType.LIMIT:
            limit_price = _oif_price(event.price, event.order_type)
        if event.order_type is OrderType.STOP:
            stop_price = _oif_price(event.price, event.order_type)

        fields = (
            "PLACE",
            account_name,
            event.symbol,
            action,
            str(event.quantity),
            order_types[event.order_type],
            limit_price,
            stop_price,
            "DAY",
            "",
            order_id,
            "",
            "",
        )
        return ";".join(fields)


def _oif_price(price: Decimal | None, order_type: OrderType) -> str:
    if price is None:
        raise ValueError(f"{order_type.value} orders require a price")
    return format(price, "f")
