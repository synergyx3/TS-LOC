from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .copier import CopyResult, TradeCopier
from .events import EventNormalizationError, TradovateEventNormalizer
from .models import CopyGroup, TradeEvent


@dataclass
class RuntimeStats:
    leader_events: int = 0
    copied_orders: int = 0
    skipped_orders: int = 0
    malformed_events: int = 0


@dataclass
class CopierRuntime:
    group: CopyGroup
    copier: TradeCopier
    normalizer: TradovateEventNormalizer
    on_result: Callable[[TradeEvent, list[CopyResult]], Awaitable[None]] | None = None
    stats: RuntimeStats = field(default_factory=RuntimeStats)

    async def handle_socket_message(self, message: dict) -> None:
        try:
            event = self.normalizer.normalize(message)
        except EventNormalizationError:
            self.stats.malformed_events += 1
            return

        if event is None:
            return
        if event.account_id != self.group.leader_account_id:
            return

        self.stats.leader_events += 1
        results = await self.copier.copy(self.group, event)
        self.stats.copied_orders += sum(1 for result in results if not result.skipped)
        self.stats.skipped_orders += sum(1 for result in results if result.skipped)

        if self.on_result is not None:
            await self.on_result(event, results)
