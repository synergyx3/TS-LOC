from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from .models import TradovateLogin
from .security import SecretStore
from .tradovate import DEMO, LIVE, TradovateClient, TradovateCredentials, TradovateEnvironment


@dataclass(frozen=True)
class SavedLogin:
    id: UUID
    label: str
    username: str
    environment: str
    app_id: str | None = None
    app_version: str | None = None
    cid: str | None = None
    device_id: str | None = None


class ConnectionManager:
    """Owns non-secret login metadata and secure Tradovate credential retrieval."""

    def __init__(
        self,
        config_path: Path,
        secret_store: SecretStore,
        client_factory: Callable[[TradovateCredentials, TradovateEnvironment], TradovateClient] | None = None,
    ) -> None:
        self.config_path = config_path
        self.secret_store = secret_store
        self.client_factory = client_factory or (lambda credentials, environment: TradovateClient(credentials, environment))

    @staticmethod
    def _environment(name: str) -> TradovateEnvironment:
        normalized = name.strip().lower()
        if normalized == "live":
            return LIVE
        if normalized == "demo":
            return DEMO
        raise ValueError(f"Unsupported Tradovate environment: {name}")

    def list_saved(self) -> list[SavedLogin]:
        if not self.config_path.exists():
            return []
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        return [
            SavedLogin(
                id=UUID(row["id"]),
                label=row["label"],
                username=row["username"],
                environment=row["environment"],
                app_id=row.get("app_id") or None,
                app_version=row.get("app_version") or None,
                cid=row.get("cid"),
                device_id=row.get("device_id"),
            )
            for row in data.get("logins", [])
        ]

    def save_login(
        self,
        *,
        label: str,
        username: str,
        password: str,
        environment: str,
        app_id: str | None = None,
        app_version: str | None = None,
        cid: str | None = None,
        secret: str | None = None,
        device_id: str | None = None,
        login_id: UUID | None = None,
    ) -> SavedLogin:
        if not label.strip() or not username.strip() or not password:
            raise ValueError("label, username and password are required")
        env = self._environment(environment)
        entry = SavedLogin(
            id=login_id or uuid4(),
            label=label.strip(),
            username=username.strip(),
            environment=env.name,
            app_id=app_id.strip() if app_id and app_id.strip() else None,
            app_version=app_version.strip() if app_version and app_version.strip() else None,
            cid=cid.strip() if cid else None,
            device_id=device_id.strip() if device_id else None,
        )
        saved = [item for item in self.list_saved() if item.id != entry.id]
        saved.append(entry)
        self._write(saved)
        self.secret_store.put(self._secret_name(entry.id, "password"), password)
        if secret:
            self.secret_store.put(self._secret_name(entry.id, "api_secret"), secret)
        else:
            self.secret_store.delete(self._secret_name(entry.id, "api_secret"))
        return entry

    def delete_login(self, login_id: UUID) -> None:
        saved = [item for item in self.list_saved() if item.id != login_id]
        self._write(saved)
        self.secret_store.delete(self._secret_name(login_id, "password"))
        self.secret_store.delete(self._secret_name(login_id, "api_secret"))

    def create_client(self, saved: SavedLogin) -> TradovateClient:
        password = self.secret_store.get(self._secret_name(saved.id, "password"))
        if not password:
            raise RuntimeError(f"No saved password for login '{saved.label}'")
        api_secret = self.secret_store.get(self._secret_name(saved.id, "api_secret"))
        credentials = TradovateCredentials(
            username=saved.username,
            password=password,
            app_id=saved.app_id,
            app_version=saved.app_version,
            cid=saved.cid,
            secret=api_secret,
            device_id=saved.device_id,
        )
        return self.client_factory(credentials, self._environment(saved.environment))

    async def connect(self, saved: SavedLogin) -> TradovateLogin:
        client = self.create_client(saved)
        try:
            await client.authenticate()
            accounts = tuple(await client.accounts(saved.id))
            return client.login_descriptor(saved.id, label=saved.label, accounts=accounts)
        finally:
            await client.aclose()

    def _write(self, logins: list[SavedLogin]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "logins": [
                {
                    **asdict(item),
                    "id": str(item.id),
                }
                for item in sorted(logins, key=lambda item: item.label.lower())
            ],
        }
        temp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.config_path)

    @staticmethod
    def _secret_name(login_id: UUID, kind: str) -> str:
        return f"tradovate-{login_id}-{kind}"
