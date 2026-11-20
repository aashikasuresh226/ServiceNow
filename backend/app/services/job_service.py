"""Job progress after dispatch: en route → on site → quote → approval → complete."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.domain.enums import Actor, RequestStatus
from app.domain.state_machine import HOMEOWNER_CANCELABLE
from app.models import Homeowner, JobOffer, ServiceRequest, Shop, Technician
from app.services.calendar_service import CalendarService
from app.services.hcp_mirror import HcpMirror
from app.services.lifecycle import clear_live_location, transition
from app.services.matching_service import MatchingService
from app.services.notifications import notify_homeowner
from app.services.payment_service import PaymentService

S = RequestStatus
MAX_QUOTE_CENTS = 50_000_00
SHOP_VISIBLE_STATUSES = [
    s.value
    for s in (S.OFFERED, S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS, S.COMPLETED)
]


class JobService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container
        self.payments = PaymentService(session, container)

    async def get_for_shop(self, request_id: uuid.UUID, shop: Shop) -> ServiceRequest:
        request = await self.s.get(ServiceRequest, request_id)
        if (
            request is None
            or request.status not in SHOP_VISIBLE_STATUSES
            or (request.shop_id != shop.id and request.id not in await self._open_offer_ids(shop))
        ):
            raise NotFound("Job not found")
        return request

    async def list_for_shop(
        self, shop: Shop, statuses: list[str] | None = None
    ) -> list[ServiceRequest]:
        wanted = statuses or SHOP_VISIBLE_STATUSES
        offered = await self._open_offer_ids(shop)
        rows = await self.s.scalars(
            select(ServiceRequest)
            .where(
                or_(
                    ServiceRequest.shop_id == shop.id,
                    and_(
                        ServiceRequest.id.in_(offered),
                        ServiceRequest.status == S.OFFERED.value,
                    ),
                ),
                ServiceRequest.status.in_(wanted),
            )
            .order_by(ServiceRequest.updated_at.desc())
            .limit(100)
        )
        return list(rows)

    async def _open_offer_ids(self, shop: Shop) -> set[uuid.UUID]:
        """Requests also offered to this shop (several shops offered at once)."""
        rows = await self.s.scalars(
            select(JobOffer.request_id).where(
                JobOffer.shop_id == shop.id, JobOffer.status == "open"
            )
        )
        return set(rows)

    async def open_offer(self, request: ServiceRequest, shop: Shop) -> JobOffer | None:
        return await self.s.scalar(
            select(JobOffer).where(
                JobOffer.request_id == request.id,
                JobOffer.shop_id == shop.id,
                JobOffer.status == "open",
            )
        )

    async def mark_en_route(self, request: ServiceRequest, actor: Actor = Actor.SHOP) -> None:
        transition(self.s, request, S.EN_ROUTE, actor)
        await self._notify(request, "{tech} is on the way to your home.")
        await HcpMirror(self.s, self.c).record(request, "en_route")

    async def mark_on_site(self, request: ServiceRequest, actor: Actor = Actor.SHOP) -> None:
        transition(self.s, request, S.ON_SITE, actor)
        await clear_live_location(self.s, request)  # sharing ends on arrival
        await HcpMirror(self.s, self.c).record(request, "on_site")

    async def submit_quote(
        self,
        request: ServiceRequest,
        *,
        final_price_cents: int,
        notes: str | None,
        actor: Actor = Actor.SHOP,
    ) -> None:
        if not 0 < final_price_cents <= MAX_QUOTE_CENTS:
            raise AppError("Enter a valid price", code="invalid_price")
        request.final_price_cents = final_price_cents
        request.quote_notes = (notes or "").strip()[:1000] or None
        transition(self.s, request, S.QUOTED, actor)
        await self._notify(
            request,
            "Your technician sent the final price "
            f"(${final_price_cents / 100:,.2f}). Open the app to approve it.",
        )

    async def approve_quote(self, request: ServiceRequest, homeowner: Homeowner) -> None:
        if request.status != S.QUOTED.value or request.final_price_cents is None:
            raise InvalidState("There's no price waiting for your approval")
        shop = await self.s.get(Shop, request.shop_id)
        assert shop
        await self.payments.ensure_hold_covers(request, homeowner, shop, request.final_price_cents)
        transition(self.s, request, S.IN_PROGRESS, Actor.HOMEOWNER)
        await HcpMirror(self.s, self.c).record(
            request,
            "quote_approved",
            price_cents=request.final_price_cents,
            notes=request.quote_notes,
            item=(request.diagnosis or {}).get("primary_issue_label"),
        )

    async def complete(self, request: ServiceRequest, actor: Actor = Actor.SHOP) -> None:
        if request.status != S.IN_PROGRESS.value:
            raise InvalidState("The homeowner hasn't approved the price yet")
        await self.payments.capture(request)
        request.completed_at = self.c.clock.now()
        transition(self.s, request, S.COMPLETED, actor)
        await CalendarService(self.s, self.c).finish(request)
        await HcpMirror(self.s, self.c).record(
            request, "completed", charged_cents=request.captured_cents
        )
        if request.captured_cents is not None:
            message = (
                "Your HVAC job is complete. Your card was charged "
                f"${request.captured_cents / 100:,.2f}. Thanks!"
            )
        else:
            message = "Your HVAC job is complete. Thanks for using HVAC Connect!"
        await self._notify(request, message)

    async def rate(
        self,
        request: ServiceRequest,
        *,
        technician_rating: int | None,
        shop_rating: int | None,
        review: str | None = None,
    ) -> None:
        """Homeowner rates the technician and the company (1-5 each), once per job."""
        if request.status != S.COMPLETED.value:
            raise InvalidState("You can rate a job once it's complete")
        if technician_rating is None and shop_rating is None:
            raise AppError("Choose a rating", code="invalid_rating")
        for value in (technician_rating, shop_rating):
            if value is not None and not 1 <= value <= 5:
                raise AppError("Ratings must be 1 to 5", code="invalid_rating")
        if technician_rating is not None:
            if request.rating is not None:
                raise InvalidState("You already rated this technician")
            request.rating = technician_rating
            tech = (
                await self.s.get(Technician, request.technician_id)
                if request.technician_id
                else None
            )
            if tech:
                tech.rating_sum += technician_rating
                tech.rating_count += 1
        if shop_rating is not None:
            if request.shop_rating is not None:
                raise InvalidState("You already rated this company")
            request.shop_rating = shop_rating
            shop = await self.s.get(Shop, request.shop_id) if request.shop_id else None
            if shop:
                shop.rating_sum += shop_rating
                shop.rating_count += 1
        if review and review.strip():
            request.review = review.strip()[:500]

    async def homeowner_cancel(self, request: ServiceRequest) -> None:
        if RequestStatus(request.status) not in HOMEOWNER_CANCELABLE:
            raise InvalidState("Please contact support to cancel at this stage")
        await MatchingService(self.s, self.c).cancel(
            request, Actor.HOMEOWNER, "Canceled by homeowner"
        )

    async def _notify(self, request: ServiceRequest, template: str) -> None:
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        tech = (
            await self.s.get(Technician, request.technician_id) if request.technician_id else None
        )
        if homeowner:
            await notify_homeowner(
                self.c, homeowner, template.format(tech=tech.name if tech else "Your technician")
            )
