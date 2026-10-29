"""Job progress after dispatch: en route → on site → quote → approval → complete."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.domain.enums import Actor, RequestStatus
from app.domain.state_machine import HOMEOWNER_CANCELABLE
from app.models import Homeowner, ServiceRequest, Shop, Technician
from app.services.lifecycle import transition
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
            or request.shop_id != shop.id
            or request.status not in SHOP_VISIBLE_STATUSES
        ):
            raise NotFound("Job not found")
        return request

    async def list_for_shop(
        self, shop: Shop, statuses: list[str] | None = None
    ) -> list[ServiceRequest]:
        wanted = statuses or SHOP_VISIBLE_STATUSES
        rows = await self.s.scalars(
            select(ServiceRequest)
            .where(ServiceRequest.shop_id == shop.id, ServiceRequest.status.in_(wanted))
            .order_by(ServiceRequest.updated_at.desc())
            .limit(100)
        )
        return list(rows)

    async def mark_en_route(self, request: ServiceRequest) -> None:
        transition(self.s, request, S.EN_ROUTE, Actor.SHOP)
        await self._notify(request, "{tech} is on the way to your home.")

    async def mark_on_site(self, request: ServiceRequest) -> None:
        transition(self.s, request, S.ON_SITE, Actor.SHOP)

    async def submit_quote(
        self, request: ServiceRequest, *, final_price_cents: int, notes: str | None
    ) -> None:
        if not 0 < final_price_cents <= MAX_QUOTE_CENTS:
            raise AppError("Enter a valid price", code="invalid_price")
        request.final_price_cents = final_price_cents
        request.quote_notes = (notes or "").strip()[:1000] or None
        transition(self.s, request, S.QUOTED, Actor.SHOP)
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

    async def complete(self, request: ServiceRequest) -> None:
        if request.status != S.IN_PROGRESS.value:
            raise InvalidState("The homeowner hasn't approved the price yet")
        await self.payments.capture(request)
        request.completed_at = self.c.clock.now()
        transition(self.s, request, S.COMPLETED, Actor.SHOP)
        await self._notify(
            request,
            "Your HVAC job is complete. Your card was charged "
            f"${(request.captured_cents or 0) / 100:,.2f}. Thanks!",
        )

    async def rate(self, request: ServiceRequest, rating: int) -> None:
        if request.status != S.COMPLETED.value:
            raise InvalidState("You can rate a job once it's complete")
        if request.rating is not None:
            raise InvalidState("You already rated this job")
        if not 1 <= rating <= 5:
            raise AppError("Rating must be 1 to 5", code="invalid_rating")
        request.rating = rating
        tech = (
            await self.s.get(Technician, request.technician_id) if request.technician_id else None
        )
        if tech:
            tech.rating_sum += rating
            tech.rating_count += 1

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
