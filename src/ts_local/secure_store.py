from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
from pathlib import Path
from typing import Any


class SecureStoreError(RuntimeError):
    pass


class WindowsSecureStore:
    """User-scoped Windows DPAPI storage for Tradovate secrets.

    The plaintext secret never needs to be written to disk. DPAPI binds the
    ciphertext to the current Windows user profile, so copying the data file
    to another Windows account does not make the credentials usable.
    """

    def __init__(self, path: Path | None = None) -> None:
        if os.name != "nt":
            raise SecureStoreError("Windows DPAPI secure storage requires Windows")
        self.path = path or (
            Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TS-Local" / "secrets.dat"
        )

    def set(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def delete(self, key: str) -> None:
        data = self._read()
        data.pop(key, None)
        self._write(data)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            ciphertext = base64.b64decode(self.path.read_bytes())
            plaintext = _unprotect(ciphertext)
            value = json.loads(plaintext.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception as exc:
            raise SecureStoreError("Unable to decrypt TS-Local credential store") from exc

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(value, separators=(",", ":")).encode("utf-8")
        ciphertext = _protect(plaintext)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_bytes(base64.b64encode(ciphertext))
        os.replace(temporary, self.path)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    input_blob = _DATA_BLOB(len(data), source)
    output_blob = _DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)


def _unprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    input_blob = _DATA_BLOB(len(data), source)
    output_blob = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
