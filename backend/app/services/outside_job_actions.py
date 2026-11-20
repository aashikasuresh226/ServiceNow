"""A technician runs a Housecall Pro job from our app; everything is sent to Housecall Pro.

What Housecall Pro's public API accepts, and how each action reaches it:
- line items (the work and prices)  -> POST /jobs/{id}/line_items (money in cents)
- photos                            -> POST /jobs/{id}/attachments (multipart)
- notes                             -> POST /jobs/{id}/notes
- On my way / Arrived / Started / Finished: the API has no route to change a job's status,
  so each step is written to the job as a timestamped note ("On my way, 2:05 PM"), and the
  office finishes and invoices the job in Housecall Pro as usual.

Actions are saved first (ExternalJobEvent) and sent right away; if Housecall Pro can't be
reached they stay queued and the worker retries them in order.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.integrations.storage import sniff_image_type
from app.models import ExternalJob, ExternalJobEvent, Homeowner, Shop, ShopCustomer, Technician
from app.services.notifications import notify_homeowner

log = logging.getLogger(__name__)

# step -> (status after it, statuses it may follow, note label)
STEPS: dict[str, tuple[str, set[str], str]] = {
    "on_my_way": ("en_route", {""}, "On my way"),
    "arrived": ("on_site", {"", "en_route"}, "Arrived"),
    "started": ("working", {"", "en_route", "on_site"}, "Started work"),
    "finished": ("finished", {"on_site", "working"}, "Finished work"),
}
STAMP = {
    "on_my_way": "on_my_way_at",
    "arrived": "arrived_at",
    "started": "started_at",
    "finished": "finished_at",
}
MAX_ATTEMPTS = {"photo": 3}  # an upload may have landed even when it reported an error
DEFAULT_MAX_ATTEMPTS = 10
SOURCE = "sent from HVAC Connect"


@dataclass(frozen=True, slots=True)
class LineItem:
    name: str
    quantity: float
    unit_price_cents: int


class OutsideJobActions:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    # --- Recording ----------------------------------------------------------------------------
    async def _job(self, tech: Technician, job_id: uuid.UUID) -> ExternalJob:
        job = await self.s.get(ExternalJob, job_id)
        if job is None or job.technician_id != tech.id:
            raise NotFound("Job not found")
        return job

    async def step(
        self, tech: Technician, job_id: uuid.UUID, step: str, summary: str | None = None
    ) -> ExternalJob:
        job = await self._job(tech, job_id)
        if step not in STEPS:
            raise AppError("Unknown step", code="invalid_step")
        status, allowed, _label = STEPS[step]
        if job.app_status not in allowed:
            raise InvalidState("That step was already done or doesn't apply now.")
        now = self.c.clock.now()
        job.app_status = status
        setattr(job, STAMP[step], now)
        payload = {"step": step, "at": now.isoformat(), "by": tech.name}
        if summary and summary.strip():
            payload["summary"] = summary.strip()[:2000]
        await self._queue(job, tech, "status", json.dumps(payload))
        if step == "on_my_way":
            await self._tell_customer(job, tech)
        return job

    async def add_line_item(self, tech: Technician, job_id: uuid.UUID, item: LineItem) -> None:
        job = await self._job(tech, job_id)
        name = item.name.strip()
        if not name:
            raise AppError("Name the work or part", code="invalid_item")
        if not 0 < item.quantity <= 1000:
            raise AppError("Quantity must be between 0 and 1,000", code="invalid_item")
        if not 0 <= item.unit_price_cents <= 10_000_000:
            raise AppError("Price must be between $0 and $100,000", code="invalid_item")
        payload = {
            "name": name[:120],
            "quantity": item.quantity,
            "unit_price_cents": item.unit_price_cents,
        }
        await self._queue(job, tech, "line_item", json.dumps(payload))

    async def add_note(self, tech: Technician, job_id: uuid.UUID, text: str) -> None:
        job = await self._job(tech, job_id)
        body = text.strip()
        if not body:
            raise AppError("Type a note", code="empty_note")
        await self._queue(job, tech, "note", body[:2000])

    async def add_photo(self, tech: Technician, job_id: uuid.UUID, data: bytes) -> None:
        job = await self._job(tech, job_id)
        if len(data) > self.c.settings.max_photo_bytes:
            raise AppError("Photo is too large (max 10 MB)", code="photo_too_large")
        content_type = sniff_image_type(data)
        if content_type is None:
            raise AppError("Please upload a JPEG, PNG, WebP or GIF photo", code="invalid_photo")
        key = await self.c.storage.save(data, content_type)
        await self._queue(job, tech, "photo", json.dumps({"key": key, "type": content_type}))

    async def events(self, job_id: uuid.UUID) -> list[ExternalJobEvent]:
        rows = await self.s.scalars(
            select(ExternalJobEvent)
            .where(ExternalJobEvent.job_id == job_id)
            .order_by(ExternalJobEvent.created_at)
        )
        return list(rows)

    async def _queue(self, job: ExternalJob, tech: Technician, kind: str, payload: str) -> None:
        self.c.rate_limiter.check("hcp-action", str(tech.id), limit=120, window_seconds=600)
        event = ExternalJobEvent(job_id=job.id, technician_id=tech.id, kind=kind, payload=payload)
        self.s.add(event)
        await self.s.flush()
        await self.send_pending(job)  # right away; the worker retries what fails

    async def _tell_customer(self, job: ExternalJob, tech: Technician) -> None:
        """If the customer uses our app, text them that the technician is on the way."""
        if job.customer_id is None:
            return
        customer = await self.s.get(ShopCustomer, job.customer_id)
        if customer is None or customer.homeowner_id is None:
            return
        homeowner = await self.s.get(Homeowner, customer.homeowner_id)
        shop = await self.s.get(Shop, job.shop_id)
        if homeowner is not None and shop is not None:
            first = tech.name.split(" ")[0]
            await notify_homeowner(self.c, homeowner, f"{first} from {shop.name} is on the way.")

    # --- Sending ------------------------------------------------------------------------------
    async def send_pending(self, job: ExternalJob) -> int:
        """Send this job's queued actions in order; stop at the first failure (order matters:
        "Finished" shouldn't land before the line items it summarizes)."""
        from app.services.external_jobs import ExternalJobService  # import cycle

        shop = await self.s.get(Shop, job.shop_id)
        client = ExternalJobService(self.s, self.c)._client(shop) if shop else None
        pending = [e for e in await self.events(job.id) if e.sent_at is None]
        if client is None:
            for event in pending:
                event.error = "Housecall Pro isn't connected"
            return 0
        sent = 0
        tz = ZoneInfo(shop.timezone) if shop and shop.timezone else ZoneInfo("America/New_York")
        for event in pending:
            if event.attempts >= MAX_ATTEMPTS.get(event.kind, DEFAULT_MAX_ATTEMPTS):
                break  # given up: shown as "Not sent" in the app; later events wait behind it
            event.attempts += 1
            try:
                await self._send(client, job, event, tz)
            except AppError as exc:
                event.error = exc.message[:300]
                log.warning(
                    "Housecall Pro action %s for job %s failed: %s", event.id, job.id, exc.message
                )
                break
            event.sent_at = self.c.clock.now()
            event.error = None
            sent += 1
        await self.s.flush()
        return sent

    async def _send(
        self, client: Any, job: ExternalJob, event: ExternalJobEvent, tz: ZoneInfo
    ) -> None:
        tech = await self.s.get(Technician, event.technician_id) if event.technician_id else None
        who = tech.name if tech else "Technician"
        if event.kind == "status":
            data = json.loads(event.payload)
            at = datetime.fromisoformat(data["at"]).astimezone(tz)
            label = STEPS[data["step"]][2]
            clock = f"{at.hour % 12 or 12}:{at:%M %p}"  # no %-I: it isn't supported on Windows
            text = f"{label}, {clock} - {data.get('by') or who} ({SOURCE})"
            if data.get("summary"):
                text += f"\nWork done: {data['summary']}"
            if data["step"] == "finished":
                text += "\nFinish and invoice this job in Housecall Pro."
            await client.add_note(job.external_id, text)
        elif event.kind == "note":
            await client.add_note(job.external_id, f"{who}: {event.payload} ({SOURCE})")
        elif event.kind == "line_item":
            data = json.loads(event.payload)
            await client.add_line_item(
                job.external_id,
                name=data["name"],
                quantity=data["quantity"],
                unit_price_cents=data["unit_price_cents"],
            )
        elif event.kind == "photo":
            data = json.loads(event.payload)
            body = await self.c.storage.read(data["key"])
            extension = data["type"].split("/")[-1].replace("jpeg", "jpg")
            await client.upload_attachment(
                job.external_id,
                filename=f"photo-{event.created_at:%Y%m%d-%H%M%S}.{extension}",
                data=body,
                content_type=data["type"],
            )

    async def retry_all(self, limit: int = 50) -> int:
        """Worker: send what couldn't be sent (Housecall Pro was down, rate limited...)."""
        job_ids = list(
            dict.fromkeys(
                await self.s.scalars(
                    select(ExternalJobEvent.job_id)
                    .where(
                        ExternalJobEvent.sent_at.is_(None),
                        ExternalJobEvent.attempts < DEFAULT_MAX_ATTEMPTS,
                    )
                    .order_by(ExternalJobEvent.created_at)
                    .limit(limit)
                )
            )
        )
        sent = 0
        for job_id in job_ids:
            job = await self.s.get(ExternalJob, job_id)
            if job is not None:
                sent += await self.send_pending(job)
        return sent

    async def hcp_line_items(self, job: ExternalJob) -> list[dict[str, Any]] | None:
        """The job's line items as Housecall Pro has them (None if it can't be reached)."""
        from app.services.external_jobs import ExternalJobService  # import cycle

        shop = await self.s.get(Shop, job.shop_id)
        client = ExternalJobService(self.s, self.c)._client(shop) if shop else None
        if client is None:
            return None
        try:
            rows = await client.line_items(job.external_id)
        except AppError:
            return None
        items = []
        for row in rows:
            try:
                quantity = float(row.get("quantity") or 1)
                unit = int(row.get("unit_price") or 0)
            except (TypeError, ValueError):
                continue
            items.append(
                {
                    "name": str(row.get("name") or "Item"),
                    "quantity": quantity,
                    "unit_price_cents": unit,
                    "total_cents": round(quantity * unit),
                }
            )
        return items
