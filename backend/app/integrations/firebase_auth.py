"""Verifies Firebase Authentication ID tokens.

We use Firebase (free Spark plan) only to prove someone controls an email address:
the browser asks Firebase to email a sign-in link, the person opens it, and the
browser gets a Firebase ID token whose `email` is verified. We check that token
here, against Google's published keys for Firebase:
- signature (RS256), issuer https://securetoken.google.com/<project>, audience <project>,
- not expired, and the email is verified.
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

FIREBASE_KEYS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
CLOCK_SKEW_SECONDS = 60
DEFAULT_KEY_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class FirebaseIdentity:
    uid: str
    email: str


class FirebaseTokenVerifier:
    def __init__(
        self, *, project_id: str, http: httpx.AsyncClient, keys_url: str = FIREBASE_KEYS_URL
    ) -> None:
        self._project = project_id
        self._http = http
        self._keys_url = keys_url
        self._keys: dict[str, Any] = {}
        self._keys_expire_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, id_token: str, *, now: float | None = None) -> FirebaseIdentity:
        now = time.time() if now is None else now
        failed = "Couldn't confirm your email. Please open the newest link we sent."
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise Unauthorized(failed) from exc
        if header.get("alg") != "RS256" or not header.get("kid"):
            raise Unauthorized(failed)
        key = await self._key(str(header["kid"]), now)
        try:
            claims = jwt.decode(
                id_token,
                key=key,
                algorithms=["RS256"],
                audience=self._project,
                issuer=f"https://securetoken.google.com/{self._project}",
                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iat": False},
                leeway=CLOCK_SKEW_SECONDS,
            )
        except jwt.PyJWTError as exc:
            log.info("Rejected Firebase ID token: %s", exc)
            raise Unauthorized(failed) from exc
        email = claims.get("email")
        if not email or claims.get("email_verified") not in (True, "true"):
            raise Unauthorized("This email address hasn't been verified yet.")
        return FirebaseIdentity(uid=str(claims["sub"]), email=str(email).lower())

    async def _key(self, kid: str, now: float) -> Any:
        if kid not in self._keys or now >= self._keys_expire_at:
            async with self._lock:
                if kid not in self._keys or now >= self._keys_expire_at:
                    await self._refresh(now)
        key = self._keys.get(kid)
        if key is None:
            raise Unauthorized("Couldn't confirm your email. Please try again.")
        return key

    async def _refresh(self, now: float) -> None:
        try:
            response = await self._http.get(self._keys_url)
            response.raise_for_status()
            jwks = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Can't reach Firebase right now. Please try again.") from exc
        self._keys = {
            jwk["kid"]: jwt.PyJWK.from_json(json.dumps(jwk)).key
            for jwk in jwks.get("keys", [])
            if jwk.get("kty") == "RSA" and jwk.get("kid")
        }
        match = re.search(r"max-age=(\d+)", response.headers.get("cache-control") or "")
        self._keys_expire_at = now + (int(match.group(1)) if match else DEFAULT_KEY_TTL_SECONDS)
