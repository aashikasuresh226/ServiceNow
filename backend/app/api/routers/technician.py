"""Technician app endpoints. The company's permissions are enforced in TechAppService."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import ContainerDep, SessionDep, TechDep
from app.api.presenters import message_out, tech_job_out
from app.core.errors import Forbidden
from app.models import ServiceRequest
from app.schemas.api import (
    DeclineIn,
    LocationIn,
    MessageIn,
    MessageOut,
    QuoteIn,
    TechBoardOut,
    TechJobOut,
    TechMeOut,
)
from app.services.message_service import MessageService
from app.services.tech_app_service import TechAppService

router = APIRouter(prefix="/tech", tags=["technician"])


@router.get("/me", response_model=TechMeOut)
async def me(principal: TechDep) -> TechMeOut:
    tech, shop = principal.tech, principal.shop
    return TechMeOut(
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


@router.get("/jobs", response_model=TechBoardOut)
async def board(principal: TechDep, session: SessionDep, c: ContainerDep) -> TechBoardOut:
    data = await TechAppService(session, c).board(principal.tech)
    tech = principal.tech
    return TechBoardOut(
        offers=[tech_job_out(c, r, tech) for r in data.offers],
        jobs=[tech_job_out(c, r, tech) for r in data.jobs],
        hidden_jobs=data.hidden_jobs,
        recent=[tech_job_out(c, r, tech) for r in data.recent],
    )


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
    await TechAppService(session, c).quote(request, body.final_price_cents, body.notes)
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
