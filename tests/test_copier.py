from decimal import Decimal
from uuid import uuid4

import pytest

from ts_local.copier import TradeCopier
from ts_local.models import CopyGroup, ExecutionMode, FollowerConfig, OrderType, Side, TradeEvent


class NeverExecutor:
    async def execute(self, account_id, event):
        raise AssertionError("dry-run must not execute orders")


@pytest.mark.asyncio
async def test_multiplier_scales_follower_quantity_without_execution():
    leader = uuid4()
    follower = uuid4()
    group = CopyGroup(
        uuid4(), "test", leader,
        (FollowerConfig(follower, Decimal("1.5")),),
    )
    event = TradeEvent(uuid4(), leader, "MNQ", Side.BUY, 2, OrderType.MARKET)

    results = await TradeCopier(NeverExecutor(), ExecutionMode.DRY_RUN).copy(group, event)

    assert len(results) == 1
    assert results[0].quantity == 3
    assert results[0].skipped is True
    assert results[0].reason == "dry run"
