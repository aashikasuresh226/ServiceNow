"""Homeowner complaints about a technician.

A homeowner can file one complaint per job, from when a technician is assigned until 30
days after the job is done. It goes to the company (portal: Complaints) and to the
platform admin (portal: /admin, plus a text to HVAC_ADMIN_PHONE if set). The technician
never sees it. The company can reply (the homeowner sees the reply) and mark it resolved;
the admin can add a private note and resolve or reopen it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.domain.enums import RequestStatus
from app.models import Complaint, ServiceRequest

log = logging.getLogger(__name__)

S = RequestStatus
CATEGORIES = {
    "late": "Late or didn't show up",
    "unprofessional": "Rude or unprofessional",
    "poor_work": "Poor quality work",
    "pricing": "Overcharged or price changed",
    "damage": "Damaged my property",
    "safety": "Made me feel unsafe",
    "other": "Something else",
}
OPEN_FOR = timedelta(days=30)
ASSIGNED = {
    s.value for s in (S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS, S.COMPLETED)
}


def can_complain(request: ServiceRequest, now: object) -> bool:
    if request.technician_id is None:
        return False
    if request.status == S.CANCELED.value:
        return request.technician_id is not None  # e.g. a no-show the shop canceled
    if request.status not in ASSIGNED:
        return False
    if request.status == S.COMPLETED.value and request.completed_at is not None:
        return bool(now < request.completed_at + OPEN_FOR)  # type: ignore[operator]
    return True


class ComplaintService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def for_request(self, request_id: uuid.UUID) -> Complaint | None:
        return await self.s.scalar(select(Complaint).where(Complaint.request_id == request_id))

    async def file(self, request: ServiceRequest, *, category: str, details: str) -> Complaint:
        if category not in CATEGORIES:
            raise AppError("Choose what went wrong", code="invalid_category")
        text = details.strip()
        if len(text) < 10:
            raise AppError("Tell us a little more (at least 10 characters)", code="too_short")
        if not can_complain(request, self.c.clock.now()):
            raise InvalidState(
                "You can report a technician once one is assigned, up to 30 days after the job.",
                code="complaint_closed",
            )
        if await self.for_request(request.id) is not None:
            raise InvalidState("You already reported a problem with this job.", code="duplicate")
        self.c.rate_limiter.check(
            "complaint", str(request.homeowner_id), limit=5, window_seconds=86400
        )
        assert request.shop_id is not None
        complaint = Complaint(
            request_id=request.id,
            homeowner_id=request.homeowner_id,
            shop_id=request.shop_id,
            technician_id=request.technician_id,
            category=category,
            details=text[:2000],
        )
        self.s.add(complaint)
        await self.s.flush()
        await self._tell_admin(complaint)
        return complaint

    async def _tell_admin(self, complaint: Complaint) -> None:
        log.warning(
            "New complaint %s (%s) for shop %s", complaint.id, complaint.category, complaint.shop_id
        )
        phone = self.c.settings.admin_phone.strip()
        if phone and self.c.sms is not None:
            try:
                await self.c.sms.send(
                    to=phone,
                    body=f"HVAC Connect: new complaint ({CATEGORIES[complaint.category]}). "
                    "Open /admin in the shop portal to read it.",
                )
            except Exception:
                log.exception("Couldn't text the admin about complaint %s", complaint.id)

    # --- Company ------------------------------------------------------------------------------
    async def for_shop(self, shop_id: uuid.UUID) -> list[Complaint]:
        rows = await self.s.scalars(
            select(Complaint)
            .where(Complaint.shop_id == shop_id)
            .order_by(Complaint.status, Complaint.created_at.desc())
            .limit(500)
        )
        return list(rows)

    async def respond(
        self, shop_id: uuid.UUID, complaint_id: uuid.UUID, *, response: str, resolved: bool
    ) -> Complaint:
        complaint = await self.s.get(Complaint, complaint_id)
        if complaint is None or complaint.shop_id != shop_id:
            raise NotFound("Complaint not found")
        text = response.strip()
        if text:
            complaint.shop_response = text[:2000]
            complaint.shop_responded_at = self.c.clock.now()
        if resolved and complaint.status != "resolved":
            complaint.status = "resolved"
            complaint.resolved_at = self.c.clock.now()
            complaint.resolved_by = "shop"
        await self.s.flush()
        return complaint

    # --- Platform admin -----------------------------------------------------------------------
    async def all(self, status: str | None = None) -> list[Complaint]:
        query = select(Complaint).order_by(Complaint.created_at.desc()).limit(1000)
        if status:
            query = query.where(Complaint.status == status)
        return list(await self.s.scalars(query))

    async def admin_update(
        self, complaint_id: uuid.UUID, *, note: str | None, status: str | None
    ) -> Complaint:
        complaint = await self.s.get(Complaint, complaint_id)
        if complaint is None:
            raise NotFound("Complaint not found")
        if note is not None:
            complaint.admin_note = note.strip()[:2000] or None
        if status in ("open", "resolved") and status != complaint.status:
            complaint.status = status
            complaint.resolved_at = self.c.clock.now() if status == "resolved" else None
            complaint.resolved_by = "admin" if status == "resolved" else None
        await self.s.flush()
        return complaint
