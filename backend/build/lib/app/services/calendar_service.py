"""Technician calendars: every booked job becomes an entry on the assigned tech's calendar.

Lifecycle of a job's calendar entry:
- homeowner confirms the booking → entry created ("Pending: …", no customer details yet)
- shop accepts → entry filled in with the customer's name, address and phone
- job declined / expired / canceled → entry removed
- job completed → entry trimmed to the actual finish time

The entries are shown on the shop's Availability board and published to each
tech's private calendar feed (.ics), which they can subscribe to from Google
Calendar, Apple Calendar or Outlook.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.domain.enums import AvailabilityKind
from app.models import AvailabilityBlock, Homeowner, ServiceRequest, Shop, Technician

JOB_SOURCE = "job"
FEED_PAST = timedelta(days=14)
FEED_FUTURE = timedelta(days=60)


class CalendarService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def book(self, request: ServiceRequest) -> AvailabilityBlock | None:
        """Put the job on the assigned tech's calendar (replacing any earlier entry)."""
        await self.release(request)
        if request.technician_id is None:
            return None
        now = self.c.clock.now()
        starts = max(request.eta_at or now, now)
        block = AvailabilityBlock(
            technician_id=request.technician_id,
            kind=AvailabilityKind.BUSY.value,
            starts_at=starts,
            ends_at=starts + timedelta(minutes=self.c.settings.default_job_duration_minutes),
            source=JOB_SOURCE,
            request_id=request.id,
        )
        self._describe(block, request, homeowner=None)
        self.s.add(block)
        await self.s.flush()
        return block

    async def confirm(self, request: ServiceRequest) -> None:
        """Shop accepted: reveal the customer's details on the tech's calendar entry."""
        block = await self._block_for(request)
        if block is None or block.technician_id != request.technician_id:
            block = await self.book(request)
        if block is None:
            return
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        self._describe(block, request, homeowner=homeowner)

    async def release(self, request: ServiceRequest) -> None:
        await self.s.execute(
            delete(AvailabilityBlock).where(
                AvailabilityBlock.request_id == request.id,
                AvailabilityBlock.source == JOB_SOURCE,
            )
        )

    async def finish(self, request: ServiceRequest) -> None:
        block = await self._block_for(request)
        if block is not None:
            now = self.c.clock.now()
            block.ends_at = max(now, block.starts_at + timedelta(minutes=5))
            block.label = f"Done: {block.label or 'HVAC job'}"[:120]

    async def _block_for(self, request: ServiceRequest) -> AvailabilityBlock | None:
        return await self.s.scalar(
            select(AvailabilityBlock).where(
                AvailabilityBlock.request_id == request.id,
                AvailabilityBlock.source == JOB_SOURCE,
            )
        )

    @staticmethod
    def _describe(
        block: AvailabilityBlock, request: ServiceRequest, homeowner: Homeowner | None
    ) -> None:
        issue = (request.diagnosis or {}).get("primary_issue_label") or "HVAC service"
        if homeowner is None:
            block.label = f"Pending: {issue}"[:120]
            block.details = "Waiting for the shop to accept. Customer details appear once accepted."
            return
        street = (request.address or "").split(",")[0]
        who = homeowner.name or "Customer"
        block.label = f"{who} · {street}"[:120] if street else who[:120]
        unit = request.unit_info or {}
        lines = [
            f"Customer: {who}",
            f"Phone: {homeowner.phone or 'not provided'}",
            f"Address: {request.address or 'not provided'}",
            f"Likely issue: {issue}",
        ]
        if unit.get("brand") or unit.get("model_number"):
            lines.append(
                f"Unit: {unit.get('brand') or ''} {unit.get('model_number') or ''}".strip()
            )
        if request.description:
            lines.append(f"Notes: {request.description}")
        block.details = "\n".join(lines)[:4000]

    # --- Calendar feed --------------------------------------------------------------
    async def feed_token(self, tech: Technician, *, rotate: bool = False) -> str:
        if rotate or not tech.calendar_token:
            tech.calendar_token = secrets.token_urlsafe(32)
            await self.s.flush()
        return tech.calendar_token

    def feed_url(self, token: str) -> str:
        base = self.c.settings.public_api_url.rstrip("/")
        return f"{base}{self.c.settings.api_prefix}/calendar/{token}.ics"

    async def ics_for_token(self, token: str) -> str | None:
        tech = await self.s.scalar(select(Technician).where(Technician.calendar_token == token))
        if tech is None:
            return None
        shop = await self.s.get(Shop, tech.shop_id)
        now = self.c.clock.now()
        rows = await self.s.scalars(
            select(AvailabilityBlock)
            .where(
                AvailabilityBlock.technician_id == tech.id,
                AvailabilityBlock.kind == AvailabilityKind.BUSY.value,
                AvailabilityBlock.ends_at > now - FEED_PAST,
                AvailabilityBlock.starts_at < now + FEED_FUTURE,
            )
            .order_by(AvailabilityBlock.starts_at)
        )
        return render_ics(
            name=f"{tech.name} · {shop.name if shop else 'HVAC jobs'}",
            blocks=list(rows),
            stamp=now,
        )


def render_ics(*, name: str, blocks: list[AvailabilityBlock], stamp: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//HVAC Connect//Technician calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT15M",
        "X-PUBLISHED-TTL:PT15M",
    ]
    for block in blocks:
        request_ref = block.request_id or block.id
        event = [
            "BEGIN:VEVENT",
            f"UID:{request_ref}@hvac-connect",
            f"DTSTAMP:{_ics_time(stamp)}",
            f"DTSTART:{_ics_time(block.starts_at)}",
            f"DTEND:{_ics_time(block.ends_at)}",
            f"SUMMARY:{_escape(block.label or 'Busy')}",
        ]
        if block.details:
            event.append(f"DESCRIPTION:{_escape(block.details)}")
            for detail in block.details.splitlines():
                if detail.startswith("Address: ") and "not provided" not in detail:
                    event.append(f"LOCATION:{_escape(detail.removeprefix('Address: '))}")
        event.append("END:VEVENT")
        lines.extend(event)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def _ics_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets continue on the next line after a space."""
    data = line.encode()
    if len(data) <= 75:
        return line
    parts: list[str] = []
    current = b""
    for ch in line:
        encoded = ch.encode()
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode())
            current = b""
        current += encoded
    parts.append(current.decode())
    return "\r\n ".join(parts)
