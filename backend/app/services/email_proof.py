"""Proving someone controls an email address (shop sign-up, technician invites).

1. We create a single-use challenge and a link `<page>?t=<token>`.
2. Firebase (free) emails the link: the browser calls Firebase's
   sendSignInLinkToEmail with it. Development without Firebase: the link is
   printed in the API window and shown on screen instead.
3. The person opens the link; the page finishes Firebase's email-link sign-in and
   sends us the Firebase ID token. We check the token's verified email equals the
   challenge's email. Only then is the address proven.

The token alone is not proof when Firebase is on (the browser that asked for the
email knows it); the Firebase ID token is.
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
        if settings.firebase_enabled:
            return EmailLink(email, link, "firebase", None)
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

    async def prove(self, token: str, purpose: str, firebase_id_token: str | None) -> str:
        """Check the Firebase proof. Returns a claim secret for the browser that proved it."""
        challenge = await self.get(token, purpose)
        if self.c.firebase is not None:
            if not firebase_id_token:
                raise Unauthorized("Open the link from your email to continue.", code="no_proof")
            identity = await self.c.firebase.verify(firebase_id_token)
            if identity.email != challenge.email.lower():
                raise Unauthorized(
                    "That link was for a different email address.", code="email_mismatch"
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

    def check_claim(self, challenge: EmailChallenge, claim: str) -> None:
        if (
            challenge.verified_at is None
            or challenge.claim_hash is None
            or not constant_time_equals(challenge.claim_hash, hash_token(claim))
        ):
            raise Unauthorized("Please confirm your email first.", code="email_unverified")
