"""Homeowner app endpoints: profile, card, and service requests."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import ContainerDep, HomeownerDep, SessionDep
from app.api.presenters import request_out
from app.core.errors import AppError, NotFound
from app.integrations.payments.fake import FakePaymentGateway
from app.models import ServiceRequest
from app.schemas.api import (
    CardSetupFinishIn,
    CardSetupOut,
    DemoCardIn,
    HomeownerOut,
    HomeownerUpdateIn,
    PreferencesIn,
    RatingIn,
    RequestCreateIn,
    RequestOut,
    UnitUpdateIn,
)
from app.services.account_service import AccountService
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.request_service import RequestService

router = APIRouter(tags=["homeowner"])


# --- Profile & card ----------------------------------------------------------------------------
@router.get("/me", response_model=HomeownerOut)
async def get_me(me: HomeownerDep) -> HomeownerOut:
    return HomeownerOut.model_validate(me)


@router.patch("/me", response_model=HomeownerOut)
async def update_me(
    body: HomeownerUpdateIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> HomeownerOut:
    await AccountService(session, c).update_profile(
        me,
        name=body.name,
        address=body.address,
        lat=body.lat,
        lng=body.lng,
        sms_opt_in=body.sms_opt_in,
    )
    return HomeownerOut.model_validate(me)


@router.post("/me/payment-methods/setup", response_model=CardSetupOut)
async def start_card_setup(me: HomeownerDep, session: SessionDep, c: ContainerDep) -> CardSetupOut:
    setup = await AccountService(session, c).start_card_setup(me)
    is_demo = isinstance(c.payments, FakePaymentGateway)
    return CardSetupOut(
        provider="demo" if is_demo else "stripe",
        publishable_key=None if is_demo else c.payments.publishable_key,
        customer_id=setup.customer_id,
        setup_intent_id=setup.setup_intent_id,
        client_secret=setup.client_secret,
        ephemeral_key_secret=setup.ephemeral_key_secret,
    )


@router.post("/me/payment-methods/demo-card", status_code=status.HTTP_204_NO_CONTENT)
async def demo_card(body: DemoCardIn, me: HomeownerDep, c: ContainerDep) -> None:
    """Demo mode only: stands in for Stripe's card form. Never sees real card data in prod."""
    if not isinstance(c.payments, FakePaymentGateway):
        raise NotFound("Not available")
    digits = "".join(ch for ch in body.card_number if ch.isdigit())
    if len(digits) < 12:
        raise AppError("Enter a test card number", code="invalid_card")
    c.payments.record_demo_card(body.setup_intent_id, digits[-4:])


@router.post("/me/payment-methods/finish", response_model=HomeownerOut)
async def finish_card_setup(
    body: CardSetupFinishIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> HomeownerOut:
    await AccountService(session, c).finish_card_setup(me, body.setup_intent_id)
    return HomeownerOut.model_validate(me)


# --- Requests ------------------------------------------------------------------------------------
async def _present(session: SessionDep, c: ContainerDep, request: ServiceRequest) -> RequestOut:
    await session.flush()
    await session.refresh(request)
    return request_out(c, request)


@router.get("/requests", response_model=list[RequestOut])
async def list_requests(me: HomeownerDep, session: SessionDep, c: ContainerDep) -> list[RequestOut]:
    return [request_out(c, r) for r in await RequestService(session, c).list_for_homeowner(me)]


@router.post("/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    body: RequestCreateIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).create(
        me,
        symptoms=body.symptoms,
        description=body.description,
        urgency=body.urgency,
        address=body.address,
        lat=body.lat,
        lng=body.lng,
    )
    return await _present(session, c, request)


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    return request_out(c, await RequestService(session, c).get_for_homeowner(request_id, me))


@router.post("/requests/{request_id}/photos", response_model=RequestOut)
async def upload_photo(
    request_id: uuid.UUID,
    me: HomeownerDep,
    session: SessionDep,
    c: ContainerDep,
    file: UploadFile = File(...),
) -> RequestOut:
    service = RequestService(session, c)
    request = await service.get_for_homeowner(request_id, me)
    data = await file.read(c.settings.max_photo_bytes + 1)
    await service.add_photo(request, data)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/analyze", response_model=RequestOut)
async def analyze_request(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    service = RequestService(session, c)
    request = await service.analyze(await service.get_for_homeowner(request_id, me))
    return await _present(session, c, request)


@router.patch("/requests/{request_id}/unit", response_model=RequestOut)
async def update_unit(
    request_id: uuid.UUID,
    body: UnitUpdateIn,
    me: HomeownerDep,
    session: SessionDep,
    c: ContainerDep,
) -> RequestOut:
    service = RequestService(session, c)
    request = await service.update_unit(
        await service.get_for_homeowner(request_id, me),
        brand=body.brand,
        model_number=body.model_number,
        equipment_type=body.equipment_type,
        approx_age_years=body.approx_age_years,
    )
    return await _present(session, c, request)


@router.put("/requests/{request_id}/preferences", response_model=RequestOut)
async def set_preferences(
    request_id: uuid.UUID,
    body: PreferencesIn,
    me: HomeownerDep,
    session: SessionDep,
    c: ContainerDep,
) -> RequestOut:
    service = RequestService(session, c)
    request = await service.set_preferences(
        await service.get_for_homeowner(request_id, me),
        soft_skills=body.soft_skills,
        require_all=body.require_all,
    )
    return await _present(session, c, request)


@router.post("/requests/{request_id}/match", response_model=RequestOut)
async def find_technician(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await MatchingService(session, c).find_technician(request)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/confirm", response_model=RequestOut)
async def confirm_booking(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await MatchingService(session, c).confirm_booking(request, me)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/widen", response_model=RequestOut)
async def widen_search(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await MatchingService(session, c).widen_search(request)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/approve-quote", response_model=RequestOut)
async def approve_quote(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await JobService(session, c).approve_quote(request, me)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/cancel", response_model=RequestOut)
async def cancel_request(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await JobService(session, c).homeowner_cancel(request)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/rating", response_model=RequestOut)
async def rate_request(
    request_id: uuid.UUID, body: RatingIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await JobService(session, c).rate(request, body.rating)
    return await _present(session, c, request)
