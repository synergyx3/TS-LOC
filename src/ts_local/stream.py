from __future__ import annotations

from copy import deepcopy
from typing import Any

from .runtime import CopierRuntime
from .tradovate import TradovateClient, TradovateWebSocket


class LeaderOrderStream:
    """Resolve Tradovate order metadata and feed normalized events to the copier runtime."""

    def __init__(self, client: TradovateClient, runtime: CopierRuntime) -> None:
        self.client = client
        self.runtime = runtime
        self.socket: TradovateWebSocket | None = None
        self._contract_names: dict[int, str] = {}

    async def start(self) -> None:
        token = await self.client.authenticate()
        self.socket = TradovateWebSocket(
            self.client.environment.websocket_url,
            token.value,
            on_event=self._on_event,
        )
        await self.socket.connect()
        await self.socket.subscribe_user()

    async def close(self) -> None:
        if self.socket is not None:
            await self.socket.close()
            self.socket = None

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
