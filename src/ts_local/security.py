from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet


class LocalSecretStore:
    """Encrypted local secret store.

    The master key is supplied by the host application rather than committed to
    source. Production Windows builds should back this key with DPAPI/Windows
    Credential Manager; this class deliberately keeps that integration isolated.
    """

    def __init__(self, root: Path, master_key: bytes):
        if not master_key:
            raise ValueError("master_key is required")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        derived = base64.urlsafe_b64encode(hashlib.sha256(master_key).digest())
        self._cipher = Fernet(derived)

    def put(self, name: str, secret: str) -> None:
        if not name or "/" in name or "\\" in name:
            raise ValueError("invalid secret name")
        encrypted = self._cipher.encrypt(secret.encode("utf-8"))
        target = self.root / f"{name}.secret"
        target.write_bytes(encrypted)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass

    def get(self, name: str) -> str | None:
        target = self.root / f"{name}.secret"
        if not target.exists():
            return None
        return self._cipher.decrypt(target.read_bytes()).decode("utf-8")

    def delete(self, name: str) -> None:
        (self.root / f"{name}.secret").unlink(missing_ok=True)
