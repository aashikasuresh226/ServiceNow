"""Platform admin (you): complaints from every company, and every rating and review.

Signed in with HVAC_ADMIN_TOKEN (created by `python -m app.cli secrets`), sent as the
X-Admin-Key header by the portal's /admin page. Switched off when the token isn't set.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy import select

from app.api.deps import ContainerDep, SessionDep
from app.core.errors import AppError, Unauthorized
from app.core.security import constant_time_equals
from app.models import Complaint, ServiceRequest, Shop, Technician
from app.schemas.api import AdminComplaintIn, AdminComplaintOut, AdminReviewOut
from app.services.complaint_service import ComplaintService
from app.services.complaints_view import complaint_views
from app.services.training_data import build_zip

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(
    request: Request,
    c: ContainerDep,
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    token = c.settings.admin_token
    if token is None or not token.get_secret_value().strip():
        raise AppError(
            "The admin page is off: run `python -m app.cli secrets` to create HVAC_ADMIN_TOKEN",
            code="admin_off",
        )
    client = request.client.host if request.client else "?"
    c.rate_limiter.check("admin", client, limit=60, window_seconds=60)
    if not x_admin_key or not constant_time_equals(x_admin_key, token.get_secret_value().strip()):
        c.rate_limiter.check("admin-fail", client, limit=10, window_seconds=900)
        raise Unauthorized("Wrong admin key", code="admin_key")


AdminDep = Depends(require_admin)


@router.get("/check", dependencies=[AdminDep])
async def check() -> dict[str, bool]:
    return {"ok": True}


@router.get("/complaints", response_model=list[AdminComplaintOut], dependencies=[AdminDep])
async def complaints(
    session: SessionDep,
    c: ContainerDep,
    status_filter: str | None = Query(None, alias="status", pattern="^(open|resolved)$"),
) -> list[AdminComplaintOut]:
    rows = await ComplaintService(session, c).all(status_filter)
    views = await complaint_views(session, rows)
    shops = (
        {
            s.id: s.name
            for s in await session.scalars(
                select(Shop).where(Shop.id.in_({r.shop_id for r in rows}))
            )
        }
        if rows
        else {}
    )
    return [
        AdminComplaintOut(
            **view.model_dump(),
            shop_id=row.shop_id,
            shop_name=shops.get(row.shop_id, ""),
            admin_note=row.admin_note,
        )
        for row, view in zip(rows, views, strict=True)
    ]


@router.patch(
    "/complaints/{complaint_id}", response_model=AdminComplaintOut, dependencies=[AdminDep]
)
async def update_complaint(
    complaint_id: uuid.UUID, body: AdminComplaintIn, session: SessionDep, c: ContainerDep
) -> AdminComplaintOut:
    row: Complaint = await ComplaintService(session, c).admin_update(
        complaint_id, note=body.note, status=body.status
    )
    [view] = await complaint_views(session, [row])
    shop = await session.get(Shop, row.shop_id)
    return AdminComplaintOut(
        **view.model_dump(),
        shop_id=row.shop_id,
        shop_name=shop.name if shop else "",
        admin_note=row.admin_note,
    )


@router.get("/training-data", dependencies=[AdminDep])
async def training_data(
    session: SessionDep, c: ContainerDep, since: datetime | None = None
) -> Response:
    """A zip of finished jobs: photos + reported symptoms + AI guess + actual issue and fix
    (labels.jsonl + images/). No names, phone numbers, emails or street addresses."""
    data = await build_zip(session, c, since)
    stamp = c.clock.now().strftime("%Y-%m-%d")
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="hvac-training-{stamp}.zip"'},
    )


@router.get("/reviews", response_model=list[AdminReviewOut], dependencies=[AdminDep])
async def reviews(
    session: SessionDep, limit: int = Query(200, ge=1, le=1000)
) -> list[AdminReviewOut]:
    """Every rating and review (companies and technicians only ever see their averages)."""
    rows = (
        await session.execute(
            select(ServiceRequest, Shop.name, Technician.name)
            .outerjoin(Shop, Shop.id == ServiceRequest.shop_id)
            .outerjoin(Technician, Technician.id == ServiceRequest.technician_id)
            .where(
                (ServiceRequest.rating.is_not(None))
                | (ServiceRequest.shop_rating.is_not(None))
                | (ServiceRequest.review.is_not(None))
            )
            .order_by(ServiceRequest.completed_at.desc().nulls_last())
            .limit(limit)
        )
    ).all()
    return [
        AdminReviewOut(
            request_id=r.id,
            completed_at=r.completed_at,
            shop_name=shop_name,
            technician_name=tech_name,
            technician_rating=r.rating,
            shop_rating=r.shop_rating,
            review=r.review,
        )
        for r, shop_name, tech_name in rows
    ]
