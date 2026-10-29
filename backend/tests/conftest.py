"""Test fixtures: a real app + SQLite database, with fakes for every integration."""

from __future__ import annotations

import os
import struct
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pyotp
import pytest
from sqlalchemy import select

from app.container import Container, build_container
from app.core.clock import FrozenClock
from app.core.config import Environment, Settings
from app.core.db import Base
from app.core.security import hash_password
from app.integrations.payments.fake import FakePaymentGateway
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


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 7, 15, 16, 0, tzinfo=UTC))


@pytest.fixture
async def container(tmp_path: Path, clock: FrozenClock) -> AsyncIterator[Container]:
    settings = Settings(
        environment=Environment.DEV,  # exposes dev codes so tests can sign in
        # Set HVAC_TEST_DATABASE_URL to run the suite against Postgres (as CI should).
        database_url=os.environ.get(
            "HVAC_TEST_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
        ),
        storage_dir=str(tmp_path / "uploads"),
        run_worker_in_process=False,
    )
    built = build_container(settings)
    built = replace(built, clock=clock, sms=ConsoleSmsSender(), payments=FakePaymentGateway())
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
                "soft_skills": ["punctual"],
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
                "soft_skills": ["punctual", "explains_clearly"],
            },
        ],
    )
    return {"near": near, "far": far}


async def homeowner_login(
    client: httpx.AsyncClient, phone: str = "(404) 555-0199", *, with_card: bool = True
) -> dict[str, str]:
    start = (await client.post("/auth/homeowner/otp/start", json={"phone": phone})).json()
    verify = await client.post(
        "/auth/homeowner/otp/verify", json={"phone": phone, "code": start["dev_code"]}
    )
    assert verify.status_code == 200, verify.text
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    r = await client.patch(
        "/me",
        headers=headers,
        json={"name": "Jordan Lee", "address": "191 Peachtree St", "lat": HOME[0], "lng": HOME[1]},
    )
    assert r.status_code == 200, r.text
    if with_card:
        setup = (await client.post("/me/payment-methods/setup", headers=headers)).json()
        r = await client.post(
            "/me/payment-methods/demo-card",
            headers=headers,
            json={
                "setup_intent_id": setup["setup_intent_id"],
                "card_number": "4242 4242 4242 4242",
            },
        )
        assert r.status_code == 204, r.text
        r = await client.post(
            "/me/payment-methods/finish",
            headers=headers,
            json={"setup_intent_id": setup["setup_intent_id"]},
        )
        assert r.json()["payment_method_label"] == "Visa •• 4242"
    return headers


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
            "lat": HOME[0],
            "lng": HOME[1],
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
