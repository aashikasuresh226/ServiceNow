"""Password hashing, JWTs, one-time codes, TOTP and secret encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.core.errors import Unauthorized

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# A real hash of a random string, used to equalize timing when a user doesn't exist.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


class Role(StrEnum):
    HOMEOWNER = "homeowner"
    SHOP_USER = "shop_user"


class TokenType(StrEnum):
    ACCESS = "access"
    MFA = "mfa"  # password verified, second factor pending
    MFA_SETUP = "mfa_setup"  # new shop user must enroll 2-step before full access


@dataclass(frozen=True, slots=True)
class TokenClaims:
    subject_id: uuid.UUID
    role: Role
    token_type: TokenType
    shop_id: uuid.UUID | None = None


class TokenService:
    def __init__(self, secret: str, issuer: str) -> None:
        if len(secret) < 32:
            raise ValueError("JWT secret must be at least 32 characters")
        self._secret = secret
        self._issuer = issuer

    def issue(self, claims: TokenClaims, *, now: datetime, ttl: timedelta) -> str:
        payload: dict[str, Any] = {
            "sub": str(claims.subject_id),
            "role": claims.role.value,
            "typ": claims.token_type.value,
            "iss": self._issuer,
            "iat": int(now.timestamp()),
            "exp": int((now + ttl).timestamp()),
            "jti": secrets.token_hex(8),
        }
        if claims.shop_id:
            payload["shop"] = str(claims.shop_id)
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def verify(self, token: str, *, expected_type: TokenType, now: datetime) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=["HS256"],
                issuer=self._issuer,
                # Expiry is checked below against the injected clock, not the system clock.
                options={"require": ["exp", "sub", "role", "typ"], "verify_exp": False},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized("Invalid token") from exc
        if int(payload["exp"]) <= now.timestamp():
            raise Unauthorized("Session expired", code="token_expired")
        if payload["typ"] != expected_type.value:
            raise Unauthorized("Wrong token type")
        return TokenClaims(
            subject_id=uuid.UUID(payload["sub"]),
            role=Role(payload["role"]),
            token_type=TokenType(payload["typ"]),
            shop_id=uuid.UUID(payload["shop"]) if payload.get("shop") else None,
        )


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    """Refresh tokens are high-entropy random strings, so a fast hash is appropriate."""
    return hashlib.sha256(token.encode()).hexdigest()


def generate_otp_code(digits: int = 6) -> str:
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def hash_otp(code: str, phone: str, pepper: str) -> str:
    """HMAC with a server secret: 6-digit codes are too small a space to hash unkeyed."""
    return hmac.new(pepper.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


class Encryptor:
    """Symmetric encryption for secrets at rest (TOTP seeds, integration credentials)."""

    def __init__(self, key: str) -> None:
        raw = base64.urlsafe_b64decode(key)
        if len(raw) != 32:
            raise ValueError("Encryption key must be 32 bytes, urlsafe-base64 encoded")
        self._fernet = Fernet(key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Could not decrypt value; was the encryption key rotated?") from exc


class UrlSigner:
    """Short-lived signed URLs for photos, so <img src> works without auth headers."""

    def __init__(self, secret: str) -> None:
        self._key = hashlib.sha256(f"url-signing:{secret}".encode()).digest()

    def sign(self, resource: str, expires_at: datetime) -> str:
        exp = int(expires_at.timestamp())
        mac = hmac.new(self._key, f"{resource}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"{exp}.{mac}"

    def verify(self, resource: str, signature: str, *, now: datetime) -> bool:
        try:
            exp_s, mac = signature.split(".", 1)
            exp = int(exp_s)
        except ValueError:
            return False
        if exp < now.timestamp():
            return False
        expected = hmac.new(self._key, f"{resource}:{exp}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected[:32], mac)


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str, *, at: datetime) -> bool:
    # valid_window=1 tolerates one 30s step of clock drift on the user's phone.
    return pyotp.TOTP(secret).verify(code.strip(), for_time=at, valid_window=1)
