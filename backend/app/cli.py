"""Operational commands.

python -m app.cli migrate     apply database migrations (safe to run any time)
python -m app.cli reset-db    delete ALL data and start with an empty database (not in prod)
python -m app.cli check       show which integrations are switched on

There is no demo data: create real accounts in the apps (a shop in the portal,
homeowners in the homeowner app).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from sqlalchemy import Connection, MetaData
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Environment, Settings, get_settings


def _run_alembic(*args: str) -> None:
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, check=True)


async def _drop_everything(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:

            def drop(sync_conn: Connection) -> None:
                metadata = MetaData()
                metadata.reflect(bind=sync_conn)
                metadata.drop_all(bind=sync_conn)

            await conn.run_sync(drop)
    finally:
        await engine.dispose()


def reset_db(settings: Settings) -> None:
    if settings.environment == Environment.PROD:
        raise SystemExit("Refusing to reset a production database.")
    asyncio.run(_drop_everything(settings.database_url))
    _run_alembic("upgrade", "head")
    print("Database is empty and up to date.")


def check(settings: Settings) -> None:
    settings.validate_providers()

    def line(name: str, on: bool, detail: str) -> None:
        print(f"  {'ON ' if on else 'OFF'}  {name:<26} {detail}")

    print("Integrations:")
    line(
        "Sign in with Google",
        bool(settings.google_client_ids),
        "HVAC_GOOGLE_CLIENT_IDS" if not settings.google_client_ids else "",
    )
    twilio = settings.resolved_sms_provider == "twilio"
    line(
        "Texted sign-in codes",
        twilio,
        "Twilio Verify" if twilio else "dev mode: codes shown on screen (set HVAC_TWILIO_*)",
    )
    line(
        "Job update texts",
        twilio and bool(settings.twilio_from_number or settings.twilio_messaging_service_sid),
        "needs HVAC_TWILIO_FROM_NUMBER or HVAC_TWILIO_MESSAGING_SERVICE_SID",
    )
    line("Photo analysis (Claude)", settings.ai_enabled, "HVAC_ANTHROPIC_API_KEY")
    line("Payments (Stripe)", settings.payments_enabled, "HVAC_STRIPE_SECRET_KEY + publishable key")
    line("Address lookup", True, settings.geocoding_provider)
    line(
        "ServiceTitan / Housecall Pro",
        settings.scheduling_integrations_enabled,
        "coming soon",
    )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["migrate", "reset-db", "check"])
    args = parser.parse_args()
    Path("var").mkdir(exist_ok=True)
    settings = get_settings()
    if args.command == "migrate":
        _run_alembic("upgrade", "head")
    elif args.command == "reset-db":
        reset_db(settings)
    else:
        check(settings)


if __name__ == "__main__":
    main()
