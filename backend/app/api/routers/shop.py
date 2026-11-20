"""Shop portal endpoints: profile, payouts, scheduling, technicians, availability, jobs."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, SessionDep, ShopDep
from app.api.presenters import message_out, outside_job_out, shop_job_out
from app.container import Container
from app.core.errors import InvalidState, NotFound
from app.domain.enums import SchedulingProvider
from app.models import ServiceRequest, Shop, ShopCustomer, Technician
from app.schemas.api import (
    AcceptIn,
    BlockOut,
    BusyIn,
    CalendarLinkOut,
    ComplaintResponseIn,
    CountOut,
    CustomerListOut,
    CustomerOut,
    DashboardOut,
    DispatchSettingsIn,
    EmailLinkOut,
    LinkOut,
    LiveIn,
    MessageIn,
    MessageOut,
    OutsideJobOut,
    PayoutScheduleIn,
    QuoteIn,
    SchedulingConnectIn,
    ShopComplaintOut,
    ShopJobOut,
    ShopMeOut,
    ShopOut,
    ShopUpdateIn,
    TechDayOut,
    TechInviteIn,
    TechInviteOut,
    TechnicianIn,
    TechnicianOut,
    TechOptionOut,
    TimeOffIn,
    TimeOffOut,
)
from app.services.availability_service import AvailabilityService
from app.services.calendar_service import CalendarService
from app.services.complaint_service import ComplaintService
from app.services.complaints_view import complaint_views
from app.services.customer_service import CustomerService, status_of
from app.services.external_jobs import ExternalJobService
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.message_service import MessageService
from app.services.outside_jobs import OutsideJobService
from app.services.shop_service import ShopService

router = APIRouter(prefix="/shop", tags=["shop"])


def _me(principal: ShopDep, c: Container | None = None) -> ShopMeOut:
    shop = ShopOut.model_validate(principal.shop)
    token = principal.shop.scheduling_webhook_token
    if token and c is not None:
        shop.scheduling_webhook_url = (
            f"{c.settings.public_api_url}/v1/webhooks/housecall-pro/{token}"
        )
    return ShopMeOut(user_email=principal.user.email, user_name=principal.user.name, shop=shop)


def _tech_out(tech: Technician) -> TechnicianOut:
    return TechnicianOut.model_validate(tech)


# --- Profile, live switch, payouts --------------------------------------------------------------
@router.get("/me", response_model=ShopMeOut)
async def get_me(principal: ShopDep, c: ContainerDep) -> ShopMeOut:
    return _me(principal, c)


@router.patch("/me", response_model=ShopMeOut)
async def update_shop(
    body: ShopUpdateIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    await ShopService(session, c).update_profile(
        principal.shop,
        name=body.name,
        phone=body.phone,
        address=body.address,
        timezone=body.timezone,
    )
    return _me(principal, c)


@router.put("/live", response_model=ShopMeOut)
async def set_live(
    body: LiveIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    await ShopService(session, c).set_live(principal.shop, body.is_live)
    return _me(principal, c)


@router.post("/payouts/onboarding-link", response_model=LinkOut)
async def payout_onboarding(principal: ShopDep, session: SessionDep, c: ContainerDep) -> LinkOut:
    url = await ShopService(session, c).payout_onboarding_link(principal.shop, principal.user)
    return LinkOut(url=url)


@router.post("/payouts/refresh", response_model=ShopMeOut)
async def refresh_payouts(principal: ShopDep, session: SessionDep, c: ContainerDep) -> ShopMeOut:
    await ShopService(session, c).refresh_payout_status(principal.shop)
    return _me(principal, c)


@router.put("/payouts/schedule", response_model=ShopMeOut)
async def payout_schedule(
    body: PayoutScheduleIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    await ShopService(session, c).set_payout_schedule(principal.shop, body.schedule)
    return _me(principal, c)


# --- Scheduling software -------------------------------------------------------------------------
@router.put("/scheduling", response_model=CountOut)
async def connect_scheduling(
    body: SchedulingConnectIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> CountOut:
    """Verify credentials, store them encrypted, import technicians, run a first sync."""
    if body.provider != SchedulingProvider.HOUSECALL_PRO and not (
        c.settings.scheduling_integrations_enabled
    ):
        raise InvalidState("The ServiceTitan connection is coming soon.", code="coming_soon")
    imported = await ShopService(session, c).connect_scheduling(
        principal.shop, body.provider, body.credentials, body.write_back_jobs
    )
    return CountOut(count=imported)


@router.delete("/scheduling", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_scheduling(principal: ShopDep, session: SessionDep, c: ContainerDep) -> None:
    await ShopService(session, c).disconnect_scheduling(principal.shop)


@router.post("/scheduling/sync", response_model=CountOut)
async def sync_now(principal: ShopDep, session: SessionDep, c: ContainerDep) -> CountOut:
    return CountOut(count=await AvailabilityService(session, c).sync_shop(principal.shop))


# --- Housecall Pro jobs and customers ------------------------------------------------------------
@router.get("/outside-jobs", response_model=list[OutsideJobOut])
async def list_outside_jobs(
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
    days: int = Query(7, ge=1, le=31),
) -> list[OutsideJobOut]:
    """Jobs in the shop's Housecall Pro (copied every minute), from yesterday on."""
    now = c.clock.now()
    rows = await OutsideJobService(session, c).for_shop(
        principal.shop.id, now - timedelta(days=1), now + timedelta(days=days)
    )
    return [
        outside_job_out(
            o.job,
            technician_name=o.technician_name,
            show_phone=True,
            customer_uses_app=o.customer_uses_app,
            unsent=o.unsent,
        )
        for o in rows
    ]


@router.get("/customers", response_model=CustomerListOut)
async def list_customers(
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
    q: str | None = Query(None, max_length=80),
    status_filter: str | None = Query(None, alias="status", max_length=12),
) -> CustomerListOut:
    service = CustomerService(session, c)
    shop = principal.shop
    everyone = await service.list_for_shop(shop)
    rows = await service.list_for_shop(shop, query=q, status=status_filter)
    shop_url = service.invite_url(await service.ensure_shop_code(shop))
    return CustomerListOut(
        customers=[_customer_out(service, shop, r) for r in rows[:500]],
        total=len(everyone),
        joined=sum(1 for r in everyone if status_of(r) == "joined"),
        invited=sum(1 for r in everyone if status_of(r) == "invited"),
        imported_at=shop.customers_imported_at,
        shop_invite_url=shop_url,
        shop_invite_message=service.invite_message(shop, shop_url),
    )


def _customer_out(service: CustomerService, shop: Shop, row: ShopCustomer) -> CustomerOut:
    url = service.invite_url(row.invite_code)
    return CustomerOut(
        id=row.id,
        provider=row.provider,
        name=row.name,
        phone=row.phone,
        email=row.email,
        address=row.address,
        status=status_of(row),
        invited_at=row.invited_at,
        joined_at=row.joined_at,
        last_job_at=row.last_job_at,
        invite_url=url,
        invite_message=service.invite_message(shop, url, row.name),
    )


@router.post("/customers/{customer_id}/invited", response_model=CustomerOut)
async def mark_customer_invited(
    customer_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> CustomerOut:
    """The shop sent this customer their invite (from its own phone or email)."""
    service = CustomerService(session, c)
    row = await service.get_for_shop(principal.shop, customer_id)
    service.mark_invited(row)
    return _customer_out(service, principal.shop, row)


@router.post("/customers/import", response_model=CountOut)
async def import_customers(principal: ShopDep, session: SessionDep, c: ContainerDep) -> CountOut:
    """Re-read every customer from Housecall Pro now."""
    if principal.shop.scheduling_provider != SchedulingProvider.HOUSECALL_PRO.value:
        raise InvalidState("Connect Housecall Pro first (How you take jobs)")
    return CountOut(count=await ExternalJobService(session, c).import_customers(principal.shop))


# --- Complaints from homeowners -------------------------------------------------------------------
@router.get("/complaints", response_model=list[ShopComplaintOut])
async def list_complaints(
    principal: ShopDep, session: SessionDep, c: ContainerDep
) -> list[ShopComplaintOut]:
    """Homeowners' complaints about your technicians (the technician doesn't see them)."""
    rows = await ComplaintService(session, c).for_shop(principal.shop.id)
    return await complaint_views(session, rows)


@router.post("/complaints/{complaint_id}/response", response_model=ShopComplaintOut)
async def respond_to_complaint(
    complaint_id: uuid.UUID,
    body: ComplaintResponseIn,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> ShopComplaintOut:
    """Reply to the homeowner (they see it in the app) and/or mark it resolved."""
    row = await ComplaintService(session, c).respond(
        principal.shop.id, complaint_id, response=body.response, resolved=body.resolved
    )
    [view] = await complaint_views(session, [row])
    return view


# --- Technicians ---------------------------------------------------------------------------------
@router.get("/technicians", response_model=list[TechnicianOut])
async def list_technicians(
    principal: ShopDep, session: SessionDep, c: ContainerDep
) -> list[TechnicianOut]:
    return [_tech_out(t) for t in await ShopService(session, c).list_technicians(principal.shop)]


@router.post("/technicians", response_model=TechnicianOut, status_code=status.HTTP_201_CREATED)
async def create_technician(
    body: TechnicianIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> TechnicianOut:
    tech = await ShopService(session, c).save_technician(
        principal.shop, None, body.model_dump(exclude_unset=True)
    )
    return _tech_out(tech)


@router.patch("/technicians/{technician_id}", response_model=TechnicianOut)
async def update_technician(
    technician_id: uuid.UUID,
    body: TechnicianIn,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> TechnicianOut:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    return _tech_out(
        await service.save_technician(principal.shop, tech, body.model_dump(exclude_unset=True))
    )


@router.post("/technicians/import", response_model=CountOut)
async def import_technicians(principal: ShopDep, session: SessionDep, c: ContainerDep) -> CountOut:
    return CountOut(count=await ShopService(session, c).import_technicians(principal.shop))


@router.get("/technicians/{technician_id}/time-off", response_model=list[TimeOffOut])
async def list_time_off(
    technician_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> list[TimeOffOut]:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    return [TimeOffOut.model_validate(b) for b in await service.list_time_off(tech)]


@router.post(
    "/technicians/{technician_id}/time-off",
    response_model=TimeOffOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_time_off(
    technician_id: uuid.UUID,
    body: TimeOffIn,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> TimeOffOut:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    block = await service.add_time_off(tech, body.starts_at, body.ends_at, body.label)
    return TimeOffOut.model_validate(block)


@router.delete(
    "/technicians/{technician_id}/time-off/{block_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_time_off(
    technician_id: uuid.UUID,
    block_id: uuid.UUID,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> None:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    await service.remove_time_off(tech, block_id)


@router.patch("/dispatch", response_model=ShopMeOut)
async def update_dispatch(
    body: DispatchSettingsIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    """How this shop takes jobs: who picks the technician, and instant book."""
    await ShopService(session, c).set_dispatch(principal.shop, body.model_dump(exclude_unset=True))
    return _me(principal, c)


@router.post("/technicians/{technician_id}/busy", response_model=TechnicianOut)
async def mark_busy(
    technician_id: uuid.UUID,
    body: BusyIn,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> TechnicianOut:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    await service.mark_busy(tech, body.minutes)
    return _tech_out(tech)


@router.delete("/technicians/{technician_id}/busy", response_model=TechnicianOut)
async def clear_busy(
    technician_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> TechnicianOut:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    await service.clear_busy(tech)
    return _tech_out(tech)


@router.get("/technicians/{technician_id}/calendar", response_model=CalendarLinkOut)
async def calendar_link(
    technician_id: uuid.UUID,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
    rotate: bool = Query(False),
) -> CalendarLinkOut:
    """Private calendar feed for one technician (subscribe from Google/Apple/Outlook)."""
    tech = await ShopService(session, c).get_technician(principal.shop, technician_id)
    service = CalendarService(session, c)
    url = service.feed_url(await service.feed_token(tech, rotate=rotate))
    webcal = "webcal://" + url.split("://", 1)[1]
    return CalendarLinkOut(
        url=url,
        webcal_url=webcal,
        google_url=f"https://calendar.google.com/calendar/r?cid={quote(webcal, safe='')}",
    )


@router.get("/readiness")
async def readiness(principal: ShopDep, session: SessionDep, c: ContainerDep) -> dict[str, Any]:
    """Can homeowners be matched to this shop right now? If not, why."""
    return await ShopService(session, c).readiness(principal.shop)


# --- Availability + dashboard -------------------------------------------------------------------
@router.get("/availability", response_model=list[TechDayOut])
async def availability(
    principal: ShopDep, session: SessionDep, c: ContainerDep, day: date | None = Query(None)
) -> list[TechDayOut]:
    board = await ShopService(session, c).availability_board(principal.shop, day)
    return [
        TechDayOut(
            technician=_tech_out(d.technician),
            blocks=[
                BlockOut(
                    kind=b.kind.value,
                    starts_at=b.starts_at,
                    ends_at=b.ends_at,
                    label=b.label,
                    source=b.source,
                )
                for b in d.blocks
            ],
            free_now=d.free_now,
            on_job=d.on_job,
        )
        for d in board
    ]


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(principal: ShopDep, session: SessionDep, c: ContainerDep) -> DashboardOut:
    return DashboardOut(**await ShopService(session, c).dashboard(principal.shop))


# --- Offers & jobs ------------------------------------------------------------------------------
async def _job(
    session: SessionDep, c: ContainerDep, principal: ShopDep, job_id: uuid.UUID
) -> ServiceRequest:
    return await JobService(session, c).get_for_shop(job_id, principal.shop)


async def _present(session: SessionDep, c: ContainerDep, request: ServiceRequest) -> ShopJobOut:
    await session.flush()
    await session.refresh(request)
    return shop_job_out(c, request)


@router.get("/jobs", response_model=list[ShopJobOut])
async def list_jobs(
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
    status_filter: list[str] | None = Query(None, alias="status"),
) -> list[ShopJobOut]:
    service = JobService(session, c)
    jobs = await service.list_for_shop(principal.shop, status_filter)
    return [await _present_for(session, c, principal, j, service) for j in jobs]


async def _present_for(
    session: SessionDep,
    c: ContainerDep,
    principal: ShopDep,
    request: ServiceRequest,
    service: JobService | None = None,
) -> ShopJobOut:
    """A job as this shop sees it (its own offer's timing when offered to several shops)."""
    if request.shop_id == principal.shop.id:
        return shop_job_out(c, request)
    offer = await (service or JobService(session, c)).open_offer(request, principal.shop)
    tech = await session.get(Technician, offer.technician_id) if offer else None
    return shop_job_out(c, request, offer, tech.name if tech else None)


@router.get("/jobs/{job_id}", response_model=ShopJobOut)
async def get_job(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    return await _present_for(session, c, principal, await _job(session, c, principal, job_id))


@router.get("/jobs/{job_id}/technician-options", response_model=list[TechOptionOut])
async def technician_options(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> list[TechOptionOut]:
    """Who could go, soonest first, for the office choosing a technician."""
    request = await _job(session, c, principal, job_id)
    rows = await MatchingService(session, c).technician_options(request, principal.shop)
    suggested_id = rows[0][0].id if rows else None
    out = []
    for tech, option, reason in rows:
        is_suggested = tech.id == suggested_id and reason is None
        out.append(
            TechOptionOut(
                technician_id=tech.id,
                name=tech.name,
                arrival_at=option.arrival_at
                if option
                else (request.eta_at if is_suggested else None),
                distance_km=round(option.distance_km, 1)
                if option
                else (request.distance_km if is_suggested else None),
                available=reason is None,
                reason=reason,
                suggested=is_suggested,
            )
        )
    return out


@router.post("/jobs/{job_id}/accept", response_model=ShopJobOut)
async def accept_job(
    job_id: uuid.UUID, body: AcceptIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    request = await _job(session, c, principal, job_id)
    await MatchingService(session, c).shop_accept(request, principal.shop, body.technician_id)
    return await _present(session, c, request)


@router.post("/jobs/{job_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_job(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> None:
    request = await _job(session, c, principal, job_id)
    await MatchingService(session, c).shop_decline(request, principal.shop)


@router.post("/jobs/{job_id}/en-route", response_model=ShopJobOut)
async def en_route(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    request = await _job(session, c, principal, job_id)
    await JobService(session, c).mark_en_route(request)
    return await _present(session, c, request)


@router.post("/jobs/{job_id}/on-site", response_model=ShopJobOut)
async def on_site(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    request = await _job(session, c, principal, job_id)
    await JobService(session, c).mark_on_site(request)
    return await _present(session, c, request)


@router.post("/jobs/{job_id}/quote", response_model=ShopJobOut)
async def submit_quote(
    job_id: uuid.UUID, body: QuoteIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    request = await _job(session, c, principal, job_id)
    await JobService(session, c).submit_quote(
        request, final_price_cents=body.final_price_cents, notes=body.notes
    )
    return await _present(session, c, request)


@router.post("/jobs/{job_id}/complete", response_model=ShopJobOut)
async def complete_job(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    request = await _job(session, c, principal, job_id)
    await JobService(session, c).complete(request)
    return await _present(session, c, request)


@router.get("/technicians/{technician_id}", response_model=TechnicianOut)
async def get_technician(
    technician_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> TechnicianOut:
    tech = await ShopService(session, c).get_technician(principal.shop, technician_id)
    if tech is None:
        raise NotFound("Technician not found")
    return _tech_out(tech)


# --- Technician app access --------------------------------------------------------------------
@router.post("/technicians/{technician_id}/invite", response_model=TechInviteOut)
async def invite_technician(
    technician_id: uuid.UUID,
    body: TechInviteIn,
    principal: ShopDep,
    session: SessionDep,
    c: ContainerDep,
) -> TechInviteOut:
    """Email the technician an invite (the portal sends it through Firebase)."""
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    link = await service.invite_technician(
        principal.shop,
        tech,
        str(body.email),
        body.model_dump(include={"can_respond_offers", "can_contact_customers", "schedule_view"}),
    )
    return TechInviteOut(
        technician=_tech_out(tech),
        email_link=EmailLinkOut(
            email=link.email,
            continue_url=link.continue_url,
            delivery=link.delivery,
            dev_link=link.dev_link,
        ),
    )


@router.delete("/technicians/{technician_id}/app-access", response_model=TechnicianOut)
async def remove_app_access(
    technician_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> TechnicianOut:
    service = ShopService(session, c)
    tech = await service.get_technician(principal.shop, technician_id)
    await service.remove_app_access(tech)
    return _tech_out(tech)


# --- Chat -----------------------------------------------------------------------------------
@router.get("/jobs/{job_id}/messages", response_model=list[MessageOut])
async def job_messages(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> list[MessageOut]:
    request = await _job(session, c, principal, job_id)
    return [message_out(m) for m in await MessageService(session, c).list(request)]


@router.post(
    "/jobs/{job_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED
)
async def send_job_message(
    job_id: uuid.UUID, body: MessageIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> MessageOut:
    request = await _job(session, c, principal, job_id)
    message = await MessageService(session, c).post(
        request, sender="shop", sender_name=principal.shop.name, body=body.body
    )
    return message_out(message)
