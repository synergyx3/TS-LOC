from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .models import CopyGroup, ExecutionMode, TradeEvent


class OrderExecutor(Protocol):
    async def execute(self, account_id, event: TradeEvent) -> str: ...


@dataclass(frozen=True)
class CopyResult:
    account_id: object
    quantity: int
    order_id: str | None
    skipped: bool = False
    reason: str | None = None


class TradeCopier:
    """Transforms leader events into independently executable follower orders."""

    def __init__(self, executor: OrderExecutor, mode: ExecutionMode = ExecutionMode.DRY_RUN):
        self.executor = executor
        self.mode = mode

    async def copy(self, group: CopyGroup, event: TradeEvent) -> list[CopyResult]:
        if not group.enabled:
            return []
        if event.account_id != group.leader_account_id:
            return []

        results: list[CopyResult] = []
        for follower in group.followers:
            if not follower.enabled:
                results.append(CopyResult(follower.account_id, 0, None, True, "disabled"))
                continue

            quantity = follower.scaled_quantity(event.quantity)
            if quantity <= 0:
                results.append(CopyResult(follower.account_id, 0, None, True, "zero quantity"))
                continue

            follower_event = TradeEvent(
                event_id=event.event_id,
                account_id=follower.account_id,
                symbol=event.symbol,
                side=event.side,
                quantity=quantity,
                order_type=event.order_type,
                price=event.price,
                source_order_id=event.source_order_id,
                occurred_at=event.occurred_at,
            )

            if self.mode is ExecutionMode.DRY_RUN:
                results.append(CopyResult(follower.account_id, quantity, None, True, "dry run"))
            else:
                order_id = await self.executor.execute(follower.account_id, follower_event)
                results.append(CopyResult(follower.account_id, quantity, order_id))
        return results
