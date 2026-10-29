"""Text messages: one-time codes and job notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.core.errors import ExternalServiceError

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    async def send(self, *, to: str, body: str) -> None: ...


@dataclass
class ConsoleSmsSender:
    """Prints messages to the server log and keeps them for tests / the demo panel."""

    outbox: list[tuple[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, body: str) -> None:
        self.outbox.append((to, body))
        if len(self.outbox) > 200:
            del self.outbox[:100]
        log.warning("SMS to %s: %s", to, body)


class TwilioSmsSender:
    def __init__(
        self, *, account_sid: str, auth_token: str, from_number: str, http: httpx.AsyncClient
    ) -> None:
        self._url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        self._auth = (account_sid, auth_token)
        self._from = from_number
        self._http = http

    async def send(self, *, to: str, body: str) -> None:
        try:
            response = await self._http.post(
                self._url, data={"To": to, "From": self._from, "Body": body}, auth=self._auth
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Twilio send failed: %s", exc)
            raise ExternalServiceError("Couldn't send the text message") from exc
