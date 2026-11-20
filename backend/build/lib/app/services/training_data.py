"""Training data for a diagnosis model: each finished job's photos, what the homeowner
reported, what the AI guessed, and what the technician actually found and fixed.

Exported as a zip from the admin page (GET /v1/admin/training-data):
  labels.jsonl   one JSON object per job (see _app_job / _hcp_job)
  images/...     the job's photos (JPEG, already stripped of metadata/GPS when saved)

No names, phone numbers, emails or street addresses are included; only the city/state
market. The homeowner's own description is included as they typed it, so it may mention
personal details: review before sharing the data outside the company.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.container import Container
from app.core.errors import AppError
from app.domain.enums import RequestStatus
from app.domain.pricing import market_from_address
from app.models import ExternalJob, ExternalJobEvent, ServiceRequest

MAX_JOBS = 5000


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def build_zip(session: AsyncSession, c: Container, since: datetime | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        lines: list[str] = []
        query = (
            select(ServiceRequest)
            .options(selectinload(ServiceRequest.photos))
            .where(ServiceRequest.status == RequestStatus.COMPLETED.value)
            .order_by(ServiceRequest.completed_at)
            .limit(MAX_JOBS)
        )
        if since is not None:
            query = query.where(ServiceRequest.completed_at >= since)
        for request in await session.scalars(query):
            images = []
            for n, photo in enumerate(request.photos, 1):
                name = f"images/{request.id}_{n}.jpg"
                try:
                    archive.writestr(name, await c.storage.read(photo.storage_key))
                except AppError:
                    continue  # a photo from an old local-disk install that isn't here
                images.append(name)
            lines.append(json.dumps(_app_job(request, images)))

        jobs = await session.scalars(
            select(ExternalJob).where(ExternalJob.app_status == "finished").limit(MAX_JOBS)
        )
        for job in jobs:
            events = list(
                await session.scalars(
                    select(ExternalJobEvent)
                    .where(ExternalJobEvent.job_id == job.id)
                    .order_by(ExternalJobEvent.created_at)
                )
            )
            images = []
            for n, event in enumerate((e for e in events if e.kind == "photo"), 1):
                name = f"images/hcp_{job.id}_{n}.jpg"
                try:
                    archive.writestr(name, await c.storage.read(json.loads(event.payload)["key"]))
                except AppError:
                    continue
                images.append(name)
            lines.append(json.dumps(_hcp_job(job, events, images)))
        archive.writestr("labels.jsonl", "\n".join(lines) + ("\n" if lines else ""))
        archive.writestr("README.txt", README)
    return buffer.getvalue()


def _app_job(request: ServiceRequest, images: list[str]) -> dict[str, Any]:
    dx = request.diagnosis or {}
    unit = request.unit_info or {}
    return {
        "source": "app",
        "job_id": str(request.id),
        "created_at": _iso(request.created_at),
        "completed_at": _iso(request.completed_at),
        "market": market_from_address(request.address),
        "images": images,
        "reported": {"symptoms": request.symptoms, "description": request.description},
        "unit": {
            k: unit.get(k)
            for k in (
                "brand",
                "model_number",
                "equipment_type",
                "manufacture_year",
                "approx_age_years",
                "tonnage",
                "refrigerant",
                "fuel_type",
            )
        },
        "ai": {
            "used": dx.get("ai_used"),
            "analysis": dx.get("analysis"),
            "primary_issue": dx.get("primary_issue"),
            "confidence": dx.get("confidence"),
            "alternatives": [
                a.get("issue") for a in dx.get("alternatives", []) if isinstance(a, dict)
            ],
            "estimate_low_cents": request.estimate_low_cents,
            "estimate_high_cents": request.estimate_high_cents,
        },
        "actual": {
            "issue": request.actual_issue,  # the label to learn
            "fix": request.quote_notes,
            "final_price_cents": request.final_price_cents,
        },
    }


def _hcp_job(job: ExternalJob, events: list[ExternalJobEvent], images: list[str]) -> dict[str, Any]:
    summary = None
    items = []
    for event in events:
        if event.kind == "status":
            data = json.loads(event.payload)
            if data.get("step") == "finished":
                summary = data.get("summary")
        elif event.kind == "line_item":
            data = json.loads(event.payload)
            items.append({k: data[k] for k in ("name", "quantity", "unit_price_cents")})
    return {
        "source": "housecall_pro",
        "job_id": str(job.id),
        "completed_at": _iso(job.finished_at),
        "market": market_from_address(job.address),
        "images": images,
        "reported": {"description": job.description},
        "actual": {"issue": job.actual_issue, "fix": summary, "line_items": items},
    }


README = """Training data exported from HVAC Connect.

labels.jsonl: one job per line.
  source            app (booked in the app) or housecall_pro (the shop's own job)
  images            photo files in images/
  reported          what the homeowner selected and wrote
  unit              what was read from the equipment label
  ai                what the AI guessed (app jobs)
  actual.issue      what the technician found: the label to train on
  actual.fix        what the technician did
No names, phone numbers, emails or street addresses. The homeowner's description is as
typed and may contain personal details: review before sharing outside the company.
"""
