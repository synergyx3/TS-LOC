import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from ts_local.tradovate import LIVE, TradovateAuthError, TradovateClient, TradovateCredentials


def test_authenticate_parses_token_and_expiry():
    async def scenario() -> None:
        client = TradovateClient(TradovateCredentials("alice", "secret", "registered-app"), LIVE)

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert request.url.path.endswith("/auth/accesstokenrequest")
            assert payload["name"] == "alice"
            assert payload["appId"] == "registered-app"
            return httpx.Response(
                200,
                json={
                    "accessToken": "token-123",
                    "expirationTime": "2030-01-01T00:00:00Z",
                    "userId": 42,
                },
            )

        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=LIVE.rest_url
        )

        token = await client.authenticate()
        assert token.value == "token-123"
        assert token.user_id == 42
        assert token.expires_at == datetime(2030, 1, 1, tzinfo=timezone.utc)
        await client.aclose()

    asyncio.run(scenario())


def test_authenticate_omits_unregistered_app_fields_when_not_provided():
    async def scenario() -> None:
        client = TradovateClient(TradovateCredentials("alice", "secret"), LIVE)

        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert payload == {"name": "alice", "password": "secret"}
            return httpx.Response(
                200,
                json={
                    "accessToken": "token-123",
                    "expirationTime": "2030-01-01T00:00:00Z",
                    "userId": 42,
                },
            )

        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=LIVE.rest_url
        )
        await client.authenticate()
        await client.aclose()

    asyncio.run(scenario())


def test_authentication_error_does_not_expose_password():
    async def scenario() -> None:
        client = TradovateClient(TradovateCredentials("alice", "SUPER-SECRET"))

        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"errorText": "Invalid Credentials"})

        await client._http.aclose()
        client._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url=LIVE.rest_url
        )

        with pytest.raises(TradovateAuthError) as exc:
            await client.authenticate()
        assert "SUPER-SECRET" not in str(exc.value)
        await client.aclose()

    asyncio.run(scenario())
