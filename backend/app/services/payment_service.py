"""Money movement for a request: hold → (re-hold if the quote is higher) → capture."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import InvalidState, PaymentRequired
from app.domain.pricing import platform_fee
from app.models import Homeowner, ServiceRequest, Shop

log = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container
        self.gateway = container.payments
        self.fee_bps = container.settings.platform_fee_bps

    async def place_hold(
        self, request: ServiceRequest, homeowner: Homeowner, shop: Shop, amount_cents: int
    ) -> None:
        """Authorize (not charge) the card, routed to the shop's payout account."""
        if not homeowner.payment_customer_id or not homeowner.default_payment_method_id:
            raise PaymentRequired(
                "Add a payment method to book a technician", code="payment_method_required"
            )
        if not shop.payout_account_id:
            raise InvalidState("This shop can't accept payments yet")
        if request.payment_intent_id:
            await self.release_hold(request)
        auth = await self.gateway.authorize(
            amount_cents=amount_cents,
            customer_id=homeowner.payment_customer_id,
            payment_method_id=homeowner.default_payment_method_id,
            destination_account_id=shop.payout_account_id,
            application_fee_cents=platform_fee(amount_cents, self.fee_bps),
            idempotency_key=f"hold-{request.id}-{request.version}-{shop.id}-{amount_cents}",
            description=f"HVAC service request {str(request.id)[:8]}",
        )
        request.payment_intent_id = auth.intent_id
        request.authorized_cents = auth.amount_cents

    async def release_hold(self, request: ServiceRequest) -> None:
        if request.payment_intent_id and request.captured_cents is None:
            try:
                await self.gateway.cancel(intent_id=request.payment_intent_id)
            except Exception:
                # Uncaptured holds also expire on their own; don't block the workflow.
                log.exception("Failed to release hold %s", request.payment_intent_id)
        request.payment_intent_id = None
        request.authorized_cents = None

    async def ensure_hold_covers(
        self, request: ServiceRequest, homeowner: Homeowner, shop: Shop, amount_cents: int
    ) -> None:
        """Called when the homeowner approves a quote above the current hold."""
        if request.authorized_cents is not None and amount_cents <= request.authorized_cents:
            return
        await self.place_hold(request, homeowner, shop, amount_cents)

    async def capture(self, request: ServiceRequest) -> None:
        if request.final_price_cents is None or not request.payment_intent_id:
            raise InvalidState("Nothing to charge for this job")
        amount = request.final_price_cents
        fee = platform_fee(amount, self.fee_bps)
        await self.gateway.capture(
            intent_id=request.payment_intent_id, amount_cents=amount, application_fee_cents=fee
        )
        request.captured_cents = amount
        request.platform_fee_cents = fee
