"""Stripe implementation: SetupIntents for cards, manual-capture PaymentIntents
for holds, and Connect Express accounts with destination charges for payouts."""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import Any, TypeVar, cast

import stripe

from app.core.errors import ExternalServiceError, PaymentRequired
from app.integrations.payments.base import (
    Authorization,
    PayoutAccountStatus,
    SavedPaymentMethod,
    SetupSession,
    WebhookEvent,
)

log = logging.getLogger(__name__)
T = TypeVar("T")


class StripePaymentGateway:
    def __init__(
        self,
        *,
        secret_key: str,
        publishable_key: str,
        webhook_secret: str | None,
        api_version: str,
        currency: str,
    ) -> None:
        self._client = stripe.StripeClient(secret_key)
        self._webhook_secret = webhook_secret
        self._api_version = api_version
        self._currency = currency
        self.publishable_key = publishable_key
        self.is_test_mode = secret_key.startswith("sk_test_")

    async def ensure_customer(
        self, *, existing_id: str | None, phone: str, name: str | None, reference: str
    ) -> str:
        if existing_id:
            return existing_id
        customer = await self._call(
            self._client.v1.customers.create_async(
                params={
                    "phone": phone,
                    "name": name or "",
                    "metadata": {"homeowner_id": reference},
                },
                options={"idempotency_key": f"customer-{reference}"},
            )
        )
        return customer.id

    async def create_setup_session(self, *, customer_id: str) -> SetupSession:
        intent = await self._call(
            self._client.v1.setup_intents.create_async(
                params={
                    "customer": customer_id,
                    "usage": "off_session",
                    "automatic_payment_methods": {"enabled": True},
                }
            )
        )
        key = await self._call(
            self._client.v1.ephemeral_keys.create_async(
                params={"customer": customer_id}, options={"stripe_version": self._api_version}
            )
        )
        return SetupSession(customer_id, intent.id, intent.client_secret or "", key.secret)

    async def get_saved_method(
        self, *, setup_intent_id: str, customer_id: str
    ) -> SavedPaymentMethod:
        intent = await self._call(
            self._client.v1.setup_intents.retrieve_async(
                setup_intent_id, params={"expand": ["payment_method"]}
            )
        )
        if intent.customer != customer_id:
            raise PaymentRequired("This card setup doesn't belong to your account")
        if intent.status != "succeeded" or intent.payment_method is None:
            raise PaymentRequired("Card setup isn't finished yet")
        pm = intent.payment_method
        if isinstance(pm, str):  # not expanded; fetch it
            pm = await self._call(self._client.v1.payment_methods.retrieve_async(pm))
        card = getattr(pm, "card", None)
        label = (
            f"{card.brand.title()} •• {card.last4}" if card else pm.type.replace("_", " ").title()
        )
        return SavedPaymentMethod(pm.id, label)

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
        try:
            intent = await self._client.v1.payment_intents.create_async(
                params={
                    "amount": amount_cents,
                    "currency": self._currency,
                    "customer": customer_id,
                    "payment_method": payment_method_id,
                    "off_session": True,
                    "confirm": True,
                    "capture_method": "manual",
                    "application_fee_amount": application_fee_cents,
                    "transfer_data": {"destination": destination_account_id},
                    "on_behalf_of": destination_account_id,
                    "description": description,
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.CardError as exc:
            raise PaymentRequired(exc.user_message or "Your card was declined") from exc
        except stripe.StripeError as exc:
            log.exception("Stripe authorize failed")
            raise ExternalServiceError("Payment service unavailable") from exc
        if intent.status != "requires_capture":
            raise PaymentRequired("Your bank needs you to confirm this payment in the app")
        return Authorization(intent.id, intent.amount)

    async def capture(
        self, *, intent_id: str, amount_cents: int, application_fee_cents: int
    ) -> None:
        await self._call(
            self._client.v1.payment_intents.capture_async(
                intent_id,
                params={
                    "amount_to_capture": amount_cents,
                    "application_fee_amount": application_fee_cents,
                },
                options={"idempotency_key": f"capture-{intent_id}-{amount_cents}"},
            )
        )

    async def cancel(self, *, intent_id: str) -> None:
        try:
            await self._client.v1.payment_intents.cancel_async(intent_id)
        except stripe.InvalidRequestError as exc:
            # Already canceled/captured: cancelling is idempotent from our point of view.
            log.info("Cancel of %s ignored: %s", intent_id, exc.user_message)

    async def create_payout_account(self, *, email: str, business_name: str, reference: str) -> str:
        account = await self._call(
            self._client.v1.accounts.create_async(
                params={
                    "type": "express",
                    "country": "US",
                    "email": email,
                    "business_type": "company",
                    "business_profile": {"name": business_name, "mcc": "1711"},  # HVAC
                    "capabilities": {
                        "card_payments": {"requested": True},
                        "transfers": {"requested": True},
                    },
                    "metadata": {"shop_id": reference},
                },
                options={"idempotency_key": f"account-{reference}"},
            )
        )
        return account.id

    async def payout_onboarding_link(
        self, *, account_id: str, return_url: str, refresh_url: str
    ) -> str:
        link = await self._call(
            self._client.v1.account_links.create_async(
                params={
                    "account": account_id,
                    "type": "account_onboarding",
                    "return_url": return_url,
                    "refresh_url": refresh_url,
                }
            )
        )
        return link.url

    async def payout_account_status(self, *, account_id: str) -> PayoutAccountStatus:
        account = await self._call(self._client.v1.accounts.retrieve_async(account_id))
        return PayoutAccountStatus(bool(account.payouts_enabled), bool(account.details_submitted))

    async def set_payout_schedule(self, *, account_id: str, interval: str) -> None:
        schedule: dict[str, str] = {"interval": interval}
        if interval == "weekly":
            schedule["weekly_anchor"] = "monday"
        await self._call(
            self._client.v1.accounts.update_async(
                account_id, params=cast(Any, {"settings": {"payouts": {"schedule": schedule}}})
            )
        )

    def parse_webhook(self, *, payload: bytes, signature: str | None) -> WebhookEvent:
        if not self._webhook_secret:
            raise PaymentRequired("Webhook secret not configured")
        try:
            event = self._client.construct_event(payload, signature, self._webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise PaymentRequired("Invalid webhook signature") from exc
        return WebhookEvent(event.id, event.type, event.data.object.to_dict())

    @staticmethod
    async def _call(awaitable: Awaitable[T]) -> T:
        try:
            return await awaitable
        except stripe.CardError as exc:
            raise PaymentRequired(exc.user_message or "Your card was declined") from exc
        except stripe.StripeError as exc:
            log.exception("Stripe call failed")
            raise ExternalServiceError("Payment service unavailable") from exc
