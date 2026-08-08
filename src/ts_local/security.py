from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet


class SecretStore(Protocol):
    def put(self, name: str, secret: str) -> None: ...
    def get(self, name: str) -> str | None: ...
    def delete(self, name: str) -> None: ...


def _validate_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("invalid secret name")
    return name


class LocalSecretStore:
    """Portable encrypted store used by tests and non-Windows development.

    Production Windows builds should prefer :class:`WindowsDPAPISecretStore`.
    """

    def __init__(self, root: Path, master_key: bytes):
        if not master_key:
            raise ValueError("master_key is required")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        derived = base64.urlsafe_b64encode(hashlib.sha256(master_key).digest())
        self._cipher = Fernet(derived)

    def put(self, name: str, secret: str) -> None:
        name = _validate_name(name)
        encrypted = self._cipher.encrypt(secret.encode("utf-8"))
        target = self.root / f"{name}.secret"
        target.write_bytes(encrypted)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass

    def get(self, name: str) -> str | None:
        name = _validate_name(name)
        target = self.root / f"{name}.secret"
        if not target.exists():
            return None
        return self._cipher.decrypt(target.read_bytes()).decode("utf-8")

    def delete(self, name: str) -> None:
        name = _validate_name(name)
        (self.root / f"{name}.secret").unlink(missing_ok=True)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class WindowsDPAPISecretStore:
    """User-scoped Windows DPAPI secret storage.

    Ciphertext is stored on disk, while Windows protects the decryption key for
    the currently signed-in user. No reusable application master key is stored.
    """

    CRYPTPROTECT_UI_FORBIDDEN = 0x01

    def __init__(self, root: Path):
        if sys.platform != "win32":
            raise OSError("WindowsDPAPISecretStore is only available on Windows")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def _protect(self, data: bytes) -> bytes:
        in_blob, _buffer = self._blob(data)
        out_blob = _DataBlob()
        ok = self._crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "TS-Local",
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def _unprotect(self, data: bytes) -> bytes:
        in_blob, _buffer = self._blob(data)
        out_blob = _DataBlob()
        ok = self._crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            self.CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        if not ok:
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def put(self, name: str, secret: str) -> None:
        name = _validate_name(name)
        target = self.root / f"{name}.dpapi"
        target.write_bytes(self._protect(secret.encode("utf-8")))

    def get(self, name: str) -> str | None:
        name = _validate_name(name)
        target = self.root / f"{name}.dpapi"
        if not target.exists():
            return None
        return self._unprotect(target.read_bytes()).decode("utf-8")

    def delete(self, name: str) -> None:
        name = _validate_name(name)
        (self.root / f"{name}.dpapi").unlink(missing_ok=True)
