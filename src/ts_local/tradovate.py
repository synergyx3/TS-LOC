from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

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

    async def accounts(self) -> list[TradovateAccount]:
        rows = await self.request("GET", "/account/list")
        return [
            TradovateAccount(
                id=__import__("uuid").uuid4(),
                login_id=__import__("uuid").uuid4(),
                account_id=str(row["id"]),
                name=str(row.get("name", row["id"])),
                active=bool(row.get("active", True)),
            )
            for row in rows
        ]

    def login_descriptor(self) -> TradovateLogin:
        return TradovateLogin(
            id=__import__("uuid").uuid4(),
            label=self.credentials.username,
            username=self.credentials.username,
            environment=self.environment.name,
        )


class TradovateWebSocket:
    """Protocol adapter for Tradovate's newline-delimited websocket API."""

    def __init__(self, url: str, access_token: str) -> None:
        self.url = url
        self.access_token = access_token
        self._ws: Any = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._receiver: asyncio.Task[None] | None = None
        self._subscriptions: list[tuple[str, dict[str, Any] | None]] = []

    async def connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("Install the websocket extra: pip install -e '.[dev]'") from exc

        self._ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20)
        await self._send_raw("authorize", 0, self.access_token)
        self._receiver = asyncio.create_task(self._receive_loop())

    async def close(self) -> None:
        if self._receiver:
            self._receiver.cancel()
            self._receiver = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def call(self, endpoint: str, body: dict[str, Any] | None = None) -> Any:
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected")
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send_raw(endpoint, request_id, json.dumps(body) if body else "")
        return await asyncio.wait_for(future, timeout=20)

    async def subscribe_user(self, user_id: int) -> Any:
        return await self.call("user/syncrequest", {"users": [user_id]})

    async def _send_raw(self, endpoint: str, request_id: int, payload: str) -> None:
        await self._ws.send(f"{endpoint}\n{request_id}\n\n{payload}")

    async def _receive_loop(self) -> None:
        async for raw in self._ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            await self._handle_message(raw)

    async def _handle_message(self, raw: str) -> None:
        if raw.startswith("a"):
            raw = raw[1:]
        try:
            messages = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(messages, list):
            return
        for message in messages:
            request_id = message.get("i")
            if request_id is None:
                continue
            future = self._pending.pop(int(request_id), None)
            if future is None or future.done():
                continue
            status = int(message.get("s", 500))
            if status >= 400:
                future.set_exception(TradovateAPIError(str(message.get("d", message))))
            else:
                future.set_result(message.get("d"))
