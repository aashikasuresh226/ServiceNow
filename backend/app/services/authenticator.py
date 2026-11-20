"""Sign-in with an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password,
iPhone Passwords...) for homeowners and technicians. Free: no texts are sent.

Setting up: we create a secret, the person adds it to their authenticator (QR code, the
"add to authenticator" link, or the key typed in) and proves it with a 6-digit code. The
secret is kept encrypted. They get 8 one-time backup codes (stored hashed) for when they
lose their phone.

Until the secret is confirmed it lives only in a short-lived encrypted setup token, so an
unfinished setup creates nothing.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.container import Container
from app.core.errors import AppError, Unauthorized
from app.core.security import new_totp_secret, totp_uri, verify_totp

SETUP_TTL = timedelta(minutes=30)
BACKUP_CODES = 8
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


@dataclass(frozen=True, slots=True)
class Setup:
    token: str  # give back with the first code
    secret: str  # shown so it can be typed in
    uri: str  # otpauth:// (QR code / "add to authenticator" link)


def start(c: Container, *, account: str, subject: str) -> Setup:
    """`account` is what the authenticator shows (e.g. a phone number); `subject` ties the
    setup to who's setting up (e.g. "homeowner:+1404..." or "tech:<id>")."""
    secret = new_totp_secret()
    expires = (c.clock.now() + SETUP_TTL).isoformat()
    token = c.encryptor.encrypt(json.dumps({"s": secret, "sub": subject, "exp": expires}))
    return Setup(token, secret, totp_uri(secret, account, "HVAC Connect"))


def finish(c: Container, token: str, code: str, *, subject: str) -> str:
    """Check the first code; returns the secret (encrypt it before storing)."""
    try:
        data = json.loads(c.encryptor.decrypt(token))
    except (ValueError, TypeError) as exc:
        raise AppError("Start the authenticator setup again", code="setup_invalid") from exc
    if data.get("sub") != subject:
        raise AppError("Start the authenticator setup again", code="setup_invalid")
    if datetime.fromisoformat(data["exp"]) < c.clock.now():
        raise AppError("The setup expired. Start again.", code="setup_expired")
    c.rate_limiter.check("totp-setup", subject, limit=10, window_seconds=900)
    if not verify_totp(data["s"], code, at=c.clock.now()):
        raise Unauthorized(
            "That code isn't right. Check your phone's time is set automatically, then try "
            "the newest code.",
            code="mfa_invalid",
        )
    return str(data["s"])


def new_backup_codes() -> tuple[list[str], str]:
    """(codes to show once, JSON of their hashes to store)."""
    codes = [
        "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(2))
        for _ in range(BACKUP_CODES)
    ]
    return codes, json.dumps([_hash(code) for code in codes])


def _hash(code: str) -> str:
    normalized = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


def check(
    c: Container, *, secret_encrypted: str | None, backup_codes: str | None, code: str, key: str
) -> str | None:
    """Accept a current authenticator code or an unused backup code. Returns the updated
    backup-code JSON when a backup code was used (store it), else None. Raises if wrong."""
    # The 6-digit space is small: cap guesses per account.
    c.rate_limiter.check("totp", key, limit=10, window_seconds=900)
    code = code.strip()
    if secret_encrypted and code.isdigit() and len(code) == 6:
        if verify_totp(c.encryptor.decrypt(secret_encrypted), code, at=c.clock.now()):
            return None
    elif backup_codes and len(code) >= 8:
        hashes: list[str] = json.loads(backup_codes)
        if _hash(code) in hashes:
            hashes.remove(_hash(code))
            return json.dumps(hashes)
    raise Unauthorized("That code isn't right", code="mfa_invalid")
