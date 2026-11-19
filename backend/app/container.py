"""Composition root: builds every adapter from settings, in one place.

A feature whose keys aren't configured is None (switched off), never faked.
Test doubles are only wired in when HVAC_ENVIRONMENT=test (see Settings.validate_providers).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.core.ratelimit import RateLimiter
from app.core.security import Encryptor, TokenService, UrlSigner
from app.integrations.ai.base import UnitAnalyzer
from app.integrations.geocoding import (
    CensusGeocoder,
    FakeGeocoder,
    Geocoder,
    GoogleGeocoder,
    MapboxGeocoder,
)
from app.integrations.google_auth import GoogleTokenVerifier
from app.integrations.payments.base import PaymentGateway
from app.integrations.scheduling.factory import SchedulingClientFactory, make_factory
from app.integrations.sms import ConsoleSmsSender, SmsSender, TwilioSmsSender, TwilioVerifyClient
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
    rate_limiter: RateLimiter
    geocoder: Geocoder
    storage: FileStorage
    scheduling: SchedulingClientFactory
    # Optional features: None when not configured.
    analyzer: UnitAnalyzer | None
    payments: PaymentGateway | None
    phone_verify: TwilioVerifyClient | None  # None: codes are generated locally (dev only)
    sms: SmsSender | None  # job-update texts
    google: GoogleTokenVerifier | None

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.engine.dispose()


def _secret(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if not getter:
        raise RuntimeError("A required secret is not configured")
    return str(getter())


def _build_analyzer(settings: Settings) -> UnitAnalyzer | None:
    if not settings.ai_enabled:
        return None
    if settings.ai_provider == "fake":
        from app.integrations.ai.fake import FakeUnitAnalyzer

        return FakeUnitAnalyzer()
    if settings.resolved_ai_provider == "gemini":
        from app.integrations.ai.gemini_analyzer import GeminiUnitAnalyzer

        return GeminiUnitAnalyzer(
            _secret(settings.gemini_api_key),
            settings.gemini_model,
            max_concurrency=settings.ai_max_concurrency,
        )
    from app.integrations.ai.anthropic_analyzer import AnthropicUnitAnalyzer

    return AnthropicUnitAnalyzer(
        _secret(settings.anthropic_api_key),
        settings.anthropic_model,
        effort=settings.anthropic_effort,
        max_concurrency=settings.ai_max_concurrency,
    )


def _build_payments(settings: Settings) -> PaymentGateway | None:
    if not settings.payments_enabled:
        return None
    if settings.payments_provider == "fake":
        from app.integrations.payments.fake import FakePaymentGateway

        return FakePaymentGateway(api_base_url=settings.public_api_url)
    from app.integrations.payments.stripe_gateway import StripePaymentGateway

    return StripePaymentGateway(
        secret_key=_secret(settings.stripe_secret_key),
        publishable_key=settings.stripe_publishable_key,
        webhook_secret=settings.stripe_webhook_secret.get_secret_value()
        if settings.stripe_webhook_secret
        else None,
        api_version=settings.stripe_api_version,
        currency=settings.currency,
    )


def _build_geocoder(settings: Settings, http: httpx.AsyncClient) -> Geocoder:
    provider = settings.geocoding_provider
    if provider == "fake":
        return FakeGeocoder()
    if provider == "google":
        return GoogleGeocoder(api_key=_secret(settings.google_maps_api_key), http=http)
    if provider == "mapbox":
        return MapboxGeocoder(token=_secret(settings.mapbox_token), http=http)
    return CensusGeocoder(http=http)


def build_container(settings: Settings) -> Container:
    settings.validate_providers()
    settings.validate_for_production()
    engine = create_engine(settings.database_url)
    http = httpx.AsyncClient(timeout=httpx.Timeout(20.0))

    phone_verify: TwilioVerifyClient | None = None
    sms: SmsSender | None = None
    if settings.resolved_sms_provider == "twilio":
        token = _secret(settings.twilio_auth_token)
        phone_verify = TwilioVerifyClient(
            account_sid=settings.twilio_account_sid,
            auth_token=token,
            service_sid=settings.twilio_verify_service_sid,
            http=http,
        )
        if settings.twilio_from_number or settings.twilio_messaging_service_sid:
            sms = TwilioSmsSender(
                account_sid=settings.twilio_account_sid,
                auth_token=token,
                from_number=settings.twilio_from_number,
                messaging_service_sid=settings.twilio_messaging_service_sid,
                http=http,
            )
    else:
        sms = ConsoleSmsSender()

    google = (
        GoogleTokenVerifier(client_ids=settings.google_client_ids, http=http)
        if settings.google_client_ids
        else None
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
        rate_limiter=RateLimiter(),
        geocoder=_build_geocoder(settings, http),
        storage=LocalFileStorage(settings.storage_dir),
        scheduling=make_factory(http),
        analyzer=_build_analyzer(settings),
        payments=_build_payments(settings),
        phone_verify=phone_verify,
        sms=sms,
        google=google,
    )
