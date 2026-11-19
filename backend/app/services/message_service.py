"""Chat between a homeowner and the shop handling their job.

Open from when the shop accepts the job until 48 hours after it's completed.
The shop office can always read and write; the technician only if the company
allows them to contact customers. Messages are encrypted in the database.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
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
        if sender != "homeowner":
            homeowner = await self.s.get(Homeowner, request.homeowner_id)
            if homeowner:
                who = sender_name or "Your technician"
                await notify_homeowner(
                    self.c, homeowner, f"New message from {who}. Open the app to reply."
                )
        return message
