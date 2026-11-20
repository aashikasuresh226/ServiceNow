"""Keeps Housecall Pro in step with jobs booked through our app, for every shop that has
Housecall Pro connected (whatever its dispatch mode), so the office and customers see the
same job in both places.

When the shop accepts a job, it's created in Housecall Pro (customer matched by phone,
technician assigned when known). Then every step is added to that job:
- On the way / Arrived                    -> timestamped notes
- the price the customer approved         -> a line item (the job total in Housecall Pro)
- Completed (and whether the card was charged in our app) -> a note
- Canceled                                -> a note, and the visit is taken off the schedule
Housecall Pro's public API can't set a job's status, so the steps are notes; the office
closes and invoices the job in Housecall Pro.

Updates are queued (ExternalJobEvent with request_id) and sent in order. If Housecall Pro
can't be reached, or the job hasn't been created there yet, they wait and the worker retries.
Each send is written to the shop's Housecall Pro activity log.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError
from app.domain.enums import SchedulingProvider
from app.models import ExternalJobEvent, Homeowner, ServiceRequest, Shop, Technician
from app.services import integration_log

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 10
SOURCE = "HVAC Connect"
LABELS = {
    "en_route": "On my way",
    "on_site": "Arrived",
    "quote_approved": "Customer approved the price",
    "completed": "Job finished",
    "canceled": "Canceled",
}


def connected(shop: Shop | None) -> bool:
    return bool(
        shop
        and shop.scheduling_provider == SchedulingProvider.HOUSECALL_PRO.value
        and shop.scheduling_credentials_encrypted
    )


def _clock(at: datetime, tz: ZoneInfo) -> str:
    local = at.astimezone(tz)
    return f"{local.hour % 12 or 12}:{local:%M %p}"  # no %-I: not supported on Windows


class HcpMirror:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def record(self, request: ServiceRequest, event: str, **data: Any) -> None:
        """Queue an update for this job's Housecall Pro copy and try to send it now."""
        shop = await self.s.get(Shop, request.shop_id) if request.shop_id else None
        if not connected(shop):
            return
        assert shop is not None
        tech = (
            await self.s.get(Technician, request.technician_id) if request.technician_id else None
        )
        payload = {
            "event": event,
            "at": self.c.clock.now().isoformat(),
            "by": tech.name if tech else None,
            "shop_id": str(shop.id),  # a canceled job loses its shop_id
            **data,
        }
        self.s.add(
            ExternalJobEvent(
                request_id=request.id,
                technician_id=tech.id if tech else None,
                kind="request",
                payload=json.dumps(payload),
            )
        )
        await self.s.flush()
        await self.send_pending(request, shop)

    async def send_pending(self, request: ServiceRequest, shop: Shop | None = None) -> int:
        from app.services.external_jobs import ExternalJobService  # import cycle

        pending = list(
            await self.s.scalars(
                select(ExternalJobEvent)
                .where(
                    ExternalJobEvent.request_id == request.id, ExternalJobEvent.sent_at.is_(None)
                )
                .order_by(ExternalJobEvent.created_at)
            )
        )
        if shop is None and pending:
            shop_id = request.shop_id or uuid.UUID(json.loads(pending[0].payload)["shop_id"])
            shop = await self.s.get(Shop, shop_id)
        service = ExternalJobService(self.s, self.c)
        client = service._client(shop) if shop else None
        if not pending or client is None or shop is None:
            return 0
        if not request.external_job_id:
            if request.shop_id is None:  # canceled before it ever reached Housecall Pro
                for event in pending:
                    event.sent_at = self.c.clock.now()
                return 0
            await service.push(request, shop)  # create it in Housecall Pro first
            if not request.external_job_id:
                for event in pending:
                    event.error = (request.external_error or "Waiting for the job to be created")[
                        :300
                    ]
                return 0
        tz = ZoneInfo(shop.timezone or "America/New_York")
        sent = 0
        for event in pending:
            if event.attempts >= MAX_ATTEMPTS:
                break
            event.attempts += 1
            data = json.loads(event.payload)
            label = LABELS.get(data["event"], data["event"])
            try:
                await self._send(client, request, data, tz)
            except AppError as exc:
                event.error = exc.message[:300]
                integration_log.record(
                    self.s, shop.id, f"{label} (job {request.external_job_id})", False, exc.message
                )
                log.warning(
                    "Housecall Pro update %s for %s failed: %s", event.id, request.id, exc.message
                )
                break
            event.sent_at = self.c.clock.now()
            event.error = None
            integration_log.record(
                self.s, shop.id, f"{label} (job {request.external_job_id})", True
            )
            sent += 1
        await self.s.flush()
        return sent

    async def _send(
        self, client: Any, request: ServiceRequest, data: dict[str, Any], tz: ZoneInfo
    ) -> None:
        job_id = request.external_job_id
        assert job_id
        at = datetime.fromisoformat(data["at"])
        who = data.get("by") or "Technician"
        event = data["event"]
        stamp = f"{_clock(at, tz)} - {who} (from {SOURCE})"
        if event in ("en_route", "on_site"):
            await client.add_note(job_id, f"{LABELS[event]}, {stamp}")
        elif event == "quote_approved":
            cents = int(data["price_cents"])
            await client.add_line_item(
                job_id,
                name=data.get("item") or "Repair (price approved in HVAC Connect)",
                quantity=1,
                unit_price_cents=cents,
                description=data.get("notes") or None,
            )
            await client.add_note(
                job_id,
                f"Customer approved ${cents / 100:,.2f} in the app, {stamp}"
                + (f"\nTechnician's notes: {data['notes']}" if data.get("notes") else ""),
            )
        elif event == "completed":
            charged = data.get("charged_cents")
            payment = (
                f"Card charged ${charged / 100:,.2f} in {SOURCE} (don't charge again)."
                if charged
                else "Payment wasn't taken in the app: collect it as usual."
            )
            await client.add_note(
                job_id, f"Job finished, {stamp}\n{payment}\nClose the job in Housecall Pro."
            )
        elif event == "canceled":
            await client.add_note(
                job_id, f"Canceled in {SOURCE}, {stamp}: {data.get('reason') or ''}".strip()
            )
            try:
                await client.unschedule(job_id)
            except AppError as exc:
                log.info("Couldn't unschedule HCP job %s: %s", job_id, exc.message)

    async def retry_all(self, limit: int = 50) -> int:
        """Worker: send what's waiting."""
        request_ids = list(
            dict.fromkeys(
                await self.s.scalars(
                    select(ExternalJobEvent.request_id)
                    .where(
                        ExternalJobEvent.request_id.is_not(None),
                        ExternalJobEvent.sent_at.is_(None),
                        ExternalJobEvent.attempts < MAX_ATTEMPTS,
                    )
                    .order_by(ExternalJobEvent.created_at)
                    .limit(limit)
                )
            )
        )
        sent = 0
        for request_id in request_ids:
            request = await self.s.get(ServiceRequest, request_id)
            if request is not None:
                sent += await self.send_pending(request)
        return sent

    async def customer_name(self, request: ServiceRequest) -> str:
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        return (homeowner.name if homeowner else None) or "customer"
