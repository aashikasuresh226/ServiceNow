"""Sends "verify your email" messages with Firebase Authentication (free plan: 1,000 a day)
and checks whether the address was verified. Everything runs from our server through
Firebase's REST API (Identity Toolkit) with the project's Web API key:

1. accounts:signUp (or accounts:signInWithPassword if the address already exists) for a
   Firebase user with that email. Its password is derived from our secret key and never
   used for anything else: our own accounts have their own sign-in.
2. accounts:sendOobCode VERIFY_EMAIL with a continue URL (our page, with a single-use
   token). Firebase emails the link; opening it marks the address verified, then offers a
   "Continue" button back to our page.
3. accounts:lookup tells us whether the address is verified now.

(Firebase's "email link sign-in" is limited to 5 emails a day on the free plan, so we
don't use it.)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.errors import AppError, ExternalServiceError

log = logging.getLogger(__name__)

API_BASE = "https://identitytoolkit.googleapis.com/v1"


class FirebaseEmailSender:
    def __init__(
        self, *, api_key: str, secret: str, http: httpx.AsyncClient, api_base: str = API_BASE
    ) -> None:
        self._key = api_key
        self._secret = secret.encode()
        self._http = http
        self._base = api_base

    def _password(self, email: str) -> str:
        digest = hmac.new(self._secret, f"firebase:{email.lower()}".encode(), hashlib.sha256)
        return base64.urlsafe_b64encode(digest.digest()).decode()[:32]

    async def send_verification(self, email: str, continue_url: str) -> None:
        id_token = await self._id_token(email, create=True)
        await self._call(
            "accounts:sendOobCode",
            {"requestType": "VERIFY_EMAIL", "idToken": id_token, "continueUrl": continue_url},
        )

    async def is_verified(self, email: str) -> bool:
        try:
            id_token = await self._id_token(email, create=False)
        except _NotFound:
            return False
        body = await self._call("accounts:lookup", {"idToken": id_token})
        users = body.get("users") or [{}]
        return bool(users[0].get("emailVerified"))

    async def _id_token(self, email: str, *, create: bool) -> str:
        password = self._password(email)
        if create:
            try:
                body = await self._call(
                    "accounts:signUp",
                    {"email": email, "password": password, "returnSecureToken": True},
                )
                return str(body["idToken"])
            except _FirebaseError as exc:
                if exc.code != "EMAIL_EXISTS":
                    raise AppError(_message(exc.code), code="firebase_error") from exc
        try:
            body = await self._call(
                "accounts:signInWithPassword",
                {"email": email, "password": password, "returnSecureToken": True},
            )
        except _FirebaseError as exc:
            if exc.code == "EMAIL_NOT_FOUND" and not create:
                raise _NotFound(exc.code) from exc
            if exc.code in ("INVALID_PASSWORD", "INVALID_LOGIN_CREDENTIALS") and create:
                raise AppError(
                    f"{email} already exists in Firebase from an earlier setup. In the Firebase "
                    "console open Authentication > Users, delete it, then send the link again.",
                    code="firebase_user_exists",
                ) from exc
            raise AppError(_message(exc.code), code="firebase_error") from exc
        return str(body["idToken"])

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.post(
                f"{self._base}/{method}", params={"key": self._key}, json=payload, timeout=15.0
            )
        except httpx.HTTPError as exc:
            log.warning("Firebase %s unreachable: %s", method, exc)
            raise ExternalServiceError("Can't reach Firebase right now. Please try again.") from exc
        if response.status_code >= 400:
            try:
                message = str(response.json()["error"]["message"])
            except (ValueError, KeyError, TypeError):
                message = f"HTTP_{response.status_code}"
            code = message.split(" ")[0].split(":")[0].strip()
            log.warning("Firebase %s failed: %s", method, message)
            raise _FirebaseError(code)
        body = response.json()
        return body if isinstance(body, dict) else {}


class _FirebaseError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NotFound(_FirebaseError):
    pass


def _message(code: str) -> str:
    """Plain-language fixes for Firebase setup problems."""
    if code == "OPERATION_NOT_ALLOWED":
        return (
            "Turn on Email/Password in Firebase console > Authentication > Sign-in method, "
            "then try again."
        )
    if code in ("API_KEY_INVALID", "INVALID_API_KEY") or code.startswith("API"):
        return "Firebase rejected the API key. Check HVAC_FIREBASE_API_KEY (Project settings)."
    if code in ("UNAUTHORIZED_DOMAIN", "INVALID_CONTINUE_URI", "UNAUTHORIZED_CONTINUE_URI"):
        return (
            "Add this website's domain in Firebase console > Authentication > Settings > "
            "Authorized domains (localhost is there by default)."
        )
    if code in ("QUOTA_EXCEEDED", "TOO_MANY_ATTEMPTS_TRY_LATER", "RESET_PASSWORD_EXCEED_LIMIT"):
        return "Firebase's email limit was reached for now. Please try again later."
    if code == "CONFIGURATION_NOT_FOUND":
        return "Click 'Get started' in Firebase console > Authentication first."
    if code in ("INVALID_PASSWORD", "INVALID_LOGIN_CREDENTIALS", "EMAIL_NOT_FOUND"):
        return "Firebase couldn't find this email yet. Send the link again."
    if code in ("INVALID_EMAIL", "MISSING_EMAIL"):
        return "Firebase says this email address isn't valid."
    if code == "USER_DISABLED":
        return "This email is disabled in Firebase (Authentication > Users)."
    return f"Firebase couldn't send the email ({code})."
