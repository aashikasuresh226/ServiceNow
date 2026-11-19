"""Application settings, loaded from environment variables (or a .env file).

Every external integration has a "fake" mode so the whole system runs locally
and in tests without third-party accounts. Production must set real providers;
`Settings.validate_for_production` enforces that at startup.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_log = logging.getLogger(__name__)


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="HVAC_", extra="ignore")

    environment: Environment = Environment.DEV
    api_prefix: str = "/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",  # shop portal (Vite)
            "http://localhost:8081",  # homeowner app (Expo web)
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8081",
        ]
    )
    public_api_url: str = "http://localhost:8000"

    # SQLite by default so the demo runs on any laptop with no database install.
    # Production uses Postgres: postgresql+asyncpg://user:pass@host:5432/hvac
    database_url: str = "sqlite+aiosqlite:///./var/hvac.db"
    # Run the background matching/waitlist/sync loop inside the API process (dev + demo).
    # In production run `python -m app.worker` as its own process instead.
    run_worker_in_process: bool = True

    # --- Security -------------------------------------------------------------
    jwt_secret: SecretStr = SecretStr("dev-only-change-me-dev-only-change-me")
    jwt_issuer: str = "hvac-connect"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    mfa_token_ttl_minutes: int = 5
    # Fernet key (urlsafe base64, 32 bytes) used to encrypt third-party credentials at rest.
    encryption_key: SecretStr = SecretStr("ZGV2LW9ubHkta2V5LWRldi1vbmx5LWtleS1kZXYtMDA=")

    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 30
    otp_max_per_hour: int = 5

    # --- Integrations ------------------------------------------------------------
    # Each one switches on when its keys are set. Without keys a feature is OFF
    # (never faked): photo analysis is skipped, payments aren't collected, etc.
    # "fake" providers exist only for the automated tests (HVAC_ENVIRONMENT=test).

    # Sign in with Google: OAuth client IDs from Google Cloud Console (comma-separated).
    # The first one is the Web client ID used by the homeowner app and shop portal.
    google_client_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # Claude reads the unit photo.
    # auto: Claude if an Anthropic key is set, else Gemini if a Gemini key is set, else off.
    ai_provider: str = "auto"  # auto | anthropic | gemini | off | fake (tests)
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_effort: str = "low"  # low | medium | high: how hard Claude thinks
    # Google Gemini (has a free tier: https://aistudio.google.com/apikey). Free-tier prompts
    # may be used by Google to improve its products; only photos + the description are sent.
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-flash-lite-latest"  # check AI Studio for free-tier models
    ai_max_concurrency: int = 8  # simultaneous Claude calls per API process
    ai_analyses_per_hour: int = 15  # per homeowner, caps cost from abuse

    # Stripe: cards for homeowners, Connect payouts for shops.
    payments_provider: str = "auto"  # auto | stripe | off | fake (tests)
    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str = ""
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_version: str = "2025-03-31.basil"
    platform_fee_bps: int = 1500  # 15.00% platform fee on each job
    currency: str = "usd"

    # Phone sign-in codes are sent and checked by Twilio Verify. Job updates are
    # texted with Twilio Messaging (needs a sending number or Messaging Service).
    # Without Twilio, in development only, codes are printed in the API window
    # and shown on screen so you can test.
    sms_provider: str = "auto"  # auto | twilio | console (dev only)
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr | None = None
    twilio_verify_service_sid: str = ""
    twilio_from_number: str = ""
    twilio_messaging_service_sid: str = ""
    # Only these country codes may request codes (blocks SMS-pumping fraud).
    sms_allowed_country_codes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["+1"]
    )

    # Address lookup. "census" is the free US Census Bureau geocoder (no key).
    geocoding_provider: str = "census"  # census | google | mapbox | fake (tests)
    google_maps_api_key: SecretStr | None = None
    mapbox_token: SecretStr | None = None

    # ServiceTitan / Housecall Pro sync. Off until API access is granted.
    scheduling_integrations_enabled: bool = False

    storage_dir: str = "./var/uploads"
    max_photo_bytes: int = 10 * 1024 * 1024
    max_photos_per_request: int = 5

    public_app_url: str = "http://localhost:8081"  # homeowner app, used in share links
    public_web_url: str = "http://localhost:5173"  # shop portal, used for Stripe return URLs

    # --- Matching / marketplace tuning -----------------------------------------
    proposal_ttl_seconds: int = 180  # homeowner has this long to confirm a proposed tech
    offer_ttl_seconds: int = 120  # shop has this long to accept a job offer
    match_horizon_days: int = 7  # how far ahead to look for a technician's next opening
    average_travel_speed_kmh: float = 40.0
    default_job_duration_minutes: int = 90
    scheduling_sync_interval_seconds: int = 300
    worker_tick_seconds: int = 5

    @field_validator("google_client_ids", "sms_allowed_country_codes", mode="before")
    @classmethod
    def _split_commas(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _ignore_old_demo_values(self) -> Settings:
        """Older .env files set the demo stand-ins ("fake"). Outside tests, treat them as
        "use the real service when its key is set" instead of refusing to start."""
        if self.environment != Environment.TEST:
            for name, real in (
                ("ai_provider", "auto"),
                ("payments_provider", "auto"),
                ("geocoding_provider", "census"),
            ):
                if getattr(self, name) == "fake":
                    _log.warning("Ignoring HVAC_%s=fake (test-only); using %s", name.upper(), real)
                    object.__setattr__(self, name, real)
        return self

    def validate_providers(self) -> None:
        """Test doubles are only allowed in tests; on-screen codes only outside prod."""
        problems: list[str] = []
        for name in ("ai_provider", "payments_provider", "geocoding_provider", "sms_provider"):
            if getattr(self, name) == "fake" and self.environment != Environment.TEST:
                problems.append(f"HVAC_{name.upper()}=fake is only for automated tests")
        if self.resolved_sms_provider == "console" and self.environment == Environment.PROD:
            problems.append("Twilio must be configured in prod")
        if self.ai_provider == "anthropic" and not self.anthropic_api_key:
            problems.append("HVAC_ANTHROPIC_API_KEY is required for HVAC_AI_PROVIDER=anthropic")
        if self.ai_provider == "gemini" and not self.gemini_api_key:
            problems.append("HVAC_GEMINI_API_KEY is required for HVAC_AI_PROVIDER=gemini")
        if self.payments_provider == "stripe" and not self.stripe_secret_key:
            problems.append("HVAC_STRIPE_SECRET_KEY is required for HVAC_PAYMENTS_PROVIDER=stripe")
        stripe_on = self.payments_enabled and self.payments_provider != "fake"
        if stripe_on and not self.stripe_publishable_key:
            problems.append("HVAC_STRIPE_PUBLISHABLE_KEY must be set with the secret key")
        if self.geocoding_provider == "google" and not self.google_maps_api_key:
            problems.append("HVAC_GOOGLE_MAPS_API_KEY is required for google geocoding")
        if self.geocoding_provider == "mapbox" and not self.mapbox_token:
            problems.append("HVAC_MAPBOX_TOKEN is required for mapbox geocoding")
        if problems:
            raise RuntimeError("Invalid configuration: " + "; ".join(problems))

    def validate_for_production(self) -> None:
        if self.environment != Environment.PROD:
            return
        problems: list[str] = []
        if "dev-only" in self.jwt_secret.get_secret_value():
            problems.append("HVAC_JWT_SECRET must be set")
        if self.encryption_key.get_secret_value().startswith("ZGV2LW9ubHk"):
            problems.append("HVAC_ENCRYPTION_KEY must be set")
        for name in ("ai_provider", "payments_provider", "sms_provider", "geocoding_provider"):
            if getattr(self, name) in ("fake", "console"):
                problems.append(f"HVAC_{name.upper()} can't be '{getattr(self, name)}' in prod")
        if self.sms_twilio_ready is False:
            problems.append("Twilio (HVAC_TWILIO_*) must be configured in prod")
        if self.payments_enabled and not self.stripe_webhook_secret:
            problems.append("HVAC_STRIPE_WEBHOOK_SECRET must be set")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))

    # --- Resolved feature switches ---------------------------------------------------
    @property
    def ai_enabled(self) -> bool:
        return self.resolved_ai_provider != "off"

    @property
    def resolved_ai_provider(self) -> str:
        if self.ai_provider == "auto":
            if self.anthropic_api_key is not None:
                return "anthropic"
            return "gemini" if self.gemini_api_key is not None else "off"
        return self.ai_provider

    @property
    def ai_model(self) -> str:
        return self.gemini_model if self.resolved_ai_provider == "gemini" else self.anthropic_model

    @property
    def payments_enabled(self) -> bool:
        if self.payments_provider == "auto":
            return self.stripe_secret_key is not None
        return self.payments_provider in ("stripe", "fake")

    @property
    def sms_twilio_ready(self) -> bool:
        return bool(
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_verify_service_sid
        )

    @property
    def resolved_sms_provider(self) -> str:
        if self.sms_provider == "auto":
            return "twilio" if self.sms_twilio_ready else "console"
        return self.sms_provider

    @property
    def google_web_client_id(self) -> str | None:
        return self.google_client_ids[0] if self.google_client_ids else None


@lru_cache
def get_settings() -> Settings:
    return Settings()
