from decimal import Decimal
from uuid import uuid4

import pytest

from ts_local.adapters import NinjaTraderOifExecutor
from ts_local.models import OrderType, Side, TradeEvent


def event(account_id, order_type=OrderType.MARKET, price=None):
    return TradeEvent(uuid4(), account_id, "MNQ 09-26", Side.BUY, 2, order_type, price)


@pytest.mark.asyncio
async def test_oif_bridge_is_disarmed_by_default(tmp_path):
    account_id = uuid4()
    executor = NinjaTraderOifExecutor(tmp_path, {account_id: "Sim101"})

    with pytest.raises(RuntimeError, match="disarmed"):
        await executor.execute(account_id, event(account_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_armed_oif_bridge_writes_atomic_place_instruction(tmp_path):
    account_id = uuid4()
    executor = NinjaTraderOifExecutor(tmp_path, {account_id: "Sim101"}, armed=True)

    order_id = await executor.execute(
        account_id,
        event(account_id, OrderType.STOP, Decimal("20123.25")),
    )

    files = list(tmp_path.glob("oif-*.txt"))
    assert len(files) == 1
    assert list(tmp_path.glob(".*.tmp")) == []
    assert files[0].read_text(encoding="ascii") == (
        f"PLACE;Sim101;MNQ 09-26;BUY;2;STOPMARKET;;20123.25;DAY;;{order_id};;"
    )


@pytest.mark.asyncio
async def test_oif_bridge_rejects_unmapped_account_without_writing(tmp_path):
    executor = NinjaTraderOifExecutor(tmp_path, {}, armed=True)

    with pytest.raises(ValueError, match="No NinjaTrader account mapping"):
        await executor.execute(uuid4(), event(uuid4()))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_oif_bridge_requires_price_for_limit_order(tmp_path):
    account_id = uuid4()
    executor = NinjaTraderOifExecutor(tmp_path, {account_id: "Sim101"}, armed=True)

    with pytest.raises(ValueError, match="require a price"):
        await executor.execute(account_id, event(account_id, OrderType.LIMIT))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_oif_bridge_rejects_delimiter_in_mapped_account(tmp_path):
    account_id = uuid4()
    executor = NinjaTraderOifExecutor(tmp_path, {account_id: "Sim101;PLACE"}, armed=True)

    with pytest.raises(ValueError, match="Invalid NinjaTrader OIF account name"):
        await executor.execute(account_id, event(account_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_oif_bridge_rejects_stop_limit_until_two_prices_are_modeled(tmp_path):
    account_id = uuid4()
    executor = NinjaTraderOifExecutor(tmp_path, {account_id: "Sim101"}, armed=True)

    with pytest.raises(ValueError, match="distinct limit and stop prices"):
        await executor.execute(
            account_id,
            event(account_id, OrderType.STOP_LIMIT, Decimal("20123.25")),
        )

    assert list(tmp_path.iterdir()) == []
