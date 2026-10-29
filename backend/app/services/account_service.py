"""Homeowner profile + saved payment method."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import InvalidState
from app.integrations.payments.base import SetupSession
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
        lat: float | None,
        lng: float | None,
        sms_opt_in: bool | None,
    ) -> Homeowner:
        if name is not None:
            homeowner.name = name.strip()[:120] or None
        if address is not None:
            if lat is not None and lng is not None:
                homeowner.address, homeowner.lat, homeowner.lng = address.strip(), lat, lng
            else:
                geo = await self.c.geocoder.geocode(address)
                homeowner.address = geo.formatted_address
                homeowner.lat, homeowner.lng = geo.location.lat, geo.location.lng
        if sms_opt_in is not None:
            homeowner.sms_opt_in = sms_opt_in
        return homeowner

    async def start_card_setup(self, homeowner: Homeowner) -> SetupSession:
        homeowner.payment_customer_id = await self.c.payments.ensure_customer(
            existing_id=homeowner.payment_customer_id,
            phone=homeowner.phone,
            name=homeowner.name,
            reference=str(homeowner.id),
        )
        return await self.c.payments.create_setup_session(customer_id=homeowner.payment_customer_id)

    async def finish_card_setup(self, homeowner: Homeowner, setup_intent_id: str) -> Homeowner:
        if not homeowner.payment_customer_id:
            raise InvalidState("Start adding a card first")
        saved = await self.c.payments.get_saved_method(
            setup_intent_id=setup_intent_id, customer_id=homeowner.payment_customer_id
        )
        homeowner.default_payment_method_id = saved.payment_method_id
        homeowner.payment_method_label = saved.label
        return homeowner
