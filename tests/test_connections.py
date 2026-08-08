from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ts_local.connections import ConnectionManager
from ts_local.models import TradovateAccount


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def put(self, name: str, secret: str) -> None:
        self.values[name] = secret

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class FakeClient:
    def __init__(self, credentials, environment) -> None:
        self.credentials = credentials
        self.environment = environment
        self.closed = False

    async def authenticate(self):
        return object()

    async def accounts(self, login_id: UUID):
        return [
            TradovateAccount(
                id=uuid4(),
                login_id=login_id,
                account_id="123",
                name="SIM123",
            )
        ]

    def login_descriptor(self, login_id: UUID, *, label: str, accounts=()):
        from ts_local.models import TradovateLogin

        return TradovateLogin(
            id=login_id,
            label=label,
            username=self.credentials.username,
            environment=self.environment.name,
            accounts=accounts,
        )

    async def aclose(self):
        self.closed = True


def make_manager(tmp_path: Path, secrets: MemorySecrets) -> ConnectionManager:
    return ConnectionManager(tmp_path / "connections.json", secrets, FakeClient)


def test_password_is_not_written_to_connection_config(tmp_path):
    secrets = MemorySecrets()
    manager = make_manager(tmp_path, secrets)

    saved = manager.save_login(
        label="Main",
        username="alice",
        password="SUPER-SECRET",
        environment="demo",
        app_id="TS-Local",
        secret="API-SECRET",
    )

    raw = (tmp_path / "connections.json").read_text(encoding="utf-8")
    assert "SUPER-SECRET" not in raw
    assert "API-SECRET" not in raw
    assert saved.username in raw
    assert secrets.get(f"tradovate-{saved.id}-password") == "SUPER-SECRET"


@pytest.mark.asyncio
async def test_discovered_accounts_keep_login_ownership(tmp_path):
    secrets = MemorySecrets()
    manager = make_manager(tmp_path, secrets)
    saved = manager.save_login(
        label="Demo",
        username="alice",
        password="secret",
        environment="demo",
        app_id="TS-Local",
    )

    login = await manager.connect(saved)

    assert login.id == saved.id
    assert len(login.accounts) == 1
    assert login.accounts[0].login_id == saved.id
    assert login.accounts[0].account_id == "123"


def test_delete_login_removes_credential_material(tmp_path):
    secrets = MemorySecrets()
    manager = make_manager(tmp_path, secrets)
    saved = manager.save_login(
        label="Demo",
        username="alice",
        password="secret",
        environment="demo",
        app_id="TS-Local",
        secret="api-secret",
    )

    manager.delete_login(saved.id)

    assert manager.list_saved() == []
    assert secrets.values == {}
