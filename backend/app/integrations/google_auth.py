"""Verifies Google ID tokens ("Sign in with Google").

The browser gets an ID token (a JWT signed by Google) from Google Identity
Services. We check, on the server:
- the signature against Google's published keys (cached per their max-age),
- the issuer is Google and the audience is one of our OAuth client IDs,
- the token hasn't expired,
- the email is verified by Google,
- the nonce matches one we issued (checked by the caller), so a token
  captured elsewhere can't be replayed here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from app.core.errors import ExternalServiceError, Unauthorized

log = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
DEFAULT_KEY_TTL_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str  # Google's stable account id ("sub")
    email: str
    name: str | None
    nonce: str | None


class GoogleTokenVerifier:
    def __init__(
        self,
        *,
        client_ids: list[str],
        http: httpx.AsyncClient,
        certs_url: str = GOOGLE_CERTS_URL,
    ) -> None:
        if not client_ids:
            raise ValueError("At least one Google client ID is required")
        self._client_ids = client_ids
        self._http = http
        self._certs_url = certs_url
        self._keys: dict[str, Any] = {}
        self._keys_expire_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, id_token: str, *, now: float | None = None) -> GoogleIdentity:
        now = time.time() if now is None else now
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise Unauthorized("Google sign-in failed. Please try again.") from exc
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise Unauthorized("Google sign-in failed. Please try again.")
        key = await self._key(str(header["kid"]), now)
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self._client_ids,
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iat": False},
                leeway=CLOCK_SKEW_SECONDS,
            )
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Google sign-in expired. Please try again.") from exc
        except jwt.PyJWTError as exc:
            log.info("Rejected Google ID token: %s", exc)
            raise Unauthorized("Google sign-in failed. Please try again.") from exc

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise Unauthorized("Google sign-in failed. Please try again.")
        email = claims.get("email")
        if not email or claims.get("email_verified") not in (True, "true"):
            raise Unauthorized("Your Google account's email isn't verified.")
        name = claims.get("name")
        return GoogleIdentity(
            subject=str(claims["sub"]),
            email=str(email).lower(),
            name=str(name)[:120] if name else None,
            nonce=claims.get("nonce"),
        )

    async def _key(self, kid: str, now: float) -> Any:
        if kid not in self._keys or now >= self._keys_expire_at:
            async with self._lock:
                if kid not in self._keys or now >= self._keys_expire_at:
                    await self._refresh_keys(now)
        key = self._keys.get(kid)
        if key is None:
            raise Unauthorized("Google sign-in failed. Please try again.")
        return key

    async def _refresh_keys(self, now: float) -> None:
        try:
            response = await self._http.get(self._certs_url)
            response.raise_for_status()
            jwks = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Can't reach Google right now. Please try again.") from exc
        keys: dict[str, Any] = {}
        for jwk in jwks.get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("kid"):
                keys[jwk["kid"]] = jwt.PyJWK.from_json(json.dumps(jwk)).key
        self._keys = keys
        self._keys_expire_at = now + _max_age(response.headers.get("cache-control"))


def _max_age(cache_control: str | None) -> int:
    match = re.search(r"max-age=(\d+)", cache_control or "")
    return int(match.group(1)) if match else DEFAULT_KEY_TTL_SECONDS
