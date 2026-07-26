"""Per-user encrypted token storage for local data-source credentials.

Only encrypted bytes are persisted. On Windows the encryption uses DPAPI with
the current user profile, so another Windows user cannot decrypt the store.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
from os import getenv, replace
from pathlib import Path
from typing import Callable


class SecretStoreError(RuntimeError):
    """A safe error that never includes a secret value."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _blob_from_bytes(value: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_byte]]:
    buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    return _DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect_with_dpapi(value: bytes) -> bytes:
    if not value:
        raise SecretStoreError("Cannot protect an empty secret")
    try:
        crypt_protect = ctypes.windll.crypt32.CryptProtectData
        local_free = ctypes.windll.kernel32.LocalFree
    except AttributeError as error:
        raise SecretStoreError("Secure token storage requires Windows DPAPI") from error

    crypt_protect.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt_protect.restype = wintypes.BOOL
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    if not crypt_protect(ctypes.byref(input_blob), None, None, None, None, 0x1, ctypes.byref(output_blob)):
        raise SecretStoreError("Windows could not encrypt the token")
    # Keep the Python buffer alive until CryptProtectData has consumed it.
    del input_buffer
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(output_blob.pbData)


def _unprotect_with_dpapi(value: bytes) -> bytes:
    try:
        crypt_unprotect = ctypes.windll.crypt32.CryptUnprotectData
        local_free = ctypes.windll.kernel32.LocalFree
    except AttributeError as error:
        raise SecretStoreError("Secure token storage requires Windows DPAPI") from error

    crypt_unprotect.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt_unprotect.restype = wintypes.BOOL
    input_blob, input_buffer = _blob_from_bytes(value)
    output_blob = _DataBlob()
    if not crypt_unprotect(ctypes.byref(input_blob), None, None, None, None, 0x1, ctypes.byref(output_blob)):
        raise SecretStoreError("Windows could not decrypt the stored token")
    del input_buffer
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        local_free(output_blob.pbData)


def default_secret_store_path() -> Path:
    """Use a user-local data directory outside the repository and its Git tree."""

    local_data = Path(getenv("LOCALAPPDATA", r"C:\Users\Default\AppData\Local"))
    return local_data / "Codex" / "ai-agent" / "tokens.json"


class TokenStore:
    """Persists named API tokens using pluggable encryption for testability."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        protect: Callable[[bytes], bytes] = _protect_with_dpapi,
        unprotect: Callable[[bytes], bytes] = _unprotect_with_dpapi,
    ) -> None:
        self._path = path or default_secret_store_path()
        self._protect = protect
        self._unprotect = unprotect

    def get_token(self, source: str) -> str | None:
        token_record = self._read().get(self._validate_source(source))
        if token_record is None:
            return None
        try:
            encrypted = base64.b64decode(token_record.encode("ascii"), validate=True)
            return self._unprotect(encrypted).decode("utf-8")
        except (UnicodeDecodeError, ValueError, SecretStoreError) as error:
            raise SecretStoreError("Stored token could not be read") from error

    def set_token(self, source: str, token: str) -> None:
        if not token.strip():
            raise ValueError("Token cannot be blank")
        source_name = self._validate_source(source)
        records = self._read()
        encrypted = self._protect(token.strip().encode("utf-8"))
        records[source_name] = base64.b64encode(encrypted).decode("ascii")
        self._write(records)

    def delete_token(self, source: str) -> bool:
        source_name = self._validate_source(source)
        records = self._read()
        if source_name not in records:
            return False
        del records[source_name]
        self._write(records)
        return True

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            document = json.loads(self._path.read_text(encoding="utf-8"))
            records = document["tokens"]
        except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise SecretStoreError("Secure token store could not be read") from error
        if document.get("version") != 1 or not isinstance(records, dict):
            raise SecretStoreError("Secure token store has an unsupported format")
        if not all(isinstance(source, str) and isinstance(token, str) for source, token in records.items()):
            raise SecretStoreError("Secure token store has invalid records")
        return dict(records)

    def _write(self, records: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".tmp")
        try:
            temporary_path.write_text(
                json.dumps({"version": 1, "tokens": records}, separators=(",", ":")),
                encoding="utf-8",
            )
            replace(temporary_path, self._path)
        except OSError as error:
            raise SecretStoreError("Secure token store could not be saved") from error

    @staticmethod
    def _validate_source(source: str) -> str:
        normalized = source.strip().lower()
        if not normalized or not normalized.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Source names may contain only letters, numbers, hyphens, and underscores")
        return normalized


def resolve_token(source: str, environment_variable: str, store: TokenStore | None = None) -> str | None:
    """Prefer an ephemeral environment value, otherwise retrieve the local token."""

    environment_token = getenv(environment_variable)
    if environment_token:
        return environment_token
    return (store or TokenStore()).get_token(source)
