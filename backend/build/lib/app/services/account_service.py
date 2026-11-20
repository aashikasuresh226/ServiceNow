"""Homeowner profile + saved payment method."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState
from app.integrations.payments.base import PaymentGateway, SetupSession
from app.models import Homeowner


class AccountService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def update_profile(
        self,
        homeowner: Homeowner,
        *,
        name: str | None,
        address: str | None,
        sms_opt_in: bool | None,
    ) -> Homeowner:
        if name is not None:
            homeowner.name = name.strip()[:120] or None
        if address is not None and address.strip() != (homeowner.address or ""):
            geo = await self.c.geocoder.geocode(address)
            homeowner.address = geo.formatted_address
            homeowner.lat, homeowner.lng = geo.location.lat, geo.location.lng
        if sms_opt_in is not None:
            homeowner.sms_opt_in = sms_opt_in
        return homeowner

    def _gateway(self) -> PaymentGateway:
        if self.c.payments is None:
            raise AppError("Payments aren't set up yet", code="payments_not_configured")
        return self.c.payments

    async def start_card_setup(self, homeowner: Homeowner) -> SetupSession:
        gateway = self._gateway()
        homeowner.payment_customer_id = await gateway.ensure_customer(
            existing_id=homeowner.payment_customer_id,
            phone=homeowner.phone or "",
            email=homeowner.email,
            name=homeowner.name,
            reference=str(homeowner.id),
        )
        return await gateway.create_setup_session(customer_id=homeowner.payment_customer_id)

    async def finish_card_setup(self, homeowner: Homeowner, setup_intent_id: str) -> Homeowner:
        if not homeowner.payment_customer_id:
            raise InvalidState("Start adding a card first")
        saved = await self._gateway().get_saved_method(
            setup_intent_id=setup_intent_id, customer_id=homeowner.payment_customer_id
        )
        homeowner.default_payment_method_id = saved.payment_method_id
        homeowner.payment_method_label = saved.label
        return homeowner
