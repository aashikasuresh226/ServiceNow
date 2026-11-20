"""Homeowner app endpoints: profile, card, and service requests."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status
from sqlalchemy import select

from app.api.deps import ContainerDep, HomeownerDep, SessionDep, client_ip
from app.api.presenters import message_out, request_out
from app.models import Complaint, ServiceRequest, Shop
from app.schemas.api import (
    CardSetupFinishIn,
    CardSetupOut,
    ComplaintIn,
    ComplaintOut,
    ComplaintStateOut,
    CustomerInviteIn,
    HomeownerOut,
    HomeownerUpdateIn,
    HomeVisitOut,
    InviteOut,
    MatchIn,
    MessageIn,
    MessageOut,
    NotificationsOut,
    OtpStartOut,
    PhoneStartIn,
    PhoneVerifyIn,
    ProfileSuggestionsOut,
    RatingIn,
    RequestCreateIn,
    RequestOut,
    UnitUpdateIn,
    UnreadChat,
)
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.services.complaint_service import CATEGORIES, ComplaintService, can_complain
from app.services.customer_service import CustomerService
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.message_service import MessageService
from app.services.outside_jobs import OutsideJobService
from app.services.provider_service import ProviderService
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
        me, name=body.name, address=body.address, sms_opt_in=body.sms_opt_in
    )
    return HomeownerOut.model_validate(me)


@router.get("/me/suggestions", response_model=ProfileSuggestionsOut)
async def profile_suggestions(
    me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> ProfileSuggestionsOut:
    """What a company the homeowner is a customer of has on file (to pre-fill the profile)."""
    customers = CustomerService(session, c)
    record = await customers.on_file(me)
    return ProfileSuggestionsOut(
        name=record.name if record else None,
        address=record.address if record else None,
        companies=await customers.company_names(me),
    )


@router.post("/me/invite", response_model=InviteOut)
async def accept_invite(
    body: CustomerInviteIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> InviteOut:
    """Signed up from a company's invite link: they become (or stay) that company's customer."""
    info = await CustomerService(session, c).accept_invite(me, body.code)
    return InviteOut(shop_name=info.shop_name, shop_phone=info.shop_phone)


@router.post("/me/phone/start", response_model=OtpStartOut)
async def start_add_phone(
    body: PhoneStartIn, request: Request, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> OtpStartOut:
    """Google users add a mobile number (verified with a texted code)."""
    started = await AuthService(session, c).start_add_phone(me, body.phone, ip=client_ip(request))
    return OtpStartOut(
        phone=started.phone,
        resend_after_seconds=started.resend_after_seconds,
        dev_code=started.dev_code,
    )


@router.post("/me/phone/verify", response_model=HomeownerOut)
async def finish_add_phone(
    body: PhoneVerifyIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> HomeownerOut:
    await AuthService(session, c).finish_add_phone(me, body.phone, body.code)
    return HomeownerOut.model_validate(me)


@router.post("/me/payment-methods/setup", response_model=CardSetupOut)
async def start_card_setup(me: HomeownerDep, session: SessionDep, c: ContainerDep) -> CardSetupOut:
    setup = await AccountService(session, c).start_card_setup(me)
    assert c.payments is not None  # start_card_setup raises when payments are off
    return CardSetupOut(
        publishable_key=c.payments.publishable_key,
        customer_id=setup.customer_id,
        setup_intent_id=setup.setup_intent_id,
        client_secret=setup.client_secret,
        ephemeral_key_secret=setup.ephemeral_key_secret,
    )


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


@router.post("/requests/{request_id}/match", response_model=RequestOut)
async def find_technician(
    request_id: uuid.UUID,
    me: HomeownerDep,
    session: SessionDep,
    c: ContainerDep,
    body: MatchIn | None = None,
) -> RequestOut:
    """Book the soonest qualified technician, or the company/technician the homeowner picked."""
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    if request.status in ("analyzed", "waitlisted"):
        await ProviderService(session, c).set_choice(
            request,
            shop_id=body.shop_id if body else None,
            technician_id=body.technician_id if body else None,
        )
    await MatchingService(session, c).find_technician(request)
    return await _present(session, c, request)


@router.post("/requests/{request_id}/confirm", response_model=RequestOut)
async def confirm_booking(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> RequestOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    await MatchingService(session, c).confirm_booking(request, me)
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
    await JobService(session, c).rate(
        request,
        technician_rating=body.technician_rating or body.rating,
        shop_rating=body.shop_rating,
        review=body.review,
    )
    return await _present(session, c, request)


@router.get("/requests/{request_id}/share")
async def share_request(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> dict[str, Any]:
    """Ready-to-send messages recommending this job's technician and company."""
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    return await ProviderService(session, c).share_for(request)


@router.get("/requests/{request_id}/providers")
async def list_providers(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> dict[str, Any]:
    """Companies and technicians who can take this request, soonest first."""
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    return await ProviderService(session, c).options_for(request)


# --- Chat with the shop / technician ------------------------------------------------------
@router.get("/requests/{request_id}/messages", response_model=list[MessageOut])
async def list_messages(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> list[MessageOut]:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    messages = MessageService(session, c)
    await messages.mark_read_by_homeowner(request)  # opening the chat reads it
    return [message_out(m) for m in await messages.list(request)]


@router.get("/me/visits", response_model=list[HomeVisitOut])
async def visits(me: HomeownerDep, session: SessionDep, c: ContainerDep) -> list[HomeVisitOut]:
    """Visits your HVAC company booked for you in Housecall Pro, so you see them here too."""
    rows = await OutsideJobService(session, c).for_homeowner(me.id)
    shops = (
        {
            s.id: s
            for s in await session.scalars(
                select(Shop).where(Shop.id.in_({j.shop_id for j, _ in rows}))
            )
        }
        if rows
        else {}
    )
    return [
        HomeVisitOut(
            id=job.id,
            shop_name=shops[job.shop_id].name if job.shop_id in shops else "Your HVAC company",
            shop_phone=shops[job.shop_id].phone if job.shop_id in shops else None,
            technician_first_name=first,
            starts_at=job.starts_at,
            ends_at=job.ends_at,
            description=job.description,
            status=job.app_status or "scheduled",
        )
        for job, first in rows
    ]


@router.get("/me/notifications", response_model=NotificationsOut)
async def notifications(me: HomeownerDep, session: SessionDep, c: ContainerDep) -> NotificationsOut:
    """New messages from companies and technicians (the app polls this to alert you)."""
    unread = await MessageService(session, c).unread_for_homeowner(me.id)
    return NotificationsOut(
        unread_messages=[
            UnreadChat(
                request_id=u.request_id,
                count=u.count,
                sender_name=u.sender_name,
                preview=u.preview,
                last_at=u.last_at,
            )
            for u in unread
        ],
        total_unread=sum(u.count for u in unread),
    )


# --- Report a problem with the technician -------------------------------------------------
def _complaint_out(complaint: Complaint) -> ComplaintOut:
    return ComplaintOut(
        id=complaint.id,
        category=complaint.category,
        category_label=CATEGORIES.get(complaint.category, complaint.category),
        details=complaint.details,
        status=complaint.status,
        shop_response=complaint.shop_response,
        created_at=complaint.created_at,
    )


@router.get("/requests/{request_id}/complaint", response_model=ComplaintStateOut)
async def complaint_state(
    request_id: uuid.UUID, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> ComplaintStateOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    existing = await ComplaintService(session, c).for_request(request.id)
    return ComplaintStateOut(
        can_file=existing is None and can_complain(request, c.clock.now()),
        categories=CATEGORIES,
        complaint=_complaint_out(existing) if existing else None,
    )


@router.post(
    "/requests/{request_id}/complaint",
    response_model=ComplaintOut,
    status_code=status.HTTP_201_CREATED,
)
async def file_complaint(
    request_id: uuid.UUID,
    body: ComplaintIn,
    me: HomeownerDep,
    session: SessionDep,
    c: ContainerDep,
) -> ComplaintOut:
    """Goes to the company and the platform admin; the technician doesn't see it."""
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    complaint = await ComplaintService(session, c).file(
        request, category=body.category, details=body.details
    )
    return _complaint_out(complaint)


@router.post(
    "/requests/{request_id}/messages",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
async def send_message(
    request_id: uuid.UUID, body: MessageIn, me: HomeownerDep, session: SessionDep, c: ContainerDep
) -> MessageOut:
    request = await RequestService(session, c).get_for_homeowner(request_id, me)
    message = await MessageService(session, c).post(
        request,
        sender="homeowner",
        sender_name=(me.name or "").split(" ")[0] or None,
        body=body.body,
    )
    return message_out(message)
