"""Orchestrates matching: propose → confirm (hold) → offer to shops → dispatch,
plus the waitlist and expiry/re-matching handled by the background worker.

Who gets the job (a tiered waterfall):
1. the homeowner's own pick (a company or technician) if they made one;
2. otherwise a returning customer's previous shop, if it can come nearly as soon;
3. an instant-book shop that can come nearly as soon (accepted automatically);
4. otherwise the soonest qualified technician's shop;
then on decline/no answer: the next best shop, one at a time, for a couple of rounds;
then several shops at once (first to accept wins); then the waitlist.

The algorithm itself is in domain/matching.py (earliest arrival per request, the
Hungarian algorithm for a backlog)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
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
from app.models import Homeowner, JobOffer, ServiceRequest, Shop, Technician
from app.services.availability_service import AvailabilityService
from app.services.calendar_service import CalendarService
from app.services.lifecycle import clear_assignment, clear_live_location, transition
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
            only_shop_id=request.preferred_shop_id,
            only_technician_id=request.preferred_technician_id,
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
            best = (await self._rank(request, options, now))[0]
            if await self._still_free(best, criteria, now):
                return best, report
        return None, report

    async def _rank(
        self, request: ServiceRequest, options: list[Option], now: datetime
    ) -> list[Option]:
        """Soonest first, but give a returning customer's shop, then instant-book shops,
        the first look when they can come nearly as soon."""
        if len(options) < 2 or request.preferred_shop_id or request.preferred_technician_id:
            return options
        soonest = options[0].arrival_at
        loyal = await self._previous_shops(request)
        for shop_id in loyal:
            pick = next((o for o in options if o.candidate.shop_id == shop_id), None)
            if pick and pick.arrival_at - soonest <= timedelta(
                minutes=self.settings.loyalty_max_delay_minutes
            ):
                return [pick, *[o for o in options if o is not pick]]
        window = timedelta(minutes=self.settings.instant_book_max_delay_minutes)
        for option in options:
            if option.arrival_at - soonest > window:
                break
            shop = await self.s.get(Shop, option.candidate.shop_id)
            if shop and await self._instant_book_open(shop, now):
                return [option, *[o for o in options if o is not option]]
        return options

    async def _previous_shops(self, request: ServiceRequest) -> list[uuid.UUID]:
        rows = await self.s.scalars(
            select(ServiceRequest.shop_id)
            .where(
                ServiceRequest.homeowner_id == request.homeowner_id,
                ServiceRequest.status == S.COMPLETED.value,
                ServiceRequest.shop_id.is_not(None),
            )
            .order_by(ServiceRequest.completed_at.desc())
            .limit(5)
        )
        # Then the companies they're already a customer of (e.g. imported from Housecall Pro).
        from app.services.customer_service import CustomerService  # avoid import cycle

        home = await CustomerService(self.s, self.c).home_shops(request.homeowner_id)
        return [r for r in dict.fromkeys([*rows, *home]) if r is not None]

    async def _instant_book_open(self, shop: Shop, now: datetime) -> bool:
        if not shop.instant_book or not shop.is_live:
            return False
        day_start = now - timedelta(hours=24)
        used = await self.s.scalar(
            select(func.count(ServiceRequest.id)).where(
                ServiceRequest.shop_id == shop.id,
                ServiceRequest.instant_booked.is_(True),
                ServiceRequest.confirmed_at >= day_start,
            )
        )
        return int(used or 0) < shop.instant_book_daily_limit

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
        if best is None and report.chosen:
            # The homeowner picked someone who can't take it: say so and let them choose
            # again (don't silently waitlist them).
            raise AppError(report.message(), code="provider_unavailable")
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
        request.offer_round = 1
        self._record_offer(request, now)
        transition(self.s, request, S.OFFERED, Actor.HOMEOWNER)
        await self.calendar.book(request)
        await self._maybe_instant_book(request, shop, now)

    def _record_offer(self, request: ServiceRequest, now: datetime) -> None:
        """The offer to the shop the request is currently assigned to."""
        assert request.shop_id and request.technician_id and request.offer_expires_at
        self.s.add(
            JobOffer(
                request_id=request.id,
                shop_id=request.shop_id,
                technician_id=request.technician_id,
                arrival_at=request.eta_at or now,
                distance_km=request.distance_km or 0.0,
                round=request.offer_round,
                expires_at=request.offer_expires_at,
            )
        )

    async def _maybe_instant_book(self, request: ServiceRequest, shop: Shop, now: datetime) -> None:
        if request.status == S.OFFERED.value and await self._instant_book_open(shop, now):
            request.instant_booked = True
            await self.s.flush()
            await self.shop_accept(request, shop, None, Actor.SYSTEM)

    async def cancel(self, request: ServiceRequest, actor: Actor, reason: str) -> None:
        if request.external_job_id and request.shop_id:
            from app.services.hcp_mirror import HcpMirror  # avoid import cycle

            await HcpMirror(self.s, self.c).record(request, "canceled", reason=reason)
        await self._close_offers(request, accepted=None)
        await clear_live_location(self.s, request)
        await self.payments.release_hold(request)
        await self.calendar.release(request)
        clear_assignment(request)
        request.canceled_reason = reason[:200]
        transition(self.s, request, S.CANCELED, actor, note=reason[:300])

    # --- Shop actions -------------------------------------------------------------
    async def shop_accept(
        self,
        request: ServiceRequest,
        shop: Shop,
        technician_id: uuid.UUID | None,
        actor: Actor = Actor.SHOP,
    ) -> None:
        now = self.c.clock.now()
        offer = await self._open_offer(request, shop, now)
        if offer is not None and request.shop_id != shop.id:
            # Several shops were offered the job at once: this one was first.
            await self._switch_to_offer(request, shop, offer, now)
        if technician_id and technician_id != request.technician_id:
            await self._reassign_within_shop(request, shop, technician_id, now)
        await self._close_offers(request, accepted=offer)
        request.offer_expires_at = None
        request.technician_flag = None
        # Shops whose Housecall Pro dispatcher assigns technicians pick the tech later
        # (unless the homeowner chose a specific technician, or the office picked one now).
        request.technician_confirmed = not (
            shop.dispatch_mode == "software"
            and not technician_id
            and request.preferred_technician_id != request.technician_id
        )
        note = "Instant book" if request.instant_booked and actor == Actor.SYSTEM else None
        transition(self.s, request, S.DISPATCHED, actor, note=note)
        await self.calendar.confirm(request)
        tech = await self.s.get(Technician, request.technician_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        if tech and homeowner:
            await notify_homeowner(
                self.c,
                homeowner,
                f"{tech.name} from {shop.name} accepted your HVAC request "
                "and will head your way shortly."
                if request.technician_confirmed
                else f"{shop.name} accepted your HVAC request and is assigning a technician.",
            )
        from app.services.hcp_mirror import connected  # avoid import cycle

        if connected(shop):
            # Every job of a shop on Housecall Pro goes into it, whatever the dispatch mode,
            # so the office and customers see the same job in both places.
            from app.services.external_jobs import ExternalJobService

            await ExternalJobService(self.s, self.c).push(request, shop)

    async def shop_decline(
        self, request: ServiceRequest, shop: Shop, reason: str = "Shop declined"
    ) -> None:
        now = self.c.clock.now()
        offer = await self._open_offer(request, shop, now)
        others = [
            o
            for o in await self._offers(request, status="open")
            if offer is None or o.id != offer.id
        ]
        if offer is not None:
            offer.status = "declined"
            declined = set(request.declined_technician_ids or [])
            declined.add(str(offer.technician_id))
            request.declined_technician_ids = sorted(declined)
        if others:
            # Other shops still have this offer open: wait for them.
            if request.shop_id == shop.id:
                await self._switch_to_offer(request, None, others[0], now)
            return
        await self._offer_to_next(request, reason=reason[:300])

    async def _offers(
        self, request: ServiceRequest, *, status: str | None = None
    ) -> list[JobOffer]:
        query = select(JobOffer).where(JobOffer.request_id == request.id)
        if status:
            query = query.where(JobOffer.status == status)
        return list(await self.s.scalars(query.order_by(JobOffer.arrival_at)))

    async def _open_offer(
        self, request: ServiceRequest, shop: Shop, now: datetime
    ) -> JobOffer | None:
        """The shop's open offer for this request (raises if it has none)."""
        if request.status != S.OFFERED.value:
            if request.shop_id != shop.id and not await self._had_offer(request, shop):
                raise Forbidden("This request isn't assigned to your shop")
            raise InvalidState("This offer is no longer open")
        if request.offer_expires_at and request.offer_expires_at <= now:
            raise InvalidState("This offer expired", code="offer_expired")
        offer = await self.s.scalar(
            select(JobOffer).where(
                JobOffer.request_id == request.id,
                JobOffer.shop_id == shop.id,
                JobOffer.status == "open",
            )
        )
        if offer is None and request.shop_id != shop.id:
            raise Forbidden("This request isn't assigned to your shop")
        return offer

    async def _had_offer(self, request: ServiceRequest, shop: Shop) -> bool:
        found = await self.s.scalar(
            select(JobOffer.id).where(
                JobOffer.request_id == request.id, JobOffer.shop_id == shop.id
            )
        )
        return found is not None

    async def _switch_to_offer(
        self, request: ServiceRequest, shop: Shop | None, offer: JobOffer, now: datetime
    ) -> None:
        """Move the request (hold, calendar) to the shop/tech of another open offer."""
        target = shop or await self.s.get(Shop, offer.shop_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert target and homeowner
        await self.payments.release_hold(request)
        await self.calendar.release(request)
        request.technician_id = offer.technician_id
        request.shop_id = offer.shop_id
        request.eta_at = offer.arrival_at
        request.distance_km = offer.distance_km
        await self.payments.place_hold(request, homeowner, target, request.estimate_low_cents or 0)
        await self.calendar.book(request)

    async def _close_offers(self, request: ServiceRequest, *, accepted: JobOffer | None) -> None:
        await self.s.execute(
            update(JobOffer)
            .where(JobOffer.request_id == request.id, JobOffer.status == "open")
            .values(status="withdrawn")
        )
        if accepted is not None:
            accepted.status = "accepted"

    async def technician_options(
        self, request: ServiceRequest, shop: Shop
    ) -> list[tuple[Technician, Option | None, str | None]]:
        """For the office choosing who goes: each of its technicians with their soonest
        arrival for this job, or why they can't take it. Suggested tech first."""
        now = self.c.clock.now()
        offer = (
            await self._open_offer(request, shop, now)
            if request.status == S.OFFERED.value
            else None
        )
        suggested = offer.technician_id if offer else request.technician_id
        criteria = replace(
            self.criteria_for(request), only_shop_id=shop.id, only_technician_id=None
        )
        pool = {
            a.candidate.technician_id: a.candidate
            for a in await self.availability.load_candidates(near=criteria.location, now=now)
        }
        techs = list(
            await self.s.scalars(
                select(Technician).where(Technician.shop_id == shop.id).order_by(Technician.name)
            )
        )
        rows: list[tuple[Technician, Option | None, str | None]] = []
        for tech in techs:
            if tech.id == suggested:
                rows.append((tech, None, None))  # already planned for this job
                continue
            candidate = pool.get(tech.id)
            option = (
                plan_option(candidate, criteria, now, self.plan_settings) if candidate else None
            )
            reason = None
            if not tech.is_active:
                reason = "Not active"
            elif candidate is None:
                reason = "Too far away or no working hours"
            elif option is None:
                reason = "Not qualified, or no opening in the next week"
            rows.append((tech, option, reason))
        far = now.replace(year=9999)
        rows.sort(
            key=lambda r: (
                r[0].id != suggested,
                r[1] is None and r[0].id != suggested,
                r[1].arrival_at if r[1] else far,
            )
        )
        return rows

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
        # A picked technician declined: try other techs at the same company, then anyone.
        request.preferred_technician_id = None
        await self._close_offers(request, accepted=None)
        if request.offer_round >= self.settings.waterfall_single_rounds:
            # Several declines/no answers: offer to the best few shops at once.
            request.preferred_shop_id = None
            options, report = await self._broadcast_options(request, now)
            if options:
                await self._offer_confirmed(request, options[0], now, note=reason, also=options[1:])
                return
            await self._waitlist(request, now, report, reason)
            return
        best, report = await self._pick_and_reserve(request, now)
        if best is None and request.preferred_shop_id:
            request.preferred_shop_id = None
            best, report = await self._pick_and_reserve(request, now)
        if best:
            await self._offer_confirmed(request, best, now, note=reason)
        else:
            await self._waitlist(request, now, report, reason)

    async def _broadcast_options(
        self, request: ServiceRequest, now: datetime
    ) -> tuple[list[Option], NoMatchReport]:
        """The soonest option at each of the best few shops."""
        criteria = self.criteria_for(request)
        pool = await self.availability.load_candidates(near=criteria.location, now=now)
        options, report = plan_options(
            [a.candidate for a in pool], criteria, now, self.plan_settings
        )
        per_shop: dict[uuid.UUID, Option] = {}
        for option in options:
            per_shop.setdefault(option.candidate.shop_id, option)
            if len(per_shop) >= self.settings.broadcast_size:
                break
        return list(per_shop.values()), report

    async def _offer_confirmed(
        self,
        request: ServiceRequest,
        best: Option,
        now: datetime,
        note: str,
        also: list[Option] | None = None,
    ) -> None:
        """Offer an already-confirmed request to a new tech (new hold for the new shop),
        and to `also` (other shops offered at the same time)."""
        self._assign(request, best, now)
        shop = await self.s.get(Shop, request.shop_id)
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert shop and homeowner
        await self.payments.place_hold(request, homeowner, shop, request.estimate_low_cents or 0)
        request.offer_expires_at = self._offer_deadline(request, now)
        request.offer_round += 1
        self._record_offer(request, now)
        for option in also or []:
            self.s.add(
                JobOffer(
                    request_id=request.id,
                    shop_id=option.candidate.shop_id,
                    technician_id=option.candidate.technician_id,
                    arrival_at=option.arrival_at,
                    distance_km=round(option.distance_km, 1),
                    round=request.offer_round,
                    expires_at=request.offer_expires_at,
                )
            )
        if also:
            note = f"{note}; offered to {len(also) + 1} shops at once"
        transition(self.s, request, S.OFFERED, Actor.SYSTEM, note=note)
        await self.calendar.book(request)
        if not also:
            await self._maybe_instant_book(request, shop, now)

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
            await self.s.execute(
                update(JobOffer)
                .where(JobOffer.request_id == request.id, JobOffer.status == "open")
                .values(status="expired")
            )
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
