"""In-memory payment gateway. Behaves like Stripe's happy path for demos and tests.

Payout onboarding is simulated: the "onboarding link" points back to the API,
which marks the account complete and redirects to the shop portal.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field

from app.core.errors import NotFound, PaymentRequired
from app.integrations.payments.base import (
    Authorization,
    PayoutAccountStatus,
    SavedPaymentMethod,
    SetupSession,
    WebhookEvent,
)

DECLINE_LAST4 = "0002"  # mirrors Stripe's "card declined" test card


@dataclass
class _Intent:
    amount: int
    status: str  # requires_capture | succeeded | canceled
    captured: int = 0
    fee: int = 0


@dataclass
class FakePaymentGateway:
    api_base_url: str = "http://localhost:8000"
    publishable_key: str = ""
    is_test_mode: bool = True
    customers: dict[str, str] = field(default_factory=dict)
    setup_intents: dict[str, str] = field(default_factory=dict)  # seti -> customer
    card_last4: dict[str, str] = field(default_factory=dict)  # seti -> last4 (demo form)
    intents: dict[str, _Intent] = field(default_factory=dict)
    accounts: dict[str, PayoutAccountStatus] = field(default_factory=dict)
    payout_schedules: dict[str, str] = field(default_factory=dict)

    async def ensure_customer(
        self, *, existing_id: str | None, phone: str, name: str | None, reference: str
    ) -> str:
        if existing_id and existing_id in self.customers:
            return existing_id
        cid = f"cus_fake_{secrets.token_hex(6)}"
        self.customers[cid] = reference
        return cid

    async def create_setup_session(self, *, customer_id: str) -> SetupSession:
        seti = f"seti_fake_{secrets.token_hex(6)}"
        self.setup_intents[seti] = customer_id
        return SetupSession(customer_id, seti, f"{seti}_secret_fake", None)

    def record_demo_card(self, setup_intent_id: str, last4: str) -> None:
        """Called by the demo card form (fake mode only) to simulate entering a card."""
        if not setup_intent_id.startswith("seti_fake_"):
            raise NotFound("Unknown setup session")
        self.card_last4[setup_intent_id] = last4

    async def get_saved_method(
        self, *, setup_intent_id: str, customer_id: str
    ) -> SavedPaymentMethod:
        owner = self.setup_intents.get(setup_intent_id)
        # State is in memory; tolerate sessions created before a dev-server reload.
        if owner is None and not setup_intent_id.startswith("seti_fake_"):
            raise NotFound("Unknown setup session")
        if owner is not None and owner != customer_id:
            raise NotFound("Unknown setup session")
        last4 = self.card_last4.get(setup_intent_id, "4242")
        if last4 == DECLINE_LAST4:
            raise PaymentRequired("Your card was declined")
        return SavedPaymentMethod(f"pm_fake_{last4}_{secrets.token_hex(4)}", f"Visa •• {last4}")

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
    ) -> Authorization:
        if amount_cents <= 0:
            raise ValueError("amount must be positive")
        intent_id = f"pi_fake_{idempotency_key[-12:]}_{secrets.token_hex(3)}"
        self.intents[intent_id] = _Intent(
            amount_cents, "requires_capture", fee=application_fee_cents
        )
        return Authorization(intent_id, amount_cents)

    async def capture(
        self, *, intent_id: str, amount_cents: int, application_fee_cents: int
    ) -> None:
        # Holds created before a dev-server reload are treated as still open.
        intent = self.intents.setdefault(intent_id, _Intent(amount_cents, "requires_capture"))
        if intent.status != "requires_capture":
            raise PaymentRequired(f"Payment is {intent.status}, cannot capture")
        if amount_cents > intent.amount:
            raise PaymentRequired("Capture exceeds the authorized amount")
        intent.status, intent.captured, intent.fee = (
            "succeeded",
            amount_cents,
            application_fee_cents,
        )

    async def cancel(self, *, intent_id: str) -> None:
        intent = self.intents.get(intent_id)
        if intent and intent.status == "requires_capture":
            intent.status = "canceled"

    async def create_payout_account(self, *, email: str, business_name: str, reference: str) -> str:
        account_id = f"acct_fake_{secrets.token_hex(6)}"
        self.accounts[account_id] = PayoutAccountStatus(False, False)
        return account_id

    async def payout_onboarding_link(
        self, *, account_id: str, return_url: str, refresh_url: str
    ) -> str:
        return f"{self.api_base_url}/v1/dev/fake-payout-onboarding/{account_id}"

    def complete_onboarding(self, account_id: str) -> None:
        if not account_id.startswith("acct_fake_"):
            raise NotFound("Unknown payout account")
        self.accounts[account_id] = PayoutAccountStatus(True, True)

    async def payout_account_status(self, *, account_id: str) -> PayoutAccountStatus:
        # Accounts from before a dev-server reload are assumed onboarded (demo convenience).
        return self.accounts.get(account_id, PayoutAccountStatus(True, True))

    async def set_payout_schedule(self, *, account_id: str, interval: str) -> None:
        self.payout_schedules[account_id] = interval

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent:
        body = json.loads(payload)
        return WebhookEvent(body["id"], body["type"], body.get("data", {}).get("object", {}))
