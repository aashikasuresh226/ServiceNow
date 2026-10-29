"""Application settings, loaded from environment variables (or a .env file).

Every external integration has a "fake" mode so the whole system runs locally
and in tests without third-party accounts. Production must set real providers;
`Settings.validate_for_production` enforces that at startup.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # --- Integrations (each "fake" or a real provider) -------------------------
    ai_provider: str = "fake"  # fake | anthropic
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-5-5"

    payments_provider: str = "fake"  # fake | stripe
    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str = ""
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_version: str = "2025-03-31.basil"
    platform_fee_bps: int = 1500  # 15.00% platform fee on each job
    currency: str = "usd"

    sms_provider: str = "console"  # console | twilio
    twilio_account_sid: str = ""
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str = ""

    geocoding_provider: str = "fake"  # fake | mapbox
    mapbox_token: SecretStr | None = None

    storage_dir: str = "./var/uploads"
    max_photo_bytes: int = 10 * 1024 * 1024
    max_photos_per_request: int = 5

    public_web_url: str = "http://localhost:5173"  # shop portal, used for Stripe return URLs

    # --- Matching / marketplace tuning -----------------------------------------
    proposal_ttl_seconds: int = 180  # homeowner has this long to confirm a proposed tech
    offer_ttl_seconds: int = 120  # shop has this long to accept a job offer
    skill_preference_max_extra_km: float = 10.0
    average_travel_speed_kmh: float = 40.0
    default_job_duration_minutes: int = 90
    scheduling_sync_interval_seconds: int = 300
    worker_tick_seconds: int = 5

    def validate_for_production(self) -> None:
        if self.environment != Environment.PROD:
            return
        problems: list[str] = []
        if "dev-only" in self.jwt_secret.get_secret_value():
            problems.append("HVAC_JWT_SECRET must be set")
        if self.encryption_key.get_secret_value().startswith("ZGV2LW9ubHk"):
            problems.append("HVAC_ENCRYPTION_KEY must be set")
        for name in ("ai_provider", "payments_provider", "geocoding_provider"):
            if getattr(self, name) == "fake":
                problems.append(f"HVAC_{name.upper()} must not be 'fake' in prod")
        if self.sms_provider == "console":
            problems.append("HVAC_SMS_PROVIDER must not be 'console' in prod")
        if self.payments_provider == "stripe" and not self.stripe_webhook_secret:
            problems.append("HVAC_STRIPE_WEBHOOK_SECRET must be set")
        if problems:
            raise RuntimeError("Invalid production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()
