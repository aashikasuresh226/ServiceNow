"""Orchestrates matching: propose → confirm (hold) → offer to shop → dispatch,
plus the live waitlist and expiry/re-matching handled by the background worker."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, Forbidden, InvalidState
from app.domain.enums import ACTIVE_JOB_STATUSES, Actor, EquipmentType, RequestStatus
from app.domain.geo import LatLng, haversine_km, travel_minutes
from app.domain.matching import MatchCriteria, RankedCandidate, eligible_candidates, pick_best
from app.domain.waitlist import TechSlot, estimate_wait_minutes
from app.models import Homeowner, ServiceRequest, Shop, Technician
from app.services.availability_service import AvailabilityService
from app.services.lifecycle import clear_assignment, transition
from app.services.notifications import notify_homeowner
from app.services.payment_service import PaymentService

log = logging.getLogger(__name__)
S = RequestStatus
MAX_RESERVE_ATTEMPTS = 3


class MatchingService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container
        self.settings = container.settings
        self.availability = AvailabilityService(session, container)
        self.payments = PaymentService(session, container)

    # --- Criteria ---------------------------------------------------------------
    @staticmethod
    def criteria_for(request: ServiceRequest) -> MatchCriteria:
        unit = (request.unit_info or {}).get("equipment_type") or EquipmentType.UNKNOWN.value
        return MatchCriteria(
            location=LatLng(request.lat, request.lng),
            equipment_type=unit,
            requires_refrigerant_work=request.requires_refrigerant_work,
            soft_skills=frozenset(request.soft_skills or []),
            require_all_skills=request.require_all_skills,
            excluded_technician_ids=frozenset(
                uuid.UUID(t) for t in (request.declined_technician_ids or [])
            ),
        )

    async def _pick_and_reserve(
        self, request: ServiceRequest, now: datetime
    ) -> RankedCandidate | None:
        """Pick the best free tech and lock them so two requests can't grab the same one."""
        criteria = self.criteria_for(request)
        excluded: set[uuid.UUID] = set()
        for _ in range(MAX_RESERVE_ATTEMPTS):
            pool = await self.availability.load_candidates(near=criteria.location, now=now)
            candidates = [a.candidate for a in pool if a.candidate.technician_id not in excluded]
            best = pick_best(
                candidates,
                criteria,
                skill_preference_max_extra_km=self.settings.skill_preference_max_extra_km,
            )
            if best is None:
                return None
            # Row lock (Postgres) then re-check that nobody claimed the tech meanwhile.
            await self.s.scalar(
                select(Technician.id)
                .where(Technician.id == best.candidate.technician_id)
                .with_for_update()
            )
            taken = await self.s.scalar(
                select(ServiceRequest.id).where(
                    ServiceRequest.technician_id == best.candidate.technician_id,
                    ServiceRequest.status.in_([st.value for st in ACTIVE_JOB_STATUSES]),
                    ServiceRequest.id != request.id,
                )
            )
            if taken is None:
                return best
            excluded.add(best.candidate.technician_id)
        return None

    def _assign(self, request: ServiceRequest, best: RankedCandidate, now: datetime) -> None:
        request.technician_id = best.candidate.technician_id
        request.shop_id = best.candidate.shop_id
        request.distance_km = round(best.distance_km, 1)
        request.eta_at = now + timedelta(
            minutes=travel_minutes(best.distance_km, self.settings.average_travel_speed_kmh)
        )
        request.waitlisted_at = None
        request.waitlist_eta_minutes = None
        request.waitlist_position = None

    # --- Homeowner actions --------------------------------------------------------
    async def find_technician(self, request: ServiceRequest) -> None:
        if request.status not in (S.ANALYZED.value, S.WAITLISTED.value):
            raise InvalidState("This request isn't ready for matching")
        now = self.c.clock.now()
        best = await self._pick_and_reserve(request, now)
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
                data={"technician_id": str(best.candidate.technician_id)},
            )
        else:
            if request.status != S.WAITLISTED.value:
                request.waitlisted_at = now
                transition(self.s, request, S.WAITLISTED, Actor.SYSTEM, note="No tech free")
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
        request.offer_expires_at = now + timedelta(seconds=self.settings.offer_ttl_seconds)
        transition(self.s, request, S.OFFERED, Actor.HOMEOWNER)

    async def widen_search(self, request: ServiceRequest) -> None:
        """Drop soft-skill preferences to get matched faster."""
        if request.status != S.WAITLISTED.value:
            raise InvalidState("Only waitlisted requests can widen their search")
        request.soft_skills = []
        request.require_all_skills = False
        await self._rematch_waitlisted(request, self.c.clock.now())
        if request.status == S.WAITLISTED.value:
            await self.refresh_waitlist_estimates(self.c.clock.now())

    async def cancel(self, request: ServiceRequest, actor: Actor, reason: str) -> None:
        await self.payments.release_hold(request)
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
        pool = await self.availability.load_candidates(
            near=LatLng(request.lat, request.lng), now=now
        )
        match = next(
            (a.candidate for a in pool if a.candidate.technician_id == technician_id), None
        )
        if match is None or match.shop_id != shop.id:
            raise AppError("That technician can't take this job", code="invalid_technician")
        criteria = self.criteria_for(request)
        best = pick_best([match], criteria, skill_preference_max_extra_km=0)
        if best is None:
            raise AppError(
                "That technician isn't free or qualified for this job",
                code="technician_unavailable",
            )
        self._assign(request, best, now)

    async def _offer_to_next(self, request: ServiceRequest, *, reason: str) -> None:
        """After a decline/expiry: offer to the next best tech or put back on the waitlist."""
        now = self.c.clock.now()
        declined = set(request.declined_technician_ids or [])
        if request.technician_id:
            declined.add(str(request.technician_id))
        request.declined_technician_ids = sorted(declined)
        await self.payments.release_hold(request)
        clear_assignment(request)
        best = await self._pick_and_reserve(request, now)
        if best:
            await self._offer_confirmed(request, best, now, note=reason)
        else:
            request.waitlisted_at = now
            transition(self.s, request, S.WAITLISTED, Actor.SYSTEM, note=reason)

    async def _offer_confirmed(
        self, request: ServiceRequest, best: RankedCandidate, now: datetime, note: str
    ) -> None:
        """Offer an already-confirmed request to a new tech (new hold for the new shop)."""
        self._assign(request, best, now)
        shop = await self.s.get(Shop, request.shop_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert shop and homeowner
        await self.payments.place_hold(request, homeowner, shop, request.estimate_low_cents or 0)
        request.offer_expires_at = now + timedelta(seconds=self.settings.offer_ttl_seconds)
        transition(self.s, request, S.OFFERED, Actor.SYSTEM, note=note)

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
        """Match waitlisted homeowners in arrival order. Returns how many were matched."""
        now = self.c.clock.now()
        queue = list(
            await self.s.scalars(
                select(ServiceRequest)
                .where(ServiceRequest.status == S.WAITLISTED.value)
                .order_by(ServiceRequest.waitlisted_at)
            )
        )
        matched = 0
        for request in queue:
            try:
                if await self._rematch_waitlisted(request, now):
                    matched += 1
            except AppError as exc:
                # e.g. card declined on re-hold: keep them waitlisted, unassigned.
                clear_assignment(request)
                log.warning("Waitlist match failed for %s: %s", request.id, exc.message)
        await self.s.flush()
        await self.refresh_waitlist_estimates(now)
        return matched

    async def _rematch_waitlisted(self, request: ServiceRequest, now: datetime) -> bool:
        best = await self._pick_and_reserve(request, now)
        if best is None:
            return False
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert homeowner
        if request.confirmed_at:
            await self._offer_confirmed(request, best, now, note="Matched from waitlist")
        else:
            self._assign(request, best, now)
            request.proposal_expires_at = now + timedelta(
                seconds=self.settings.proposal_ttl_seconds
            )
            transition(self.s, request, S.PROPOSED, Actor.SYSTEM, note="Matched from waitlist")
        await self.s.flush()
        await notify_homeowner(
            self.c,
            homeowner,
            "Good news: a technician is available for your HVAC request. Open the app to confirm.",
        )
        return True

    async def refresh_waitlist_estimates(self, now: datetime) -> None:
        """Recompute each waitlisted request's queue position and ETA."""
        queue = list(
            await self.s.scalars(
                select(ServiceRequest)
                .where(ServiceRequest.status == S.WAITLISTED.value)
                .order_by(ServiceRequest.waitlisted_at)
            )
        )
        duration = timedelta(minutes=self.settings.default_job_duration_minutes)
        for request in queue:
            criteria = self.criteria_for(request)
            pool = await self.availability.load_candidates(near=criteria.location, now=now)
            eligible = {
                r.candidate.technician_id: r
                for r in eligible_candidates(
                    [a.candidate for a in pool], criteria, require_free_now=False
                )
            }
            slots = [
                TechSlot(
                    a.next_free_at,
                    travel_minutes(
                        eligible[a.candidate.technician_id].distance_km,
                        self.settings.average_travel_speed_kmh,
                    ),
                )
                for a in pool
                if a.candidate.technician_id in eligible and a.next_free_at is not None
            ]
            # Position: people ahead of you who could be served by the same techs.
            ahead = sum(
                1
                for other in queue
                if other.waitlisted_at
                and request.waitlisted_at
                and other.waitlisted_at < request.waitlisted_at
                and _overlaps(other, request)
            )
            request.waitlist_position = ahead + 1
            request.waitlist_eta_minutes = estimate_wait_minutes(
                slots, position=ahead + 1, now=now, job_duration=duration
            )


def _overlaps(a: ServiceRequest, b: ServiceRequest, radius_km: float = 40.0) -> bool:
    return haversine_km(LatLng(a.lat, a.lng), LatLng(b.lat, b.lng)) <= radius_km
