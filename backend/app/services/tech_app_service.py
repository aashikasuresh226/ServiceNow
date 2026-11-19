"""What a signed-in technician can see and do. Every permission the company set is
enforced here (not just hidden in the app):

- schedule_view "next": only the current/next job is visible, never the rest of the day;
- can_respond_offers: may accept/decline job offers (otherwise the office does);
- can_contact_customers: may see the customer's phone, call and chat.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, Forbidden, InvalidState, NotFound
from app.domain.enums import Actor, RequestStatus
from app.models import JobOffer, ServiceRequest, Shop, TechLocation, Technician
from app.services.job_service import JobService
from app.services.matching_service import MatchingService
from app.services.notifications import notify_homeowner

S = RequestStatus
WORKING = [S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS]
WORKING_VALUES = [s.value for s in WORKING]
# Jobs underway sort before ones that haven't started.
STARTED = {S.EN_ROUTE.value, S.ON_SITE.value, S.QUOTED.value, S.IN_PROGRESS.value}


@dataclass(frozen=True, slots=True)
class TechBoard:
    offers: list[ServiceRequest]
    jobs: list[ServiceRequest]
    hidden_jobs: int  # jobs not shown because the company set "next job only"
    recent: list[ServiceRequest]


class TechAppService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def board(self, tech: Technician) -> TechBoard:
        offers: list[ServiceRequest] = []
        shop = await self.s.get(Shop, tech.shop_id)
        # Offers reach technicians only when we pick the tech; otherwise the office (or
        # Housecall Pro's dispatcher) decides who goes.
        if tech.can_respond_offers and shop is not None and shop.dispatch_mode == "platform":
            offered = select(JobOffer.request_id).where(
                JobOffer.technician_id == tech.id, JobOffer.status == "open"
            )
            offers = list(
                await self.s.scalars(
                    select(ServiceRequest)
                    .where(
                        or_(
                            ServiceRequest.technician_id == tech.id,
                            ServiceRequest.id.in_(offered),
                        ),
                        ServiceRequest.status == S.OFFERED.value,
                    )
                    .order_by(ServiceRequest.eta_at)
                )
            )
        jobs = await self._working(tech)
        hidden = 0
        if tech.schedule_view == "next" and len(jobs) > 1:
            hidden = len(jobs) - 1
            jobs = jobs[:1]
        recent = list(
            await self.s.scalars(
                select(ServiceRequest)
                .where(
                    ServiceRequest.technician_id == tech.id,
                    ServiceRequest.status == S.COMPLETED.value,
                )
                .order_by(ServiceRequest.completed_at.desc())
                .limit(5 if tech.schedule_view == "full" else 0)
            )
        )
        return TechBoard(offers, jobs, hidden, recent)

    async def _working(self, tech: Technician) -> list[ServiceRequest]:
        rows = list(
            await self.s.scalars(
                select(ServiceRequest).where(
                    ServiceRequest.technician_id == tech.id,
                    ServiceRequest.status.in_(WORKING_VALUES),
                )
            )
        )
        far_future = self.c.clock.now().replace(year=9999)
        rows.sort(key=lambda r: (r.status not in STARTED, r.eta_at or far_future))
        return rows

    async def get(self, tech: Technician, request_id: uuid.UUID) -> ServiceRequest:
        """A job the technician may open: their offers (if allowed), visible jobs, recent."""
        board = await self.board(tech)
        for request in (*board.offers, *board.jobs, *board.recent):
            if request.id == request_id:
                return request
        raise NotFound("Job not found")

    # --- Offers ---------------------------------------------------------------------------
    def _require(self, allowed: bool, message: str) -> None:
        if not allowed:
            raise Forbidden(message, code="not_allowed")

    async def accept(self, tech: Technician, shop: Shop, request: ServiceRequest) -> None:
        self._require(tech.can_respond_offers, "Your company accepts jobs for you")
        await MatchingService(self.s, self.c).shop_accept(request, shop, tech.id, Actor.TECHNICIAN)

    async def decline(
        self, tech: Technician, shop: Shop, request: ServiceRequest, reason: str | None
    ) -> None:
        self._require(tech.can_respond_offers, "Your company accepts jobs for you")
        why = f"{tech.name} declined" + (f": {reason.strip()[:120]}" if reason else "")
        await MatchingService(self.s, self.c).shop_decline(request, shop, why)

    async def cant_make_it(self, request: ServiceRequest, reason: str | None) -> None:
        """Without accept/decline rights: tell the office so they can reassign."""
        if request.status != S.DISPATCHED.value:
            raise InvalidState("You can only do this before you start driving")
        request.technician_flag = (reason or "Can't make this job").strip()[:200]

    # --- Job progress -------------------------------------------------------------------------
    async def start_driving(self, request: ServiceRequest) -> None:
        await JobService(self.s, self.c).mark_en_route(request, Actor.TECHNICIAN)

    async def arrived(self, request: ServiceRequest) -> None:
        await JobService(self.s, self.c).mark_on_site(request, Actor.TECHNICIAN)

    async def quote(self, request: ServiceRequest, cents: int, notes: str | None) -> None:
        await JobService(self.s, self.c).submit_quote(
            request, final_price_cents=cents, notes=notes, actor=Actor.TECHNICIAN
        )

    async def complete(self, request: ServiceRequest) -> None:
        await JobService(self.s, self.c).complete(request, Actor.TECHNICIAN)

    async def update_location(
        self,
        tech: Technician,
        request: ServiceRequest,
        *,
        lat: float,
        lng: float,
        accuracy_m: float | None,
    ) -> None:
        """Only accepted while this job is en route: never before, never after arriving."""
        if request.status != S.EN_ROUTE.value or request.technician_id != tech.id:
            raise InvalidState("Location is only shared while driving to this job")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise AppError("Invalid location", code="invalid_location")
        now = self.c.clock.now()
        location = request.live_location or await self.s.scalar(
            select(TechLocation).where(TechLocation.request_id == request.id)
        )
        if location is None:
            location = TechLocation(request_id=request.id, technician_id=tech.id)
            self.s.add(location)
        location.lat, location.lng = lat, lng
        location.accuracy_m = accuracy_m
        location.recorded_at = now
        await self.s.flush()

    async def notify_customer(self, request: ServiceRequest, message: str) -> None:
        if request.homeowner:
            await notify_homeowner(self.c, request.homeowner, message)
