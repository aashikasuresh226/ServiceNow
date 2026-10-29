"""Shop portal endpoints: profile, payouts, scheduling, technicians, availability, jobs."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Query, status

from app.api.deps import ContainerDep, SessionDep, ShopDep
from app.api.presenters import shop_job_out
from app.core.errors import NotFound
from app.models import ServiceRequest, Technician
from app.schemas.api import (
    AcceptIn,
    BlockOut,
    BusyIn,
    CountOut,
    DashboardOut,
    LinkOut,
    LiveIn,
    PayoutScheduleIn,
    QuoteIn,
    SchedulingConnectIn,
    ShopJobOut,
    ShopMeOut,
    ShopOut,
    ShopUpdateIn,
    TechDayOut,
    TechnicianIn,
    TechnicianOut,
)
from app.services.availability_service import AvailabilityService
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.shop_service import ShopService

router = APIRouter(prefix="/shop", tags=["shop"])


def _me(principal: ShopDep) -> ShopMeOut:
    return ShopMeOut(
        user_email=principal.user.email,
        user_name=principal.user.name,
        shop=ShopOut.model_validate(principal.shop),
    )


def _tech_out(tech: Technician) -> TechnicianOut:
    return TechnicianOut.model_validate(tech)


# --- Profile, live switch, payouts --------------------------------------------------------------
@router.get("/me", response_model=ShopMeOut)
async def get_me(principal: ShopDep) -> ShopMeOut:
    return _me(principal)


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
    return _me(principal)


@router.put("/live", response_model=ShopMeOut)
async def set_live(
    body: LiveIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    await ShopService(session, c).set_live(principal.shop, body.is_live)
    return _me(principal)


@router.post("/payouts/onboarding-link", response_model=LinkOut)
async def payout_onboarding(principal: ShopDep, session: SessionDep, c: ContainerDep) -> LinkOut:
    url = await ShopService(session, c).payout_onboarding_link(principal.shop, principal.user)
    return LinkOut(url=url)


@router.post("/payouts/refresh", response_model=ShopMeOut)
async def refresh_payouts(principal: ShopDep, session: SessionDep, c: ContainerDep) -> ShopMeOut:
    await ShopService(session, c).refresh_payout_status(principal.shop)
    return _me(principal)


@router.put("/payouts/schedule", response_model=ShopMeOut)
async def payout_schedule(
    body: PayoutScheduleIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopMeOut:
    await ShopService(session, c).set_payout_schedule(principal.shop, body.schedule)
    return _me(principal)


# --- Scheduling software -------------------------------------------------------------------------
@router.put("/scheduling", response_model=CountOut)
async def connect_scheduling(
    body: SchedulingConnectIn, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> CountOut:
    """Verify credentials, store them encrypted, import technicians, run a first sync."""
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
                BlockOut(kind=b.kind.value, starts_at=b.starts_at, ends_at=b.ends_at)
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
    jobs = await JobService(session, c).list_for_shop(principal.shop, status_filter)
    return [shop_job_out(c, j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=ShopJobOut)
async def get_job(
    job_id: uuid.UUID, principal: ShopDep, session: SessionDep, c: ContainerDep
) -> ShopJobOut:
    return shop_job_out(c, await _job(session, c, principal, job_id))


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
