"""Technician app endpoints. The company's permissions are enforced in TechAppService."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ContainerDep, SessionDep, TechDep, TechPrincipal
from app.api.presenters import (
    message_out,
    outside_activity_text,
    outside_job_out,
    tech_job_out,
)
from app.container import Container
from app.core.errors import Forbidden, NotFound
from app.models import ServiceRequest, Technician
from app.schemas.api import (
    DeclineIn,
    LocationIn,
    MessageIn,
    MessageOut,
    OutsideActivity,
    OutsideJobDetailOut,
    OutsideJobOut,
    OutsideLineItem,
    OutsideLineItemIn,
    OutsideNoteIn,
    OutsideStepIn,
    QuoteIn,
    TechBoardOut,
    TechJobOut,
    TechMeOut,
    TechUpdateIn,
)
from app.services import media
from app.services.auth_service import AuthService
from app.services.message_service import MessageService
from app.services.outside_job_actions import LineItem, OutsideJobActions
from app.services.outside_jobs import OutsideJob, OutsideJobService
from app.services.tech_app_service import TechAppService

router = APIRouter(prefix="/tech", tags=["technician"])


def _tech_me(principal: TechPrincipal) -> TechMeOut:
    tech, shop = principal.tech, principal.shop
    return TechMeOut(
        photo_url=tech.photo_url,
        sign_in="authenticator"
        if tech.totp_secret_encrypted
        else "google"
        if tech.google_sub
        else "email",
        id=tech.id,
        name=tech.name,
        phone=tech.phone,
        email=tech.email,
        shop_name=shop.name,
        shop_phone=shop.phone,
        can_respond_offers=tech.can_respond_offers,
        can_contact_customers=tech.can_contact_customers,
        schedule_view=tech.schedule_view,
    )


@router.get("/me", response_model=TechMeOut)
async def me(principal: TechDep) -> TechMeOut:
    return _tech_me(principal)


@router.patch("/me", response_model=TechMeOut)
async def update_me(
    body: TechUpdateIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechMeOut:
    """A technician updates their own mobile number (customers and the office use it)."""
    if body.phone is not None:
        service = AuthService(session, c)
        phone = service._normalize_allowed(body.phone)
        await service._ensure_tech_phone_free(principal.tech, phone)
        principal.tech.phone = phone
        await session.flush()
    return _tech_me(principal)


@router.post("/me/photo", response_model=TechMeOut)
async def set_photo(
    principal: TechDep, session: SessionDep, c: ContainerDep, file: UploadFile = File(...)
) -> TechMeOut:
    """Profile photo: customers see it when this technician is on the way."""
    data = await file.read(media.MAX_BYTES + 1)
    principal.tech.photo_url = await media.save_image(c, data, kind="avatar")
    await session.flush()
    return _tech_me(principal)


@router.delete("/me/photo", response_model=TechMeOut)
async def remove_photo(principal: TechDep, session: SessionDep) -> TechMeOut:
    principal.tech.photo_url = None
    await session.flush()
    return _tech_me(principal)


@router.get("/jobs", response_model=TechBoardOut)
async def board_for(principal: TechDep, session: SessionDep, c: ContainerDep) -> TechBoardOut:
    data = await TechAppService(session, c).board(principal.tech)
    tech = principal.tech
    outside = await OutsideJobService(session, c).for_technician(tech)
    hidden = data.hidden_jobs
    if tech.schedule_view == "next" and outside:
        # Next job only: the earliest of our jobs and the shop's own jobs.
        first_ours = data.jobs[0].eta_at if data.jobs else None
        first_theirs = outside[0].job.starts_at
        if first_ours is not None and (first_theirs is None or first_ours <= first_theirs):
            hidden += len(outside)
            outside = []
        else:
            hidden += len(outside) - 1 + len(data.jobs)
            outside = outside[:1]
            data = type(data)(data.offers, [], 0, data.recent)
    return TechBoardOut(
        offers=[tech_job_out(c, r, tech) for r in data.offers],
        jobs=[tech_job_out(c, r, tech) for r in data.jobs],
        hidden_jobs=hidden,
        recent=[tech_job_out(c, r, tech) for r in data.recent],
        outside_jobs=[_outside(o, tech) for o in outside],
    )


def _outside(item: OutsideJob, tech: Technician) -> OutsideJobOut:
    return outside_job_out(
        item.job,
        technician_name=item.technician_name,
        show_phone=tech.can_contact_customers,
        customer_uses_app=item.customer_uses_app,
        unsent=item.unsent,
    )


@router.get("/outside-jobs/{job_id}", response_model=OutsideJobDetailOut)
async def outside_job(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> OutsideJobDetailOut:
    """A job from the company's Housecall Pro, with what's been done in the app and the
    line items Housecall Pro has."""
    tech = principal.tech
    board = await board_for(principal, session, c)
    if not any(o.id == job_id for o in board.outside_jobs):
        raise NotFound("Job not found")
    return await _detail(session, c, tech, job_id)


async def _detail(
    session: AsyncSession, c: Container, tech: Technician, job_id: uuid.UUID
) -> OutsideJobDetailOut:
    item = await OutsideJobService(session, c).get_for_technician(tech, job_id)
    actions = OutsideJobActions(session, c)
    events = await actions.events(job_id)
    items = await actions.hcp_line_items(item.job)
    return OutsideJobDetailOut(
        **_outside(item, tech).model_dump(),
        activity=[
            OutsideActivity(
                id=e.id,
                kind=e.kind,
                text=outside_activity_text(e),
                created_at=e.created_at,
                sent=e.sent_at is not None,
                error=e.error,
            )
            for e in events
        ],
        line_items=[OutsideLineItem(**i) for i in items] if items is not None else None,
    )


@router.post("/outside-jobs/{job_id}/step", response_model=OutsideJobDetailOut)
async def outside_step(
    job_id: uuid.UUID, body: OutsideStepIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> OutsideJobDetailOut:
    """On my way / Arrived / Started / Finished: written to the Housecall Pro job as notes."""
    await OutsideJobActions(session, c).step(
        principal.tech, job_id, body.step, body.summary, body.actual_issue
    )
    return await _detail(session, c, principal.tech, job_id)


@router.post("/outside-jobs/{job_id}/line-items", response_model=OutsideJobDetailOut)
async def outside_line_item(
    job_id: uuid.UUID,
    body: OutsideLineItemIn,
    principal: TechDep,
    session: SessionDep,
    c: ContainerDep,
) -> OutsideJobDetailOut:
    """Add work or a part with its price to the Housecall Pro job."""
    await OutsideJobActions(session, c).add_line_item(
        principal.tech,
        job_id,
        LineItem(body.name, body.quantity, body.unit_price_cents),
    )
    return await _detail(session, c, principal.tech, job_id)


@router.post("/outside-jobs/{job_id}/notes", response_model=OutsideJobDetailOut)
async def outside_note(
    job_id: uuid.UUID, body: OutsideNoteIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> OutsideJobDetailOut:
    await OutsideJobActions(session, c).add_note(principal.tech, job_id, body.body)
    return await _detail(session, c, principal.tech, job_id)


@router.post("/outside-jobs/{job_id}/photos", response_model=OutsideJobDetailOut)
async def outside_photo(
    job_id: uuid.UUID,
    principal: TechDep,
    session: SessionDep,
    c: ContainerDep,
    file: UploadFile = File(...),
) -> OutsideJobDetailOut:
    data = await file.read(c.settings.max_photo_bytes + 1)
    await OutsideJobActions(session, c).add_photo(principal.tech, job_id, data)
    return await _detail(session, c, principal.tech, job_id)


@router.post("/outside-jobs/{job_id}/retry", response_model=OutsideJobDetailOut)
async def outside_retry(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> OutsideJobDetailOut:
    """Try again now to send what's waiting (also retried automatically)."""
    item = await OutsideJobService(session, c).get_for_technician(principal.tech, job_id)
    await OutsideJobActions(session, c).send_pending(item.job)
    return await _detail(session, c, principal.tech, job_id)


async def _job(
    principal: TechDep, session: SessionDep, c: ContainerDep, job_id: uuid.UUID
) -> ServiceRequest:
    return await TechAppService(session, c).get(principal.tech, job_id)


async def _present(
    principal: TechDep, session: SessionDep, c: ContainerDep, request: ServiceRequest
) -> TechJobOut:
    await session.flush()
    await session.refresh(request)
    return tech_job_out(c, request, principal.tech)


@router.get("/jobs/{job_id}", response_model=TechJobOut)
async def get_job(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    return tech_job_out(c, await _job(principal, session, c, job_id), principal.tech)


@router.post("/jobs/{job_id}/accept", response_model=TechJobOut)
async def accept(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).accept(principal.tech, principal.shop, request)
    return await _present(principal, session, c, request)


@router.post("/jobs/{job_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline(
    job_id: uuid.UUID, body: DeclineIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> None:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).decline(principal.tech, principal.shop, request, body.reason)


@router.post("/jobs/{job_id}/cant-make-it", response_model=TechJobOut)
async def cant_make_it(
    job_id: uuid.UUID, body: DeclineIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).cant_make_it(request, body.reason)
    return await _present(principal, session, c, request)


@router.post("/jobs/{job_id}/start-driving", response_model=TechJobOut)
async def start_driving(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).start_driving(request)
    return await _present(principal, session, c, request)


@router.put("/jobs/{job_id}/location", status_code=status.HTTP_204_NO_CONTENT)
async def update_location(
    job_id: uuid.UUID, body: LocationIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> None:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).update_location(
        principal.tech, request, lat=body.lat, lng=body.lng, accuracy_m=body.accuracy_m
    )


@router.post("/jobs/{job_id}/arrived", response_model=TechJobOut)
async def arrived(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).arrived(request)
    return await _present(principal, session, c, request)


@router.post("/jobs/{job_id}/quote", response_model=TechJobOut)
async def quote(
    job_id: uuid.UUID, body: QuoteIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).quote(
        request, body.final_price_cents, body.notes, body.actual_issue
    )
    return await _present(principal, session, c, request)


@router.post("/jobs/{job_id}/complete", response_model=TechJobOut)
async def complete(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> TechJobOut:
    request = await _job(principal, session, c, job_id)
    await TechAppService(session, c).complete(request)
    return await _present(principal, session, c, request)


def _require_contact(principal: TechDep) -> None:
    if not principal.tech.can_contact_customers:
        raise Forbidden("Your company handles customer messages", code="not_allowed")


@router.get("/jobs/{job_id}/messages", response_model=list[MessageOut])
async def messages(
    job_id: uuid.UUID, principal: TechDep, session: SessionDep, c: ContainerDep
) -> list[MessageOut]:
    _require_contact(principal)
    request = await _job(principal, session, c, job_id)
    return [message_out(m) for m in await MessageService(session, c).list(request)]


@router.post(
    "/jobs/{job_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def send_message(
    job_id: uuid.UUID, body: MessageIn, principal: TechDep, session: SessionDep, c: ContainerDep
) -> MessageOut:
    _require_contact(principal)
    request = await _job(principal, session, c, job_id)
    message = await MessageService(session, c).post(
        request, sender="technician", sender_name=principal.tech.name, body=body.body
    )
    return message_out(message)
