"""Encryption of personal data inside the database ("field-level encryption").

Customer names, phone numbers, emails, addresses, problem descriptions, chat
messages and live locations are encrypted by the app before they are written,
with the key in HVAC_ENCRYPTION_KEY (kept outside the database). Someone holding
a copy of the database, or the database password, sees only ciphertext.

Encrypted values are randomized, so the database can't search them. Columns we
need to look up (phone, email) also store a "blind index": an HMAC of the
normalized value under a separate key derived from the same secret. Equal inputs
give equal indexes, but the index can't be reversed without the key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text, TypeDecorator

PREFIX = "enc1:"

_fernet: Fernet | None = None
_index_key: bytes | None = None


def configure(key: str) -> None:
    """Called at startup with HVAC_ENCRYPTION_KEY (urlsafe base64, 32 bytes)."""
    global _fernet, _index_key
    raw = base64.urlsafe_b64decode(key)
    if len(raw) != 32:
        raise ValueError("Encryption key must be 32 bytes, urlsafe-base64 encoded")
    _fernet = Fernet(key.encode())
    _index_key = hmac.new(raw, b"blind-index-v1", hashlib.sha256).digest()


def _ensure() -> tuple[Fernet, bytes]:
    if _fernet is None or _index_key is None:
        from app.core.config import get_settings  # lazy: CLI tools and migrations

        configure(get_settings().encryption_key.get_secret_value())
    assert _fernet is not None and _index_key is not None
    return _fernet, _index_key


def encrypt(value: str) -> str:
    fernet, _ = _ensure()
    return PREFIX + fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value.startswith(PREFIX):
        return value  # written before encryption was switched on
    fernet, _ = _ensure()
    try:
        return fernet.decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Can't decrypt stored data: was HVAC_ENCRYPTION_KEY changed?") from exc


def blind_index(kind: str, value: str | None) -> str | None:
    if value is None:
        return None
    _, key = _ensure()
    return hmac.new(key, f"{kind}:{value.strip().lower()}".encode(), hashlib.sha256).hexdigest()


def encrypt_bytes(data: bytes) -> bytes:
    fernet, _ = _ensure()
    return PREFIX.encode() + fernet.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    if not data.startswith(PREFIX.encode()):
        return data  # file saved before encryption was switched on
    fernet, _ = _ensure()
    return fernet.decrypt(data[len(PREFIX) :])


class EncryptedText(TypeDecorator[str]):
    """A string column stored encrypted. Reads and writes look like plain strings."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return decrypt(str(value))


class EncryptedFloat(TypeDecorator[float]):
    """A number (e.g. a live GPS coordinate) stored encrypted."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else encrypt(repr(float(value)))

    def process_result_value(self, value: Any, dialect: Any) -> float | None:
        return None if value is None else float(decrypt(str(value)))
