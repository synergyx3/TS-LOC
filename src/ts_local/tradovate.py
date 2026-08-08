from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

import httpx

from .models import TradovateAccount, TradovateLogin


@dataclass(frozen=True)
class TradovateEnvironment:
    name: str
    rest_url: str
    websocket_url: str


LIVE = TradovateEnvironment(
    "live",
    "https://live.tradovateapi.com/v1",
    "wss://live.tradovateapi.com/v1/websocket",
)
DEMO = TradovateEnvironment(
    "demo",
    "https://demo.tradovateapi.com/v1",
    "wss://demo.tradovateapi.com/v1/websocket",
)


@dataclass(frozen=True)
class TradovateCredentials:
    username: str
    password: str
    app_id: str
    app_version: str = "1.0.0"
    cid: str | None = None
    secret: str | None = None
    device_id: str | None = None


@dataclass(frozen=True)
class AccessToken:
    value: str
    expires_at: datetime
    user_id: int
    username: str

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def expires_soon(self) -> bool:
        return (self.expires_at - datetime.now(timezone.utc)).total_seconds() < 15 * 60


class TradovateAPIError(RuntimeError):
    pass


class TradovateAuthError(TradovateAPIError):
    pass


class TradovateClient:
    """Small async Tradovate REST client with token renewal and account discovery."""

    def __init__(
        self,
        credentials: TradovateCredentials,
        environment: TradovateEnvironment = LIVE,
        timeout: float = 20.0,
    ) -> None:
        self.credentials = credentials
        self.environment = environment
        self._http = httpx.AsyncClient(
            base_url=environment.rest_url,
            timeout=timeout,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        self._token: AccessToken | None = None
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def authenticate(self, force: bool = False) -> AccessToken:
        async with self._token_lock:
            if self._token and not force and not self._token.expires_soon:
                return self._token

            if self._token and not self._token.is_expired:
                try:
                    response = await self._http.get(
                        "/auth/renewaccesstoken",
                        headers={"Authorization": f"Bearer {self._token.value}"},
                    )
                    response.raise_for_status()
                    data = response.json()
                    self._token = self._parse_token(data, self._token.username)
                    return self._token
                except httpx.HTTPError:
                    self._token = None

            payload: dict[str, Any] = {
                "name": self.credentials.username,
                "password": self.credentials.password,
                "appId": self.credentials.app_id,
                "appVersion": self.credentials.app_version,
            }
            if self.credentials.cid:
                payload["cid"] = self.credentials.cid
            if self.credentials.secret:
                payload["sec"] = self.credentials.secret
            if self.credentials.device_id:
                payload["deviceId"] = self.credentials.device_id

            response = await self._http.post("/auth/accesstokenrequest", json=payload)
            data = response.json()
            if response.status_code >= 400 or not data.get("accessToken"):
                detail = data.get("errorText") or response.text
                raise TradovateAuthError(f"Tradovate authentication failed: {detail}")

            self._token = self._parse_token(data, self.credentials.username)
            return self._token

    @staticmethod
    def _parse_token(data: dict[str, Any], username: str) -> AccessToken:
        expiration = data.get("expirationTime")
        if not expiration:
            raise TradovateAuthError("Tradovate did not return an expiration time")
        expires_at = datetime.fromisoformat(expiration.replace("Z", "+00:00"))
        return AccessToken(
            value=data["accessToken"],
            expires_at=expires_at,
            user_id=int(data["userId"]),
            username=username,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        token = await self.authenticate()
        response = await self._http.request(
            method,
            path,
            json=json_body,
            headers={"Authorization": f"Bearer {token.value}"},
        )
        if response.status_code == 401 and retry_auth:
            await self.authenticate(force=True)
            return await self.request(method, path, json_body=json_body, retry_auth=False)
        if response.status_code >= 400:
            try:
                detail = response.json().get("errorText") or response.text
            except json.JSONDecodeError:
                detail = response.text
            raise TradovateAPIError(f"{method} {path} failed ({response.status_code}): {detail}")
        return response.json()

    async def me(self) -> dict[str, Any]:
        return await self.request("GET", "/auth/me")

    async def accounts(self, login_id: UUID | None = None) -> list[TradovateAccount]:
        rows = await self.request("GET", "/account/list")
        owner_id = login_id or uuid4()
        return [
            TradovateAccount(
                id=uuid4(),
                login_id=owner_id,
                account_id=str(row["id"]),
                name=str(row.get("name", row["id"])),
                active=bool(row.get("active", True)),
            )
            for row in rows
        ]

    async def contract(self, contract_id: int) -> dict[str, Any]:
        return await self.request("GET", f"/contract/item?id={int(contract_id)}")

    def login_descriptor(
        self,
        login_id: UUID | None = None,
        *,
        label: str | None = None,
        accounts: tuple[TradovateAccount, ...] = (),
    ) -> TradovateLogin:
        return TradovateLogin(
            id=login_id or uuid4(),
            label=label or self.credentials.username,
            username=self.credentials.username,
            environment=self.environment.name,
            accounts=accounts,
        )


EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TradovateWebSocket:
    """Protocol adapter for Tradovate's websocket API with heartbeat support."""

    def __init__(
        self,
        url: str,
        access_token: str,
        on_event: EventHandler | None = None,
    ) -> None:
        self.url = url
        self.access_token = access_token
        self.on_event = on_event
        self._ws: Any = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._receiver: asyncio.Task[None] | None = None
        self._heartbeat: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install the websocket dependency with: pip install -e .") from exc

        self._ws = await websockets.connect(self.url, ping_interval=None)
        self._receiver = asyncio.create_task(self._receive_loop(), name="tradovate-receiver")
        self._heartbeat = asyncio.create_task(self._heartbeat_loop(), name="tradovate-heartbeat")
        await self._send_raw("authorize", 0, self.access_token)

    async def wait_closed(self) -> None:
        """Wait for receiver/heartbeat termination and surface unexpected failures."""
        tasks = [task for task in (self._receiver, self._heartbeat) if task is not None]
        if not tasks:
            return
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.cancelled():
                continue
            exception = task.exception()
            if exception is not None:
                raise exception

    async def close(self) -> None:
        tasks = [task for task in (self._receiver, self._heartbeat) if task is not None]
        for task in tasks:
            task.cancel()
        self._receiver = None
        self._heartbeat = None
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def call(self, endpoint: str, body: dict[str, Any] | None = None) -> Any:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send_raw(endpoint, request_id, json.dumps(body) if body else "")
        try:
            return await asyncio.wait_for(future, timeout=20)
        finally:
            self._pending.pop(request_id, None)

    async def subscribe_user(self) -> Any:
        return await self.call(
            "user/syncrequest",
            {
                "splitResponses": True,
                "entityTypes": [
                    "account",
                    "executionReport",
                    "fill",
                    "order",
                    "orderStrategy",
                    "position",
                ],
            },
        )

    async def _send_raw(self, endpoint: str, request_id: int, payload: str) -> None:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        await self._ws.send(f"{endpoint}\n{request_id}\n\n{payload}")

    async def _heartbeat_loop(self) -> None:
        while self._ws is not None:
            await asyncio.sleep(2.5)
            if self._ws is not None:
                await self._ws.send("[]")

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            await self._handle_message(raw)

    async def _handle_message(self, raw: str) -> None:
        if raw == "o" or raw.startswith("h"):
            return
        if raw.startswith("c"):
            raise TradovateAPIError(f"Tradovate websocket closed: {raw}")
        if raw.startswith("a"):
            raw = raw[1:]
        try:
            messages = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(messages, list):
            messages = [messages]

        for message in messages:
            if not isinstance(message, dict):
                continue
            request_id = message.get("i")
            if request_id is not None:
                future = self._pending.get(int(request_id))
                if future is not None and not future.done():
                    status = int(message.get("s", 500))
                    if status >= 400:
                        future.set_exception(TradovateAPIError(str(message.get("d", message))))
                    else:
                        future.set_result(message.get("d"))
                    continue

            if self.on_event is not None and message.get("e"):
                await self.on_event(message)
