"""Test fixtures: a real app + SQLite database, with test doubles for outside services."""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pyotp
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.container import Container, build_container
from app.core.clock import FrozenClock
from app.core.config import Environment, Settings
from app.core.db import Base
from app.core.security import hash_password
from app.domain.geo import LatLng
from app.integrations.geocoding import GeocodeResult
from app.integrations.sms import ConsoleSmsSender
from app.main import create_app
from app.models import Shop, ShopUser, Technician

ALL_DAY = {d: [["00:00", "24:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
HOME = (33.7490, -84.3880)
SHOP_PASSWORD = "CorrectHorseBattery1"


def png_bytes() -> bytes:
    """A valid 1x1 PNG."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class PinnedGeocoder:
    """Every address resolves to HOME unless it starts with "@lat,lng " (keeps tests exact)."""

    async def geocode(self, address: str) -> GeocodeResult:
        if address.startswith("@"):
            coords, _, rest = address[1:].partition(" ")
            lat, lng = (float(v) for v in coords.split(","))
            return GeocodeResult(LatLng(lat, lng), rest or address)
        return GeocodeResult(LatLng(*HOME), address.strip())


# The test clock and authenticator secrets for this test, so helpers can make codes.
STATE: dict[str, Any] = {"clock": None, "secrets": {}}


@pytest.fixture
def clock() -> FrozenClock:
    frozen = FrozenClock(datetime(2026, 7, 15, 16, 0, tzinfo=UTC))
    STATE["clock"] = frozen
    STATE["secrets"] = {}
    return frozen


def totp_code(secret: str) -> str:
    return pyotp.TOTP(secret).at(STATE["clock"].now())


ADMIN_KEY = "test-admin-key-0123456789"


@pytest.fixture
async def container(tmp_path: Path, clock: FrozenClock) -> AsyncIterator[Container]:
    settings = Settings(
        environment=Environment.TEST,
        ai_provider="fake",
        payments_provider="fake",
        geocoding_provider="fake",
        sms_provider="console",  # codes come back as dev_code so tests can sign in
        # Set HVAC_TEST_DATABASE_URL to run the suite against Postgres (as CI should).
        database_url=os.environ.get(
            "HVAC_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        ),
        storage_dir=str(tmp_path / "uploads"),
        run_worker_in_process=False,
        admin_token=SecretStr(ADMIN_KEY),
    )
    built = build_container(settings)
    built = replace(built, clock=clock, sms=ConsoleSmsSender(), geocoder=PinnedGeocoder())
    async with built.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield built
    await built.aclose()


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(container.settings, container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test/v1") as http:
        yield http


@dataclass
class SeededShop:
    shop_id: object
    email: str
    totp_secret: str
    tech_ids: list[object]


async def make_shop(
    container: Container,
    *,
    name: str,
    email: str,
    offset: tuple[float, float],
    techs: list[dict[str, object]],
) -> SeededShop:
    secret = pyotp.random_base32()
    async with container.session_factory() as s:
        shop = Shop(
            name=name,
            lat=HOME[0] + offset[0],
            lng=HOME[1] + offset[1],
            is_live=True,
            payouts_enabled=True,
            payout_account_id=f"acct_fake_{name[:4].lower()}",
            phone="+14045550000",
        )
        s.add(shop)
        await s.flush()
        s.add(
            ShopUser(
                shop_id=shop.id,
                email=email,
                password_hash=hash_password(SHOP_PASSWORD),
                totp_secret_encrypted=container.encryptor.encrypt(secret),
                mfa_enabled=True,
                email_verified_at=datetime.now(UTC),
            )
        )
        ids = []
        for spec in techs:
            tech = Technician(
                shop_id=shop.id, working_hours=ALL_DAY, service_radius_km=40.0, **spec
            )
            s.add(tech)
            await s.flush()
            ids.append(tech.id)
        await s.commit()
        return SeededShop(shop.id, email, secret, ids)


@pytest.fixture
async def shops(container: Container) -> dict[str, SeededShop]:
    near = await make_shop(
        container,
        name="Near HVAC",
        email="near@shop.example.com",
        offset=(0.01, 0.0),
        techs=[
            {
                "name": "Nina Near",
                "equipment_types": ["central_ac"],
                "certifications": ["epa_608"],
            },
        ],
    )
    far = await make_shop(
        container,
        name="Far HVAC",
        email="far@shop.example.com",
        offset=(0.08, 0.0),
        techs=[
            {
                "name": "Fred Far",
                "equipment_types": ["central_ac", "furnace"],
                "certifications": ["epa_608"],
            },
        ],
    )
    return {"near": near, "far": far}


async def homeowner_login(
    client: httpx.AsyncClient, phone: str = "(404) 555-0199", *, with_card: bool = True
) -> dict[str, str]:
    start = await client.post("/auth/homeowner/start", json={"phone": phone})
    assert start.status_code == 200, start.text
    body = start.json()
    key = "".join(ch for ch in phone if ch.isdigit())[-10:]
    if body["account"] == "new":
        secret = body["setup"]["secret"]
        verify = await client.post(
            "/auth/homeowner/signup",
            json={
                "phone": phone,
                "setup_token": body["setup"]["setup_token"],
                "code": totp_code(secret),
            },
        )
        STATE["secrets"][key] = secret
    else:
        verify = await client.post(
            "/auth/homeowner/login",
            json={"phone": phone, "code": totp_code(STATE["secrets"][key])},
        )
    assert verify.status_code == 200, verify.text
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    r = await client.patch(
        "/me",
        headers=headers,
        json={"name": "Jordan Lee", "address": "191 Peachtree St NE, Atlanta, GA 30303"},
    )
    assert r.status_code == 200, r.text
    if with_card:
        # The test gateway stands in for Stripe Elements confirming the SetupIntent.
        setup = (await client.post("/me/payment-methods/setup", headers=headers)).json()
        r = await client.post(
            "/me/payment-methods/finish",
            headers=headers,
            json={"setup_intent_id": setup["setup_intent_id"]},
        )
        assert r.json()["payment_method_label"] == "Visa •• 4242"
    return headers


STRONG_PASSWORD = "Furnace-Blue-27!"


def token_from_link(link: str) -> str:
    return link.split("?t=", 1)[1]


async def signup_shop(
    client: httpx.AsyncClient, clock: FrozenClock, email: str, shop_name: str
) -> dict[str, str]:
    """Sign up -> open the emailed link (development link) -> authenticator app -> signed in."""
    r = await client.post(
        "/auth/shop/signup",
        json={"email": email, "password": STRONG_PASSWORD, "shop_name": shop_name},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["step"] == "verify_email"
    setup = {"Authorization": f"Bearer {body['token']}"}
    token = token_from_link(body["email_link"]["dev_link"])
    r = await client.post("/auth/shop/verify-email", json={"token": token})
    assert r.status_code == 204, r.text
    status = (await client.get("/auth/shop/setup-status", headers=setup)).json()
    assert status["step"] == "mfa_setup"
    setup = {"Authorization": f"Bearer {status['token']}"}
    secret = (await client.post("/auth/shop/mfa/enroll", headers=setup)).json()["secret"]
    r = await client.post(
        "/auth/shop/mfa/activate", headers=setup, json={"code": pyotp.TOTP(secret).at(clock.now())}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def shop_login(
    client: httpx.AsyncClient, shop: SeededShop, clock: FrozenClock
) -> dict[str, str]:
    r = await client.post("/auth/shop/login", json={"email": shop.email, "password": SHOP_PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["step"] == "mfa"
    code = pyotp.TOTP(shop.totp_secret).at(clock.now())
    r = await client.post("/auth/shop/login/mfa", json={"token": body["token"], "code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def analyzed_request(
    client: httpx.AsyncClient, headers: dict[str, str], symptoms: list[str] | None = None
) -> dict[str, object]:
    r = await client.post(
        "/requests",
        headers=headers,
        json={
            "symptoms": symptoms or ["no_cooling"],
            "description": "Blowing warm air",
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    r = await client.post(
        f"/requests/{rid}/photos",
        headers=headers,
        files={"file": ("unit.png", png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"/requests/{rid}/analyze", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def shop_id_of_tech(container: Container, tech_id: object) -> object:
    async with container.session_factory() as s:
        return await s.scalar(select(Technician.shop_id).where(Technician.id == tech_id))
