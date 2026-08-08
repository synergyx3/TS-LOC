from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from uuid import UUID

from .copier import CopyResult
from .models import TradeEvent


class ExecutionJournal:
    """Small local-first SQLite journal for leader events and copy outcomes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    source_order_id TEXT,
                    leader_account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    leader_quantity INTEGER NOT NULL,
                    follower_account_id TEXT NOT NULL,
                    follower_quantity INTEGER NOT NULL,
                    order_id TEXT,
                    skipped INTEGER NOT NULL,
                    reason TEXT,
                    payload_json TEXT NOT NULL
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_journal_event_id ON execution_journal(event_id)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_journal_recorded_at ON execution_journal(recorded_at)"
            )

    def record(self, event: TradeEvent, results: Iterable[CopyResult]) -> None:
        rows = []
        recorded_at = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(
            {
                "event_id": str(event.event_id),
                "account_id": str(event.account_id),
                "symbol": event.symbol,
                "side": event.side.value,
                "quantity": event.quantity,
                "order_type": event.order_type.value,
                "price": str(event.price) if event.price is not None else None,
                "source_order_id": event.source_order_id,
                "occurred_at": event.occurred_at.isoformat(),
            },
            separators=(",", ":"),
        )
        for result in results:
            rows.append(
                (
                    recorded_at,
                    str(event.event_id),
                    event.source_order_id,
                    str(event.account_id),
                    event.symbol,
                    event.side.value,
                    event.order_type.value,
                    event.quantity,
                    str(result.account_id),
                    result.quantity,
                    result.order_id,
                    1 if result.skipped else 0,
                    result.reason,
                    payload_json,
                )
            )
        if not rows:
            return
        with self._connect() as db:
            db.executemany(
                """
                INSERT INTO execution_journal (
                    recorded_at, event_id, source_order_id, leader_account_id,
                    symbol, side, order_type, leader_quantity, follower_account_id,
                    follower_quantity, order_id, skipped, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def recent(self, limit: int = 100) -> list[dict[str, object]]:
        if limit < 1:
            return []
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT recorded_at, event_id, source_order_id, leader_account_id,
                       symbol, side, order_type, leader_quantity, follower_account_id,
                       follower_quantity, order_id, skipped, reason
                FROM execution_journal
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
