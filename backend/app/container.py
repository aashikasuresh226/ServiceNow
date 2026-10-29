"""Composition root: builds every adapter from settings, in one place.

Services receive adapters through this container, so tests swap in fakes
without monkeypatching and production wiring is explicit.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.security import Encryptor, TokenService, UrlSigner
from app.integrations.ai.base import UnitAnalyzer
from app.integrations.ai.fake import FakeUnitAnalyzer
from app.integrations.geocoding import FakeGeocoder, Geocoder, MapboxGeocoder
from app.integrations.payments.base import PaymentGateway
from app.integrations.payments.fake import FakePaymentGateway
from app.integrations.scheduling.factory import SchedulingClientFactory, make_factory
from app.integrations.sms import ConsoleSmsSender, SmsSender, TwilioSmsSender
from app.integrations.storage import FileStorage, LocalFileStorage


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    http: httpx.AsyncClient
    clock: Clock
    tokens: TokenService
    encryptor: Encryptor
    url_signer: UrlSigner
    analyzer: UnitAnalyzer
    payments: PaymentGateway
    sms: SmsSender
    geocoder: Geocoder
    storage: FileStorage
    scheduling: SchedulingClientFactory

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if not getter:
        raise RuntimeError("A required secret is not configured")
    return str(getter())


def build_container(settings: Settings) -> Container:
    settings.validate_for_production()
    engine = create_engine(settings.database_url)
    http = httpx.AsyncClient(timeout=httpx.Timeout(20.0))

    analyzer: UnitAnalyzer
    if settings.ai_provider == "anthropic":
        from app.integrations.ai.anthropic_analyzer import AnthropicUnitAnalyzer

        analyzer = AnthropicUnitAnalyzer(
            _secret(settings.anthropic_api_key), settings.anthropic_model
        )
    else:
        analyzer = FakeUnitAnalyzer()

    payments: PaymentGateway
    if settings.payments_provider == "stripe":
        from app.integrations.payments.stripe_gateway import StripePaymentGateway

        payments = StripePaymentGateway(
            secret_key=_secret(settings.stripe_secret_key),
            publishable_key=settings.stripe_publishable_key,
            webhook_secret=settings.stripe_webhook_secret.get_secret_value()
            if settings.stripe_webhook_secret
            else None,
            api_version=settings.stripe_api_version,
            currency=settings.currency,
        )
    else:
        payments = FakePaymentGateway(api_base_url=settings.public_api_url)

    sms: SmsSender
    if settings.sms_provider == "twilio":
        sms = TwilioSmsSender(
            account_sid=settings.twilio_account_sid,
            auth_token=_secret(settings.twilio_auth_token),
            from_number=settings.twilio_from_number,
            http=http,
        )
    else:
        sms = ConsoleSmsSender()

    geocoder: Geocoder = (
        MapboxGeocoder(token=_secret(settings.mapbox_token), http=http)
        if settings.geocoding_provider == "mapbox"
        else FakeGeocoder()
    )

    return Container(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        http=http,
        clock=SystemClock(),
        tokens=TokenService(settings.jwt_secret.get_secret_value(), settings.jwt_issuer),
        encryptor=Encryptor(settings.encryption_key.get_secret_value()),
        url_signer=UrlSigner(settings.jwt_secret.get_secret_value()),
        analyzer=analyzer,
        payments=payments,
        sms=sms,
        geocoder=geocoder,
        storage=LocalFileStorage(settings.storage_dir),
        scheduling=make_factory(http),
    )
