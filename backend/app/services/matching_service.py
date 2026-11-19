"""Orchestrates matching: propose → confirm (hold) → offer to shop → dispatch,
plus the waitlist and expiry/re-matching handled by the background worker.

The algorithm itself is in domain/matching.py (earliest arrival per request, the
Hungarian algorithm for a backlog)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, Forbidden, InvalidState
from app.domain.enums import Actor, EquipmentType, RequestStatus
from app.domain.geo import LatLng, haversine_km
from app.domain.matching import (
    MatchCriteria,
    NoMatchReport,
    Option,
    PlanSettings,
    assign_batch,
    plan_option,
    plan_options,
)
from app.models import Homeowner, ServiceRequest, Shop, Technician
from app.services.availability_service import AvailabilityService
from app.services.calendar_service import CalendarService
from app.services.lifecycle import clear_assignment, transition
from app.services.notifications import notify_homeowner
from app.services.payment_service import PaymentService

log = logging.getLogger(__name__)
S = RequestStatus
MAX_RESERVE_ATTEMPTS = 3
# Bookings this far ahead give the shop until shortly before the visit to accept.
SCHEDULED_AFTER = timedelta(hours=2)
SCHEDULED_ACCEPT_LEAD = timedelta(hours=1)


class MatchingService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container
        self.settings = container.settings
        self.availability = AvailabilityService(session, container)
        self.payments = PaymentService(session, container)
        self.calendar = CalendarService(session, container)

    # --- Criteria ---------------------------------------------------------------
    @staticmethod
    def criteria_for(request: ServiceRequest) -> MatchCriteria:
        unit = (request.unit_info or {}).get("equipment_type") or EquipmentType.UNKNOWN.value
        return MatchCriteria(
            location=LatLng(request.lat, request.lng),
            equipment_type=unit,
            requires_refrigerant_work=request.requires_refrigerant_work,
            excluded_technician_ids=frozenset(
                uuid.UUID(t) for t in (request.declined_technician_ids or [])
            ),
        )

    @property
    def plan_settings(self) -> PlanSettings:
        return PlanSettings(
            job_duration=timedelta(minutes=self.settings.default_job_duration_minutes),
            speed_kmh=self.settings.average_travel_speed_kmh,
            horizon=timedelta(days=self.settings.match_horizon_days),
        )

    async def _pick_and_reserve(
        self, request: ServiceRequest, now: datetime
    ) -> tuple[Option | None, NoMatchReport]:
        """Pick the tech who can arrive soonest and lock them, re-checking that nobody
        booked the same time meanwhile."""
        criteria = self.criteria_for(request)
        report = NoMatchReport()
        for _ in range(MAX_RESERVE_ATTEMPTS):
            pool = await self.availability.load_candidates(near=criteria.location, now=now)
            options, report = plan_options(
                [a.candidate for a in pool], criteria, now, self.plan_settings
            )
            if not options:
                return None, report
            best = options[0]
            if await self._still_free(best, criteria, now):
                return best, report
        return None, report

    async def _still_free(self, option: Option, criteria: MatchCriteria, now: datetime) -> bool:
        # Row lock (Postgres) so concurrent bookings for this tech queue up, then
        # re-plan with fresh data: the same slot must still be open.
        await self.s.scalar(
            select(Technician.id)
            .where(Technician.id == option.candidate.technician_id)
            .with_for_update()
        )
        pool = await self.availability.load_candidates(near=criteria.location, now=now)
        fresh = next(
            (
                a.candidate
                for a in pool
                if a.candidate.technician_id == option.candidate.technician_id
            ),
            None,
        )
        if fresh is None:
            return False
        again = plan_option(fresh, criteria, now, self.plan_settings)
        return again is not None and again.start_at == option.start_at

    def _assign(self, request: ServiceRequest, option: Option, now: datetime) -> None:
        request.technician_id = option.candidate.technician_id
        request.shop_id = option.candidate.shop_id
        request.distance_km = round(option.distance_km, 1)
        request.eta_at = option.arrival_at
        request.waitlisted_at = None
        request.waitlist_eta_minutes = None
        request.waitlist_position = None
        request.waitlist_reason = None

    def _offer_deadline(self, request: ServiceRequest, now: datetime) -> datetime:
        """Shops get a couple of minutes for jobs happening now; for a visit booked for
        later (e.g. tomorrow morning) they have until an hour before it."""
        quick = now + timedelta(seconds=self.settings.offer_ttl_seconds)
        if request.eta_at and request.eta_at - now > SCHEDULED_AFTER:
            return max(quick, request.eta_at - SCHEDULED_ACCEPT_LEAD)
        return quick

    async def _waitlist(
        self, request: ServiceRequest, now: datetime, report: NoMatchReport, note: str
    ) -> None:
        request.waitlist_reason = report.message()
        if request.status != S.WAITLISTED.value:
            request.waitlisted_at = now
            transition(self.s, request, S.WAITLISTED, Actor.SYSTEM, note=note)

    # --- Homeowner actions --------------------------------------------------------
    async def find_technician(self, request: ServiceRequest) -> None:
        if request.status not in (S.ANALYZED.value, S.WAITLISTED.value):
            raise InvalidState("This request isn't ready for matching")
        now = self.c.clock.now()
        best, report = await self._pick_and_reserve(request, now)
        if best:
            self._assign(request, best, now)
            request.proposal_expires_at = now + timedelta(
                seconds=self.settings.proposal_ttl_seconds
            )
            transition(
                self.s,
                request,
                S.PROPOSED,
                Actor.HOMEOWNER,
                data={
                    "technician_id": str(best.candidate.technician_id),
                    "arrival_at": best.arrival_at.isoformat(),
                },
            )
        else:
            await self._waitlist(request, now, report, "No technician available")
            await self.s.flush()
            await self.refresh_waitlist_estimates(now)

    async def confirm_booking(self, request: ServiceRequest, homeowner: Homeowner) -> None:
        now = self.c.clock.now()
        if request.status != S.PROPOSED.value:
            raise InvalidState("There is no technician waiting for your confirmation")
        if request.proposal_expires_at and request.proposal_expires_at <= now:
            raise InvalidState("This match expired. Please search again.", code="proposal_expired")
        shop = await self.s.get(Shop, request.shop_id)
        if shop is None:
            raise InvalidState("This shop is no longer available")
        await self.payments.place_hold(request, homeowner, shop, request.estimate_low_cents or 0)
        request.confirmed_at = now
        request.proposal_expires_at = None
        request.offer_expires_at = self._offer_deadline(request, now)
        transition(self.s, request, S.OFFERED, Actor.HOMEOWNER)
        await self.calendar.book(request)

    async def cancel(self, request: ServiceRequest, actor: Actor, reason: str) -> None:
        await self.payments.release_hold(request)
        await self.calendar.release(request)
        clear_assignment(request)
        request.canceled_reason = reason[:200]
        transition(self.s, request, S.CANCELED, actor, note=reason[:300])

    # --- Shop actions -------------------------------------------------------------
    async def shop_accept(
        self, request: ServiceRequest, shop: Shop, technician_id: uuid.UUID | None
    ) -> None:
        now = self.c.clock.now()
        self._ensure_open_offer(request, shop, now)
        if technician_id and technician_id != request.technician_id:
            await self._reassign_within_shop(request, shop, technician_id, now)
        request.offer_expires_at = None
        transition(self.s, request, S.DISPATCHED, Actor.SHOP)
        await self.calendar.confirm(request)
        tech = await self.s.get(Technician, request.technician_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        if tech and homeowner:
            await notify_homeowner(
                self.c,
                homeowner,
                f"{tech.name} from {shop.name} accepted your HVAC request "
                "and will head your way shortly.",
            )

    async def shop_decline(self, request: ServiceRequest, shop: Shop) -> None:
        self._ensure_open_offer(request, shop, self.c.clock.now())
        await self._offer_to_next(request, reason="Shop declined")

    def _ensure_open_offer(self, request: ServiceRequest, shop: Shop, now: datetime) -> None:
        if request.shop_id != shop.id:
            raise Forbidden("This request isn't assigned to your shop")
        if request.status != S.OFFERED.value:
            raise InvalidState("This offer is no longer open")
        if request.offer_expires_at and request.offer_expires_at <= now:
            raise InvalidState("This offer expired", code="offer_expired")

    async def _reassign_within_shop(
        self, request: ServiceRequest, shop: Shop, technician_id: uuid.UUID, now: datetime
    ) -> None:
        old_tech = request.technician_id
        # Free the current tech's slot so it doesn't block the new plan.
        request.technician_id = None
        await self.s.flush()
        pool = await self.availability.load_candidates(
            near=LatLng(request.lat, request.lng), now=now
        )
        match = next(
            (a.candidate for a in pool if a.candidate.technician_id == technician_id), None
        )
        option = (
            plan_option(match, self.criteria_for(request), now, self.plan_settings)
            if match is not None and match.shop_id == shop.id
            else None
        )
        if option is None:
            request.technician_id = old_tech
            raise AppError(
                "That technician isn't qualified or has no opening for this job",
                code="technician_unavailable",
            )
        self._assign(request, option, now)

    async def _offer_to_next(self, request: ServiceRequest, *, reason: str) -> None:
        """After a decline/expiry: offer to the next best tech or put back on the waitlist."""
        now = self.c.clock.now()
        declined = set(request.declined_technician_ids or [])
        if request.technician_id:
            declined.add(str(request.technician_id))
        request.declined_technician_ids = sorted(declined)
        await self.payments.release_hold(request)
        await self.calendar.release(request)
        clear_assignment(request)
        best, report = await self._pick_and_reserve(request, now)
        if best:
            await self._offer_confirmed(request, best, now, note=reason)
        else:
            await self._waitlist(request, now, report, reason)

    async def _offer_confirmed(
        self, request: ServiceRequest, best: Option, now: datetime, note: str
    ) -> None:
        """Offer an already-confirmed request to a new tech (new hold for the new shop)."""
        self._assign(request, best, now)
        shop = await self.s.get(Shop, request.shop_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert shop and homeowner
        await self.payments.place_hold(request, homeowner, shop, request.estimate_low_cents or 0)
        request.offer_expires_at = self._offer_deadline(request, now)
        transition(self.s, request, S.OFFERED, Actor.SYSTEM, note=note)
        await self.calendar.book(request)

    # --- Background work (called by the worker) -----------------------------------------
    async def expire_proposals(self) -> int:
        now = self.c.clock.now()
        rows = list(
            await self.s.scalars(
                select(ServiceRequest).where(
                    ServiceRequest.status == S.PROPOSED.value,
                    ServiceRequest.proposal_expires_at <= now,
                )
            )
        )
        for request in rows:
            clear_assignment(request)
            transition(self.s, request, S.ANALYZED, Actor.SYSTEM, note="Proposal expired")
        return len(rows)

    async def expire_offers(self) -> int:
        now = self.c.clock.now()
        rows = list(
            await self.s.scalars(
                select(ServiceRequest).where(
                    ServiceRequest.status == S.OFFERED.value,
                    ServiceRequest.offer_expires_at <= now,
                )
            )
        )
        for request in rows:
            await self._offer_to_next(request, reason="Shop didn't respond in time")
        return len(rows)

    async def process_waitlist(self) -> int:
        """Place waiting homeowners, all at once: the Hungarian algorithm assigns techs to
        requests minimizing total arrival time, favoring those who waited longest.
        Returns how many were matched."""
        now = self.c.clock.now()
        queue = list(
            await self.s.scalars(
                select(ServiceRequest)
                .where(ServiceRequest.status == S.WAITLISTED.value)
                .order_by(ServiceRequest.waitlisted_at)
            )
        )
        if not queue:
            return 0
        candidates = {
            a.candidate.technician_id: a.candidate
            for request in queue
            for a in await self.availability.load_candidates(
                near=LatLng(request.lat, request.lng), now=now
            )
        }
        batch = [
            (
                self.criteria_for(r),
                (now - r.waitlisted_at).total_seconds() / 60 if r.waitlisted_at else 0.0,
            )
            for r in queue
        ]
        assigned = assign_batch(batch, list(candidates.values()), now, self.plan_settings)
        matched = 0
        for index, option in assigned.items():
            request = queue[index]
            try:
                if not await self._still_free(option, self.criteria_for(request), now):
                    continue  # picked up again on the next tick
                await self._place_from_waitlist(request, option, now)
                matched += 1
            except AppError as exc:
                # e.g. card declined on re-hold: keep them waitlisted, unassigned.
                clear_assignment(request)
                log.warning("Waitlist match failed for %s: %s", request.id, exc.message)
            await self.s.flush()
        await self.refresh_waitlist_estimates(now)
        return matched

    async def _place_from_waitlist(
        self, request: ServiceRequest, option: Option, now: datetime
    ) -> None:
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert homeowner
        if request.confirmed_at:
            await self._offer_confirmed(request, option, now, note="Matched from waitlist")
        else:
            self._assign(request, option, now)
            request.proposal_expires_at = now + timedelta(
                seconds=self.settings.proposal_ttl_seconds
            )
            transition(self.s, request, S.PROPOSED, Actor.SYSTEM, note="Matched from waitlist")
        await notify_homeowner(
            self.c,
            homeowner,
            "Good news: a technician is available for your HVAC request. Open the app to confirm.",
        )

    async def refresh_waitlist_estimates(self, now: datetime) -> None:
        """Queue position among waiting homeowners in the same area. (No time estimate:
        a waitlisted request has no technician with an opening in the planning window.)"""
        queue = list(
            await self.s.scalars(
                select(ServiceRequest)
                .where(ServiceRequest.status == S.WAITLISTED.value)
                .order_by(ServiceRequest.waitlisted_at)
            )
        )
        for request in queue:
            ahead = sum(
                1
                for other in queue
                if other.waitlisted_at
                and request.waitlisted_at
                and other.waitlisted_at < request.waitlisted_at
                and _overlaps(other, request)
            )
            request.waitlist_position = ahead + 1
            request.waitlist_eta_minutes = None


def _overlaps(a: ServiceRequest, b: ServiceRequest, radius_km: float = 40.0) -> bool:
    return haversine_km(LatLng(a.lat, a.lng), LatLng(b.lat, b.lng)) <= radius_km
