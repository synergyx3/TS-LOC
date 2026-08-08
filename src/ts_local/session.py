from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Callable

from .connections import ConnectionManager, SavedLogin
from .copier import TradeCopier
from .events import AccountBinding, TradovateEventNormalizer
from .journal import ExecutionJournal
from .models import CopyGroup, ExecutionMode, TradovateAccount
from .runtime import CopierRuntime
from .stream import LeaderOrderStream


class NeverLiveExecutor:
    async def execute(self, account_id, event):
        raise AssertionError("DRY RUN session attempted live execution")


@dataclass(frozen=True)
class SessionState:
    running: bool
    error: str | None = None


class DryRunLeaderSession:
    """Runs the leader websocket on a background asyncio loop for the desktop UI."""

    def __init__(
        self,
        manager: ConnectionManager,
        saved_login: SavedLogin,
        accounts: list[TradovateAccount],
        group: CopyGroup,
        journal: ExecutionJournal,
        on_state: Callable[[SessionState], None] | None = None,
    ) -> None:
        self.manager = manager
        self.saved_login = saved_login
        self.accounts = accounts
        self.group = group
        self.journal = journal
        self.on_state = on_state
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._thread_main, name="ts-local-dry-run", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        stop = self._stop
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)

    def _emit(self, state: SessionState) -> None:
        if self.on_state is not None:
            self.on_state(state)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._run())
        except Exception as exc:
            self._emit(SessionState(False, str(exc)))
        finally:
            self._loop = None
            self._stop = None

    async def _run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        client = self.manager.create_client(self.saved_login)
        bindings = [
            AccountBinding(int(account.account_id), account.id)
            for account in self.accounts
            if account.account_id.isdigit()
        ]
        normalizer = TradovateEventNormalizer(bindings)
        runtime = CopierRuntime(
            group=self.group,
            copier=TradeCopier(NeverLiveExecutor(), ExecutionMode.DRY_RUN),
            normalizer=normalizer,
            journal=self.journal,
        )
        stream = LeaderOrderStream(client, runtime)
        try:
            await stream.start()
            self._emit(SessionState(True))
            await self._stop.wait()
        finally:
            await stream.close()
            await client.aclose()
            self._emit(SessionState(False))
