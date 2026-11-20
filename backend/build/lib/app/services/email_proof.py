"""Proving someone controls an email address (shop sign-up, technician invites).

1. We create a single-use challenge and a link `<page>?t=<token>`.
2. Our server asks Firebase (free) to send a "verify your email" message whose
   continue button leads to that link (integrations/firebase_email.py). The token
   is only ever in the email: it isn't returned to the browser that asked.
   Development without Firebase: the link is printed in the API window and shown
   on screen instead.
3. The person opens the email: Firebase marks the address verified. We check that
   with Firebase before accepting the token, so both the inbox (token) and
   Firebase (verified address) agree.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.config import Environment
from app.core.errors import AppError, NotFound, Unauthorized
from app.core.security import constant_time_equals, hash_token
from app.models import EmailChallenge

log = logging.getLogger(__name__)

TTL = {"shop_email": timedelta(hours=24), "tech_invite": timedelta(days=7)}


@dataclass(frozen=True, slots=True)
class EmailLink:
    email: str
    continue_url: str  # what Firebase puts in the email
    delivery: str  # firebase | development
    dev_link: str | None  # development only: open it to "click the email"


class EmailProofService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def start(
        self, *, purpose: str, subject_id: uuid.UUID, email: str, page_url: str
    ) -> EmailLink:
        settings = self.c.settings
        if not settings.firebase_enabled and settings.environment == Environment.PROD:
            raise AppError("Email links aren't set up (Firebase)", code="email_not_configured")
        now = self.c.clock.now()
        # A new link replaces older ones.
        await self.s.execute(
            update(EmailChallenge)
            .where(
                EmailChallenge.subject_id == subject_id,
                EmailChallenge.purpose == purpose,
                EmailChallenge.used_at.is_(None),
            )
            .values(used_at=now)
        )
        token = secrets.token_urlsafe(32)
        self.s.add(
            EmailChallenge(
                purpose=purpose,
                subject_id=subject_id,
                email=email.strip().lower(),
                token_hash=hash_token(token),
                expires_at=now + TTL[purpose],
            )
        )
        await self.s.flush()
        link = f"{page_url}?t={token}"
        if self.c.firebase is not None:
            await self.c.firebase.send_verification(email.strip().lower(), link)
            return EmailLink(email, "", "firebase", None)  # the link is only in the email
        log.warning("Email link for %s (development: no Firebase configured): %s", email, link)
        return EmailLink(email, link, "development", link)

    async def get(self, token: str, purpose: str | None = None) -> EmailChallenge:
        challenge = await self.s.scalar(
            select(EmailChallenge).where(EmailChallenge.token_hash == hash_token(token))
        )
        if (
            challenge is None
            or challenge.used_at is not None
            or challenge.expires_at <= self.c.clock.now()
            or (purpose and challenge.purpose != purpose)
        ):
            raise NotFound(
                "This link has expired or was already used. Ask for a new one.",
                code="link_expired",
            )
        return challenge

    async def prove(self, token: str, purpose: str) -> str:
        """The person opened the emailed link. Returns a claim secret for their browser."""
        challenge = await self.get(token, purpose)
        if self.c.firebase is not None:
            if not await self.c.firebase.is_verified(challenge.email):
                raise Unauthorized(
                    "Open the link in the email we sent (it confirms the address), then "
                    "continue from there.",
                    code="email_unverified",
                )
        elif self.c.settings.environment == Environment.PROD:
            raise AppError("Email links aren't set up (Firebase)", code="email_not_configured")
        claim = secrets.token_urlsafe(24)
        challenge.verified_at = self.c.clock.now()
        challenge.claim_hash = hash_token(claim)
        await self.s.flush()
        return claim

    async def consume(self, token: str, purpose: str, claim: str) -> EmailChallenge:
        challenge = await self.get(token, purpose)
        if (
            challenge.verified_at is None
            or challenge.claim_hash is None
            or not constant_time_equals(challenge.claim_hash, hash_token(claim))
        ):
            raise Unauthorized("Please confirm your email first.", code="email_unverified")
        challenge.used_at = self.c.clock.now()
        return challenge

    async def verified_elsewhere(
        self, subject_id: uuid.UUID, purpose: str
    ) -> EmailChallenge | None:
        """The address was verified in Firebase (e.g. on a phone) even though our page
        wasn't opened: used by the sign-up tab that's waiting."""
        if self.c.firebase is None:
            return None
        challenge = await self.s.scalar(
            select(EmailChallenge)
            .where(
                EmailChallenge.subject_id == subject_id,
                EmailChallenge.purpose == purpose,
                EmailChallenge.used_at.is_(None),
                EmailChallenge.expires_at > self.c.clock.now(),
            )
            .order_by(EmailChallenge.created_at.desc())
        )
        if challenge is None or not await self.c.firebase.is_verified(challenge.email):
            return None
        challenge.verified_at = self.c.clock.now()
        challenge.used_at = self.c.clock.now()
        return challenge

    def check_claim(self, challenge: EmailChallenge, claim: str) -> None:
        if (
            challenge.verified_at is None
            or challenge.claim_hash is None
            or not constant_time_equals(challenge.claim_hash, hash_token(claim))
        ):
            raise Unauthorized("Please confirm your email first.", code="email_unverified")
