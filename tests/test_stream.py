import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from ts_local.stream import LeaderOrderStream, ReconnectPolicy
from ts_local.tradovate import AccessToken, DEMO


class FakeRuntime:
    async def handle_socket_message(self, message):
        pass


class FakeClient:
    environment = DEMO

    def __init__(self):
        self.auth_calls = 0

    async def authenticate(self, force=False):
        self.auth_calls += 1
        return AccessToken(
            value=f"token-{self.auth_calls}",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            user_id=1,
            username="demo",
        )

    async def contract(self, contract_id):
        return {"name": "MNQZ6"}


class FakeSocket:
    def __init__(self, fail_wait=False):
        self.fail_wait = fail_wait
        self.connected = False
        self.subscribed = False
        self.closed = False

    async def connect(self):
        self.connected = True

    async def subscribe_user(self):
        self.subscribed = True

    async def wait_closed(self):
        await asyncio.sleep(0)
        if self.fail_wait:
            raise RuntimeError("socket dropped")

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_stream_start_authenticates_and_subscribes():
    client = FakeClient()
    sockets = []

    def factory(url, token, handler):
        socket = FakeSocket()
        sockets.append((url, token, socket))
        return socket

    stream = LeaderOrderStream(client, FakeRuntime(), socket_factory=factory)
    await stream.start()

    assert client.auth_calls == 1
    assert sockets[0][0] == DEMO.websocket_url
    assert sockets[0][1] == "token-1"
    assert sockets[0][2].connected is True
    assert sockets[0][2].subscribed is True

    await stream.close()
    assert sockets[0][2].closed is True


@pytest.mark.asyncio
async def test_run_forever_reauthenticates_after_disconnect():
    client = FakeClient()
    created = []

    def factory(url, token, handler):
        socket = FakeSocket(fail_wait=True)
        created.append(socket)
        return socket

    statuses = []

    async def on_status(message):
        statuses.append(message)

    stream = LeaderOrderStream(
        client,
        FakeRuntime(),
        socket_factory=factory,
        reconnect_policy=ReconnectPolicy(initial_delay=0.01, max_delay=0.01),
        on_status=on_status,
    )

    task = asyncio.create_task(stream.run_forever())
    for _ in range(100):
        if client.auth_calls >= 2:
            break
        await asyncio.sleep(0.002)
    await stream.close()
    await asyncio.wait_for(task, timeout=1)

    assert client.auth_calls >= 2
    assert len(created) >= 2
    assert any("reconnecting" in status for status in statuses)


@pytest.mark.asyncio
async def test_symbol_resolution_is_cached():
    client = FakeClient()
    calls = 0

    async def contract(contract_id):
        nonlocal calls
        calls += 1
        return {"name": "MNQZ6"}

    client.contract = contract
    stream = LeaderOrderStream(client, FakeRuntime(), socket_factory=lambda *_: FakeSocket())
    message = {
        "e": "props",
        "d": {
            "entityType": "order",
            "eventType": "Created",
            "entity": {"contractId": 123},
        },
    }

    first = await stream._enrich_order_symbol(message)
    second = await stream._enrich_order_symbol(message)

    assert first["d"]["entity"]["symbol"] == "MNQZ6"
    assert second["d"]["entity"]["symbol"] == "MNQZ6"
    assert calls == 1
