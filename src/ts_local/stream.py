from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from .runtime import CopierRuntime
from .tradovate import TradovateClient, TradovateWebSocket


StatusHandler = Callable[[str], Awaitable[None] | None]
SocketFactory = Callable[[str, str, Callable[[dict[str, Any]], Awaitable[None]]], TradovateWebSocket]


@dataclass(frozen=True)
class ReconnectPolicy:
    initial_delay: float = 1.0
    max_delay: float = 20.0
    multiplier: float = 2.0

    def next_delay(self, current: float) -> float:
        if current <= 0:
            return self.initial_delay
        return min(self.max_delay, current * self.multiplier)


class LeaderOrderStream:
    """Resolve Tradovate order metadata and feed normalized events to the copier runtime.

    `run_forever` owns the websocket lifecycle and reconnects after transient
    failures. A reconnect always authenticates again and issues a fresh
    user/syncrequest so stale sockets are never reused.
    """

    def __init__(
        self,
        client: TradovateClient,
        runtime: CopierRuntime,
        *,
        socket_factory: SocketFactory | None = None,
        reconnect_policy: ReconnectPolicy = ReconnectPolicy(),
        on_status: StatusHandler | None = None,
    ) -> None:
        self.client = client
        self.runtime = runtime
        self.socket: TradovateWebSocket | None = None
        self._contract_names: dict[int, str] = {}
        self._socket_factory = socket_factory or self._default_socket_factory
        self._reconnect_policy = reconnect_policy
        self._on_status = on_status
        self._stop_event = asyncio.Event()

    @staticmethod
    def _default_socket_factory(url: str, token: str, handler):
        return TradovateWebSocket(url, token, on_event=handler)

    async def start(self) -> None:
        """Open one websocket session. Prefer `run_forever` for production."""
        self._stop_event.clear()
        await self._open_session()

    async def run_forever(self) -> None:
        """Run until `close` is called, reconnecting with bounded backoff."""
        self._stop_event.clear()
        delay = 0.0

        while not self._stop_event.is_set():
            try:
                await self._open_session()
                delay = 0.0
                await self._wait_until_socket_ends()
                if self._stop_event.is_set():
                    break
                await self._emit_status("Tradovate stream disconnected; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                await self._emit_status(
                    f"Tradovate stream error: {type(exc).__name__}; reconnecting"
                )
            finally:
                await self._close_socket()

            delay = self._reconnect_policy.next_delay(delay)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

        await self._emit_status("Tradovate stream stopped")

    async def close(self) -> None:
        self._stop_event.set()
        await self._close_socket()

    async def _open_session(self) -> None:
        await self._close_socket()
        await self._emit_status("Authenticating Tradovate stream")
        token = await self.client.authenticate(force=True)
        socket = self._socket_factory(
            self.client.environment.websocket_url,
            token.value,
            self._on_event,
        )
        self.socket = socket
        try:
            await socket.connect()
            await socket.subscribe_user()
        except Exception:
            await self._close_socket()
            raise
        await self._emit_status("Tradovate stream connected — DRY RUN")

    async def _wait_until_socket_ends(self) -> None:
        socket = self.socket
        if socket is None:
            return
        await socket.wait_closed()

    async def _close_socket(self) -> None:
        socket = self.socket
        self.socket = None
        if socket is not None:
            await socket.close()

    async def _emit_status(self, message: str) -> None:
        if self._on_status is None:
            return
        result = self._on_status(message)
        if asyncio.iscoroutine(result):
            await result

    async def _on_event(self, message: dict[str, Any]) -> None:
        enriched = await self._enrich_order_symbol(message)
        await self.runtime.handle_socket_message(enriched)

    async def _enrich_order_symbol(self, message: dict[str, Any]) -> dict[str, Any]:
        data = message.get("d")
        if not isinstance(data, dict) or data.get("entityType") != "order":
            return message
        entity = data.get("entity")
        if not isinstance(entity, dict):
            return message
        if entity.get("symbol") or entity.get("contractName"):
            return message

        contract_id = entity.get("contractId")
        if contract_id is None:
            return message
        contract_id = int(contract_id)

        name = self._contract_names.get(contract_id)
        if name is None:
            contract = await self.client.contract(contract_id)
            name = str(contract.get("name") or contract.get("symbol") or "")
            if name:
                self._contract_names[contract_id] = name

        if not name:
            return message

        enriched = deepcopy(message)
        enriched["d"]["entity"]["symbol"] = name
        return enriched
