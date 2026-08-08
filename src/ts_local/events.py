from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from .models import OrderType, Side, TradeEvent


class EventNormalizationError(ValueError):
    pass


@dataclass(frozen=True)
class AccountBinding:
    tradovate_account_id: int
    local_account_id: UUID


class TradovateEventNormalizer:
    """Convert Tradovate websocket order entities into TS-Local trade events.

    This intentionally only accepts newly-created orders. Updates, fills and
    position events are handled separately so a leader action cannot be copied
    twice just because Tradovate emits several lifecycle events for it.
    """

    def __init__(self, account_bindings: list[AccountBinding]) -> None:
        self._accounts = {
            binding.tradovate_account_id: binding.local_account_id
            for binding in account_bindings
        }
        self._seen_order_ids: set[str] = set()

    def normalize(self, message: dict[str, Any]) -> TradeEvent | None:
        if message.get("e") != "props":
            return None

        payload = message.get("d")
        if not isinstance(payload, dict):
            return None
        if payload.get("entityType") != "order":
            return None
        if payload.get("eventType") != "Created":
            return None

        entity = payload.get("entity")
        if not isinstance(entity, dict):
            return None

        raw_order_id = entity.get("id")
        if raw_order_id is None:
            raise EventNormalizationError("order event is missing id")
        order_id = str(raw_order_id)
        if order_id in self._seen_order_ids:
            return None

        raw_account_id = entity.get("accountId")
        if raw_account_id is None:
            raise EventNormalizationError("order event is missing accountId")
        local_account_id = self._accounts.get(int(raw_account_id))
        if local_account_id is None:
            return None

        quantity = int(entity.get("orderQty") or entity.get("qty") or 0)
        if quantity <= 0:
            raise EventNormalizationError("order quantity must be positive")

        action = str(entity.get("action", ""))
        try:
            side = Side(action)
        except ValueError as exc:
            raise EventNormalizationError(f"unsupported order action: {action!r}") from exc

        raw_type = str(entity.get("orderType") or "Market")
        try:
            order_type = OrderType(raw_type)
        except ValueError as exc:
            raise EventNormalizationError(f"unsupported order type: {raw_type!r}") from exc

        # Contract symbols are resolved by the stream coordinator before this
        # normalizer is called. A descriptive fallback keeps malformed events
        # visible in logs without inventing a tradeable symbol.
        symbol = str(entity.get("symbol") or entity.get("contractName") or "")
        if not symbol:
            raise EventNormalizationError("order event is missing resolved symbol")

        price = entity.get("price")
        if price is None:
            price = entity.get("stopPrice")

        self._seen_order_ids.add(order_id)
        return TradeEvent(
            event_id=uuid4(),
            account_id=local_account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=Decimal(str(price)) if price is not None else None,
            source_order_id=order_id,
        )
