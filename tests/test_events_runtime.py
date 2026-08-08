from decimal import Decimal
from uuid import uuid4

import pytest

from ts_local.copier import CopySafetyPolicy, TradeCopier
from ts_local.events import AccountBinding, TradovateEventNormalizer
from ts_local.models import CopyGroup, ExecutionMode, FollowerConfig
from ts_local.runtime import CopierRuntime


class NeverExecutor:
    async def execute(self, account_id, event):
        raise AssertionError("dry-run must never execute")


def order_message(account_id: int = 100, order_id: int = 1, qty: int = 2):
    return {
        "e": "props",
        "d": {
            "entityType": "order",
            "eventType": "Created",
            "entity": {
                "id": order_id,
                "accountId": account_id,
                "action": "Buy",
                "orderQty": qty,
                "orderType": "Market",
                "symbol": "MNQZ6",
            },
        },
    }


def test_normalizer_is_idempotent_for_same_order_id():
    leader = uuid4()
    normalizer = TradovateEventNormalizer([AccountBinding(100, leader)])

    first = normalizer.normalize(order_message())
    second = normalizer.normalize(order_message())

    assert first is not None
    assert first.account_id == leader
    assert first.symbol == "MNQZ6"
    assert second is None


@pytest.mark.asyncio
async def test_runtime_routes_leader_event_to_dry_run_followers_once():
    leader = uuid4()
    follower = uuid4()
    group = CopyGroup(
        uuid4(),
        "main",
        leader,
        (FollowerConfig(follower, Decimal("1.5")),),
    )
    runtime = CopierRuntime(
        group=group,
        copier=TradeCopier(NeverExecutor(), ExecutionMode.DRY_RUN),
        normalizer=TradovateEventNormalizer([AccountBinding(100, leader)]),
    )

    await runtime.handle_socket_message(order_message(qty=2))
    await runtime.handle_socket_message(order_message(qty=2))

    assert runtime.stats.leader_events == 1
    assert runtime.stats.skipped_orders == 1
    assert runtime.stats.copied_orders == 0


@pytest.mark.asyncio
async def test_safety_cap_blocks_oversized_scaled_order():
    leader = uuid4()
    follower = uuid4()
    group = CopyGroup(
        uuid4(),
        "main",
        leader,
        (FollowerConfig(follower, Decimal("10")),),
    )
    normalizer = TradovateEventNormalizer([AccountBinding(100, leader)])
    event = normalizer.normalize(order_message(qty=3))
    assert event is not None

    results = await TradeCopier(
        NeverExecutor(),
        ExecutionMode.DRY_RUN,
        CopySafetyPolicy(max_quantity_per_follower=20),
    ).copy(group, event)

    assert results[0].skipped is True
    assert results[0].quantity == 30
    assert "safety cap" in results[0].reason
