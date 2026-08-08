from decimal import Decimal
from uuid import uuid4

from ts_local.copier import CopyResult
from ts_local.journal import ExecutionJournal
from ts_local.models import OrderType, Side, TradeEvent


def test_execution_journal_records_copy_result(tmp_path):
    leader = uuid4()
    follower = uuid4()
    event = TradeEvent(
        event_id=uuid4(),
        account_id=leader,
        symbol="MNQZ6",
        side=Side.BUY,
        quantity=2,
        order_type=OrderType.MARKET,
        price=Decimal("20000.25"),
        source_order_id="order-123",
    )
    journal = ExecutionJournal(tmp_path / "journal.sqlite3")

    journal.record(
        event,
        [CopyResult(account_id=follower, quantity=3, order_id=None, skipped=True, reason="dry run")],
    )

    rows = journal.recent()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "MNQZ6"
    assert rows[0]["leader_quantity"] == 2
    assert rows[0]["follower_quantity"] == 3
    assert rows[0]["reason"] == "dry run"
