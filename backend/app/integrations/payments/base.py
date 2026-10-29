"""Payment gateway interface (Stripe in production, an in-memory fake for demos/tests).

Flow, modeled on ride-hailing apps:
1. Homeowner saves a card (SetupIntent) during sign-up; nothing is charged.
2. Confirming a booking places a hold (manual-capture PaymentIntent) for the estimate,
   routed to the shop's connected account with the platform fee attached.
3. When the job is done, the approved final amount is captured.
4. Shops get paid out by Stripe on their chosen schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class SetupSession:
    customer_id: str
    setup_intent_id: str
    client_secret: str
    ephemeral_key_secret: str | None  # needed by the native mobile PaymentSheet


@dataclass(frozen=True, slots=True)
class SavedPaymentMethod:
    payment_method_id: str
    label: str  # e.g. "Visa •• 4242"


@dataclass(frozen=True, slots=True)
class Authorization:
    intent_id: str
    amount_cents: int


@dataclass(frozen=True, slots=True)
class PayoutAccountStatus:
    payouts_enabled: bool
    details_submitted: bool


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    id: str
    type: str
    data: dict[str, Any]


class PaymentGateway(Protocol):
    publishable_key: str
    is_test_mode: bool

    async def ensure_customer(
        self, *, existing_id: str | None, phone: str, name: str | None, reference: str
    ) -> str: ...

    async def create_setup_session(self, *, customer_id: str) -> SetupSession: ...

    async def get_saved_method(
        self, *, setup_intent_id: str, customer_id: str
    ) -> SavedPaymentMethod: ...

    async def authorize(
        self,
        *,
        amount_cents: int,
        customer_id: str,
        payment_method_id: str,
        destination_account_id: str,
        application_fee_cents: int,
        idempotency_key: str,
        description: str,
    ) -> Authorization: ...

    async def capture(
        self, *, intent_id: str, amount_cents: int, application_fee_cents: int
    ) -> None: ...

    async def cancel(self, *, intent_id: str) -> None: ...

    async def create_payout_account(
        self, *, email: str, business_name: str, reference: str
    ) -> str: ...

    async def payout_onboarding_link(
        self, *, account_id: str, return_url: str, refresh_url: str
    ) -> str: ...

    async def payout_account_status(self, *, account_id: str) -> PayoutAccountStatus: ...

    async def set_payout_schedule(self, *, account_id: str, interval: str) -> None: ...

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent: ...
