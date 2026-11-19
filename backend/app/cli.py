"""Operational commands.

python -m app.cli secrets     create HVAC_JWT_SECRET + HVAC_ENCRYPTION_KEY in .env if missing
python -m app.cli migrate     apply database migrations (safe to run any time)
python -m app.cli reset-db    delete ALL data and start with an empty database (not in prod)
python -m app.cli check       show which integrations are switched on
python -m app.cli test-ai [photo.jpg]
                              send a photo (or a blank test image) to Claude and print
                              what it reads, to confirm your Anthropic key works

There is no demo data: create real accounts in the apps (a shop in the portal,
homeowners in the homeowner app).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, MetaData

from app.core.config import Environment, Settings, get_settings


def _run_alembic(*args: str) -> None:
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, check=True)


async def _drop_everything(url: str) -> None:
    from app.core.db import create_engine

    engine = create_engine(url)
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


ENV_FILE = Path(".env")


def ensure_secrets() -> None:
    """Give this install its own random secrets (the built-in ones are public, dev-only).

    Never replaces a key that's already set: HVAC_ENCRYPTION_KEY decrypts the customer
    data in the database, so losing or changing it makes that data unreadable."""
    import secrets as pysecrets

    from cryptography.fernet import Fernet

    text = ENV_FILE.read_text(encoding="utf-8-sig") if ENV_FILE.exists() else ""
    present = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }
    added = []
    if "HVAC_JWT_SECRET" not in present:
        added.append(f"HVAC_JWT_SECRET={pysecrets.token_urlsafe(48)}")
    if "HVAC_ENCRYPTION_KEY" not in present:
        if _database_has_rows():
            print(
                "Keeping the built-in development encryption key: the database already has "
                "data encrypted with it. (Run reset-db first to switch to a private key.)"
            )
        else:
            added.append(f"HVAC_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
    if added:
        block = "\n# Generated for this computer. Keep private; don't change once data exists.\n"
        newline = "" if not text or text.endswith("\n") else "\n"
        ENV_FILE.write_text(text + newline + block + "\n".join(added) + "\n", encoding="utf-8")
        print(f"Created {', '.join(a.split('=')[0] for a in added)} in backend/.env")
    else:
        print("Secrets are set.")


def _database_has_rows() -> bool:
    settings = get_settings()

    async def probe() -> bool:
        from sqlalchemy import text

        from app.core.db import create_engine

        engine = create_engine(settings.database_url)
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT COUNT(*) FROM homeowners"))
                return bool(result.scalar())
        except Exception:
            return False
        finally:
            await engine.dispose()

    return asyncio.run(probe())


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
    line(
        "Photo analysis",
        settings.ai_enabled,
        f"{settings.resolved_ai_provider} ({settings.ai_model})"
        if settings.ai_enabled
        else "HVAC_GEMINI_API_KEY (free) or HVAC_ANTHROPIC_API_KEY",
    )
    line(
        "Email links (Firebase)",
        settings.firebase_enabled,
        f"project {settings.firebase_project_id}"
        if settings.firebase_enabled
        else "dev mode: links shown on screen (set HVAC_FIREBASE_*)",
    )
    line("Payments (Stripe)", settings.payments_enabled, "HVAC_STRIPE_SECRET_KEY + publishable key")
    line("Address lookup", True, settings.geocoding_provider)
    line(
        "ServiceTitan / Housecall Pro",
        settings.scheduling_integrations_enabled,
        "coming soon",
    )
    db = settings.database_url
    host = db.split("@", 1)[1].split("/", 1)[0] if "@" in db else "this computer"
    print(
        f"Database: {'Postgres at ' + host if db.startswith('postgres') else 'SQLite (local file)'}"
    )
    private_key = not settings.encryption_key.get_secret_value().startswith("ZGV2LW9ubHk")
    print(
        "Customer data encryption: "
        + ("ON, private key" if private_key else "ON, but with the public development key")
    )


async def _test_ai(settings: Settings, photo: str | None) -> None:
    from dataclasses import asdict

    from app.container import _build_analyzer
    from app.core.errors import AppError
    from app.integrations.ai.base import PhotoInput

    analyzer = _build_analyzer(settings)
    if analyzer is None:
        raise SystemExit(
            "Photo analysis is OFF: set HVAC_GEMINI_API_KEY (free) or HVAC_ANTHROPIC_API_KEY "
            "in backend/.env"
        )
    if photo:
        data = await asyncio.to_thread(Path(photo).read_bytes)
    else:
        import io

        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(buffer, format="JPEG")
        data = buffer.getvalue()
    what = "your photo" if photo else "a blank test image"
    print(f"Sending {what} to {settings.resolved_ai_provider} ({settings.ai_model})...")
    try:
        result = await analyzer.analyze(
            symptoms=["no_cooling"],
            description="Test from the command line",
            photos=[PhotoInput(data, "image/jpeg")],
            current_year=datetime.now().year,
        )
    except AppError as exc:
        raise SystemExit(f"FAILED: {exc.message}. See the log lines above for details.") from exc
    unit = asdict(result.unit)
    print("OK, the AI answered. Unit:")
    for key, value in unit.items():
        if value not in (None, [], {}):
            print(f"  {key}: {value}")
    dx = result.diagnosis
    print(f"Likely issue: {dx.primary_issue.value} ({dx.confidence.value})")
    print(f"Summary: {result.diagnosis.summary}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["secrets", "migrate", "reset-db", "check", "test-ai"])
    parser.add_argument("photo", nargs="?", help="photo for test-ai")
    args = parser.parse_args()
    Path("var").mkdir(exist_ok=True)
    settings = get_settings()
    if args.command == "secrets":
        ensure_secrets()
    elif args.command == "migrate":
        _run_alembic("upgrade", "head")
    elif args.command == "reset-db":
        reset_db(settings)
    elif args.command == "test-ai":
        logging.getLogger().setLevel(logging.INFO)
        asyncio.run(_test_ai(settings, args.photo))
    else:
        check(settings)


if __name__ == "__main__":
    main()
