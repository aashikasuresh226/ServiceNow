"""Complaint rows -> what the company (and admin) see, with job context."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Complaint, Homeowner, ServiceRequest, Technician
from app.schemas.api import ShopComplaintOut
from app.services.complaint_service import CATEGORIES


async def complaint_views(
    session: AsyncSession, rows: Sequence[Complaint]
) -> list[ShopComplaintOut]:
    if not rows:
        return []
    requests = {
        r.id: r
        for r in await session.scalars(
            select(ServiceRequest).where(ServiceRequest.id.in_({c.request_id for c in rows}))
        )
    }
    techs = {
        t.id: t.name
        for t in await session.scalars(
            select(Technician).where(
                Technician.id.in_({c.technician_id for c in rows if c.technician_id})
            )
        )
    }
    owners = {
        h.id: h.name
        for h in await session.scalars(
            select(Homeowner).where(Homeowner.id.in_({c.homeowner_id for c in rows}))
        )
    }
    out = []
    for c in rows:
        request = requests.get(c.request_id)
        name = owners.get(c.homeowner_id)
        diagnosis = (request.diagnosis or {}) if request else {}
        out.append(
            ShopComplaintOut(
                id=c.id,
                category=c.category,
                category_label=CATEGORIES.get(c.category, c.category),
                details=c.details,
                status=c.status,
                shop_response=c.shop_response,
                created_at=c.created_at,
                request_id=c.request_id,
                technician_id=c.technician_id,
                technician_name=techs.get(c.technician_id) if c.technician_id else None,
                customer_name=name.split()[0] if name and name.split() else None,
                job_date=request.created_at if request else c.created_at,
                issue=diagnosis.get("primary_issue_label"),
                shop_responded_at=c.shop_responded_at,
                resolved_at=c.resolved_at,
                resolved_by=c.resolved_by,
            )
        )
    return out
