"""Text messages via Twilio.

- Sign-in codes: Twilio Verify generates, sends and checks the code (it also
  handles delivery, retries and fraud screening, and doesn't need US A2P
  10DLC registration).
- Job updates (waitlist match, tech on the way, receipt): Twilio Messaging,
  from a Twilio number or a Messaging Service.

In local development without Twilio, ConsoleSmsSender prints messages to the
API window instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.errors import AppError, ExternalServiceError, RateLimited

log = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"
TWILIO_VERIFY_API = "https://verify.twilio.com/v2"

# Twilio error codes we turn into friendly messages.
_INVALID_NUMBER = {21211, 21614, 60200, 60205}
_TOO_MANY = {60203, 60212}
_BLOCKED = {60410, 60605}


class SmsSender(Protocol):
    async def send(self, *, to: str, body: str) -> None: ...


@dataclass
class ConsoleSmsSender:
    """Development only: prints texts to the API window."""

    outbox: list[tuple[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, body: str) -> None:
        self.outbox.append((to, body))
        if len(self.outbox) > 200:
            del self.outbox[:100]
        log.warning("SMS (not sent, Twilio not set up) to %s: %s", to, body)


class TwilioSmsSender:
    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        http: httpx.AsyncClient,
        from_number: str = "",
        messaging_service_sid: str = "",
        api_base: str = TWILIO_API,
    ) -> None:
        if not (from_number or messaging_service_sid):
            raise ValueError("Twilio needs a sending number or a Messaging Service SID")
        self._url = f"{api_base}/Accounts/{account_sid}/Messages.json"
        self._auth = (account_sid, auth_token)
        self._sender = (
            {"MessagingServiceSid": messaging_service_sid}
            if messaging_service_sid
            else {"From": from_number}
        )
        self._http = http

    async def send(self, *, to: str, body: str) -> None:
        try:
            response = await self._http.post(
                self._url, data={"To": to, "Body": body, **self._sender}, auth=self._auth
            )
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Couldn't send the text message") from exc
        if response.status_code >= 400:
            log.warning("Twilio send failed: %s %s", response.status_code, response.text[:300])
            raise ExternalServiceError("Couldn't send the text message")


class TwilioVerifyClient:
    """Twilio Verify: sends a one-time code by SMS and checks it."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        service_sid: str,
        http: httpx.AsyncClient,
        api_base: str = TWILIO_VERIFY_API,
    ) -> None:
        self._base = f"{api_base}/Services/{service_sid}"
        self._auth = (account_sid, auth_token)
        self._http = http

    async def start(self, phone: str) -> None:
        response = await self._post("Verifications", {"To": phone, "Channel": "sms"})
        if response.status_code >= 400:
            raise _verify_error(response)

    async def check(self, phone: str, code: str) -> bool:
        response = await self._post("VerificationCheck", {"To": phone, "Code": code})
        if response.status_code == 404:
            # No pending verification: expired, already used, or too many wrong tries.
            raise AppError("That code has expired. Please request a new one.", code="otp_expired")
        if response.status_code >= 400:
            raise _verify_error(response)
        return response.json().get("status") == "approved"

    async def _post(self, path: str, data: dict[str, str]) -> httpx.Response:
        try:
            return await self._http.post(f"{self._base}/{path}", data=data, auth=self._auth)
        except httpx.HTTPError as exc:
            log.warning("Twilio Verify unreachable: %s", exc)
            raise ExternalServiceError("Couldn't send the code. Please try again.") from exc


def _verify_error(response: httpx.Response) -> AppError:
    try:
        code = int(response.json().get("code") or 0)
    except ValueError:
        code = 0
    log.warning("Twilio Verify error %s: %s", response.status_code, response.text[:300])
    if code in _INVALID_NUMBER:
        return AppError("Please enter a valid mobile number", code="invalid_phone")
    if code in _TOO_MANY or response.status_code == 429:
        return RateLimited("Too many codes requested. Please try again later.")
    if code in _BLOCKED:
        return AppError("We can't send codes to this number", code="phone_blocked")
    return ExternalServiceError("Couldn't send the code. Please try again.")
