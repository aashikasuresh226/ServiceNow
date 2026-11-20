"""Chat between a homeowner and the shop handling their job.

Open from when the shop accepts the job until 48 hours after it's completed.
The shop office can always read and write; the technician only if the company
allows them to contact customers. Messages are encrypted in the database.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState
from app.domain.enums import RequestStatus
from app.models import Homeowner, Message, ServiceRequest, Technician
from app.services.notifications import notify_homeowner

S = RequestStatus
CHAT_STATUSES = {
    s.value for s in (S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS, S.COMPLETED)
}
AFTER_JOB = timedelta(hours=48)
MAX_LENGTH = 1000


def chat_open(request: ServiceRequest, now: object) -> bool:
    if request.status not in CHAT_STATUSES:
        return False
    if request.status == S.COMPLETED.value:
        return bool(request.completed_at and now < request.completed_at + AFTER_JOB)  # type: ignore[operator]
    return True


def technician_can_contact(tech: Technician | None) -> bool:
    return bool(tech and tech.app_status == "active" and tech.can_contact_customers)


@dataclass(frozen=True, slots=True)
class Unread:
    request_id: uuid.UUID
    count: int
    sender_name: str | None
    preview: str
    last_at: datetime


class MessageService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def list(self, request: ServiceRequest) -> list[Message]:
        rows = await self.s.scalars(
            select(Message)
            .where(Message.request_id == request.id)
            .order_by(Message.created_at)
            .limit(500)
        )
        return list(rows)

    async def mark_read_by_homeowner(self, request: ServiceRequest) -> None:
        # Marked by the newest message's own timestamp, so "unread" compares like with like.
        newest = await self.s.scalar(
            select(func.max(Message.created_at)).where(Message.request_id == request.id)
        )
        if newest is not None and (
            request.homeowner_read_at is None or newest > request.homeowner_read_at
        ):
            request.homeowner_read_at = newest
            await self.s.flush()

    async def unread_for_homeowner(self, homeowner_id: uuid.UUID) -> Sequence[Unread]:
        """Messages from the company or technician the homeowner hasn't opened yet."""
        since = self.c.clock.now() - timedelta(days=14)
        rows = (
            await self.s.execute(
                select(Message, ServiceRequest.homeowner_read_at)
                .join(ServiceRequest, ServiceRequest.id == Message.request_id)
                .where(
                    ServiceRequest.homeowner_id == homeowner_id,
                    Message.sender != "homeowner",
                    Message.created_at >= since,
                )
                .order_by(Message.created_at)
            )
        ).all()
        found: dict[uuid.UUID, Unread] = {}
        for message, read_at in rows:
            if read_at is not None and message.created_at <= read_at:
                continue
            before = found.get(message.request_id)
            text = message.body if len(message.body) <= 90 else message.body[:87] + "..."
            found[message.request_id] = Unread(
                message.request_id,
                (before.count if before else 0) + 1,
                message.sender_name,
                text,
                message.created_at,
            )
        return sorted(found.values(), key=lambda u: u.last_at, reverse=True)

    async def _has_unread(self, request: ServiceRequest, before: Message) -> bool:
        query = (
            select(func.count())
            .select_from(Message)
            .where(
                Message.request_id == request.id,
                Message.sender != "homeowner",
                Message.id != before.id,
            )
        )
        if request.homeowner_read_at is not None:
            query = query.where(Message.created_at > request.homeowner_read_at)
        return bool(await self.s.scalar(query))

    async def post(
        self, request: ServiceRequest, *, sender: str, sender_name: str | None, body: str
    ) -> Message:
        text = body.strip()
        if not text:
            raise AppError("Type a message", code="empty_message")
        if len(text) > MAX_LENGTH:
            raise AppError(f"Messages can be up to {MAX_LENGTH} characters", code="too_long")
        if not chat_open(request, self.c.clock.now()):
            raise InvalidState("Chat is closed for this job", code="chat_closed")
        self.c.rate_limiter.check("chat", f"{request.id}:{sender}", limit=60, window_seconds=600)
        message = Message(request_id=request.id, sender=sender, sender_name=sender_name, body=text)
        self.s.add(message)
        await self.s.flush()
        if sender == "homeowner":
            request.homeowner_read_at = message.created_at  # replying means they've read it
        elif not await self._has_unread(request, message):
            # One text per conversation burst: only when this is the first unread message.
            homeowner = await self.s.get(Homeowner, request.homeowner_id)
            if homeowner:
                who = sender_name or "Your technician"
                await notify_homeowner(
                    self.c, homeowner, f"New message from {who}. Open the app to reply."
                )
        return message
