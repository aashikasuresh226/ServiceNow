"""Technician accounts (invite by email, permissions), chat, live location, encryption."""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import replace
from pathlib import Path

import httpx
from sqlalchemy import text

from app.container import Container
from app.core.clock import FrozenClock
from app.core.db import prepare_database_url
from app.core.passwords import breach_count
from app.integrations.ai.base import AnalysisResult
from app.models import TechLocation
from tests.conftest import (
    STATE,
    SeededShop,
    analyzed_request,
    homeowner_login,
    shop_login,
    token_from_link,
    totp_code,
)

TECH_PHONE = "(404) 555-0177"


async def join_as_technician(
    client: httpx.AsyncClient,
    shop_headers: dict[str, str],
    tech_id: object,
    *,
    phone: str = TECH_PHONE,
    **permissions: object,
) -> dict[str, str]:
    r = await client.post(
        f"/shop/technicians/{tech_id}/invite",
        headers=shop_headers,
        json={"email": "nina@tech.example.com", **permissions},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["technician"]["app_status"] == "invited"
    token = token_from_link(body["email_link"]["dev_link"])
    assert body["email_link"]["continue_url"].startswith("http://localhost:8081/tech/join?t=")

    info = (await client.get(f"/auth/technician/invite/{token}")).json()
    assert info["technician_name"] == "Nina Near" and info["email"] == "nina@tech.example.com"
    # The link alone isn't enough: the email must be proven first (Firebase in production).
    r = await client.post(
        "/auth/technician/invite/authenticator", json={"token": token, "claim": "x" * 20}
    )
    assert r.status_code == 401
    claim = (
        await client.post("/auth/technician/invite/verify-email", json={"token": token})
    ).json()["claim"]
    setup = (
        await client.post(
            "/auth/technician/invite/authenticator", json={"token": token, "claim": claim}
        )
    ).json()
    r = await client.post(
        "/auth/technician/invite/accept",
        json={
            "token": token,
            "claim": claim,
            "phone": phone,
            "setup_token": setup["setup_token"],
            "code": totp_code(setup["secret"]),
        },
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["backup_codes"]) == 8
    STATE["secrets"]["tech:" + phone] = setup["secret"]
    STATE["secrets"]["tech-backup:" + phone] = r.json()["backup_codes"]
    # The invite works once.
    assert (await client.get(f"/auth/technician/invite/{token}")).status_code == 404
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def booked_request(
    client: httpx.AsyncClient, home: dict[str, str], technician_id: object = None
) -> str:
    rid = (await analyzed_request(client, home))["id"]
    choice = {"technician_id": str(technician_id)} if technician_id else {}
    proposed = (await client.post(f"/requests/{rid}/match", headers=home, json=choice)).json()
    assert proposed["technician"]["name"] == "Nina Near"
    r = await client.post(f"/requests/{rid}/confirm", headers=home)
    assert r.json()["status"] == "offered"
    return str(rid)


async def test_technician_invite_accept_drive_chat_complete(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech_id = shops["near"].tech_ids[0]
    tech = await join_as_technician(client, shop, tech_id)
    me = (await client.get("/tech/me", headers=tech)).json()
    assert me["shop_name"] == "Near HVAC" and me["phone"] == "+14045550177"
    techs = (await client.get("/shop/technicians", headers=shop)).json()
    assert techs[0]["app_status"] == "active"

    # Sign in again later: phone or email, plus the authenticator code (or a backup code).
    secret = STATE["secrets"]["tech:" + TECH_PHONE]
    r = await client.post(
        "/auth/technician/login", json={"login": TECH_PHONE, "code": totp_code(secret)}
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/auth/technician/login",
        json={"login": "nina@tech.example.com", "code": totp_code(secret)},
    )
    assert r.status_code == 200, r.text
    backup = STATE["secrets"]["tech-backup:" + TECH_PHONE][0]
    r = await client.post("/auth/technician/login", json={"login": TECH_PHONE, "code": backup})
    assert r.status_code == 200, r.text
    r = await client.post("/auth/technician/login", json={"login": TECH_PHONE, "code": backup})
    assert r.status_code == 401  # each backup code works once
    unknown = await client.post(
        "/auth/technician/login", json={"login": "(404) 555-0166", "code": "123456"}
    )
    assert unknown.status_code == 401

    home = await homeowner_login(client)
    rid = await booked_request(client, home)

    board = (await client.get("/tech/jobs", headers=tech)).json()
    assert [o["id"] for o in board["offers"]] == [rid]
    offer = board["offers"][0]
    assert offer["customer_name"] is None and offer["address"] is None  # until accepted

    job = (await client.post(f"/tech/jobs/{rid}/accept", headers=tech)).json()
    assert job["status"] == "dispatched"
    assert job["customer_name"] == "Jordan Lee" and job["address"]
    assert job["customer_phone"] == "+14045550199"

    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["technician"]["phone"] == "+14045550177" and req["technician"]["can_message"]
    assert req["technician"]["location"] is None  # assigned, but not on the way yet

    # No location before driving.
    loc = {"lat": 33.70, "lng": -84.40, "accuracy_m": 12}
    assert (
        await client.put(f"/tech/jobs/{rid}/location", headers=tech, json=loc)
    ).status_code == 409

    await client.post(f"/tech/jobs/{rid}/start-driving", headers=tech)
    r = await client.put(f"/tech/jobs/{rid}/location", headers=tech, json=loc)
    assert r.status_code == 204
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["status"] == "en_route"
    assert req["technician"]["location"] == {"lat": 33.70, "lng": -84.40}
    # Stored encrypted.
    async with container.engine.connect() as conn:
        raw = (await conn.execute(text("SELECT lat FROM tech_locations"))).scalar()
    assert str(raw).startswith("enc1:")
    # Another homeowner can't see it.
    other = await homeowner_login(client, "(404) 555-0144", with_card=False)
    assert (await client.get(f"/requests/{rid}", headers=other)).status_code == 404

    # Chat: technician, homeowner and the shop office share one thread.
    r = await client.post(
        f"/tech/jobs/{rid}/messages", headers=tech, json={"body": "On my way, 12 min."}
    )
    assert r.status_code == 201
    await client.post(f"/requests/{rid}/messages", headers=home, json={"body": "Gate code 4412"})
    await client.post(f"/shop/jobs/{rid}/messages", headers=shop, json={"body": "Thanks!"})
    thread = (await client.get(f"/requests/{rid}/messages", headers=home)).json()
    assert [(m["sender"], m["body"]) for m in thread] == [
        ("technician", "On my way, 12 min."),
        ("homeowner", "Gate code 4412"),
        ("shop", "Thanks!"),
    ]
    async with container.engine.connect() as conn:
        bodies = (await conn.execute(text("SELECT body FROM messages"))).scalars().all()
    assert all(b.startswith("enc1:") for b in bodies)

    # Arrival ends location sharing and deletes the stored position.
    await client.post(f"/tech/jobs/{rid}/arrived", headers=tech)
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["status"] == "on_site" and req["technician"]["location"] is None
    async with container.session_factory() as s:
        assert (await s.execute(text("SELECT COUNT(*) FROM tech_locations"))).scalar() == 0
    assert (
        await client.put(f"/tech/jobs/{rid}/location", headers=tech, json=loc)
    ).status_code == 409

    job = (
        await client.post(
            f"/tech/jobs/{rid}/quote", headers=tech, json={"final_price_cents": 18500}
        )
    ).json()
    assert job["status"] == "quoted"
    await client.post(f"/requests/{rid}/approve-quote", headers=home)
    job = (await client.post(f"/tech/jobs/{rid}/complete", headers=tech)).json()
    assert job["status"] == "completed"
    _ = TechLocation  # imported for clarity: the table above


async def test_company_permissions_are_enforced(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech_id = shops["near"].tech_ids[0]
    tech = await join_as_technician(
        client,
        shop,
        tech_id,
        can_respond_offers=False,
        can_contact_customers=False,
        schedule_view="next",
    )
    home = await homeowner_login(client)
    rid = await booked_request(client, home)

    # Offers go to the office, not the technician.
    board = (await client.get("/tech/jobs", headers=tech)).json()
    assert board["offers"] == [] and board["jobs"] == []
    assert (await client.post(f"/tech/jobs/{rid}/accept", headers=tech)).status_code == 404
    await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})

    job = (await client.get(f"/tech/jobs/{rid}", headers=tech)).json()
    assert job["address"] and job["customer_phone"] is None and job["can_contact"] is False
    assert (await client.get(f"/tech/jobs/{rid}/messages", headers=tech)).status_code == 403
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["technician"]["phone"] is None and req["technician"]["can_message"] is False
    assert req["chat_open"]  # the homeowner can still message the office

    # "I can't make it" flags the job for the office.
    r = await client.post(
        f"/tech/jobs/{rid}/cant-make-it", headers=tech, json={"reason": "Truck broke down"}
    )
    assert r.json()["technician_flag"] == "Truck broke down"
    jobs = (await client.get("/shop/jobs", headers=shop)).json()
    assert jobs[0]["technician_flag"] == "Truck broke down"

    # "Next job only": a second booked job stays hidden.
    home2 = await homeowner_login(client, "(404) 555-0145")
    rid2 = await booked_request(client, home2, tech_id)  # the customer picks Nina
    await client.post(f"/shop/jobs/{rid2}/accept", headers=shop, json={})
    board = (await client.get("/tech/jobs", headers=tech)).json()
    assert len(board["jobs"]) == 1 and board["hidden_jobs"] == 1
    hidden = rid2 if board["jobs"][0]["id"] == rid else rid
    assert (await client.get(f"/tech/jobs/{hidden}", headers=tech)).status_code == 404

    # The company switches off app access: the session ends at once.
    await client.delete(f"/shop/technicians/{tech_id}/app-access", headers=shop)
    assert (await client.get("/tech/me", headers=tech)).status_code == 401


async def test_shop_cant_hijack_an_invite_or_change_a_joined_techs_phone(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech_id = shops["near"].tech_ids[0]
    await join_as_technician(client, shop, tech_id)
    r = await client.patch(
        f"/shop/technicians/{tech_id}", headers=shop, json={"phone": "(404) 555-0100"}
    )
    assert r.json()["error"]["code"] == "phone_locked"
    r = await client.post(
        f"/shop/technicians/{tech_id}/invite", headers=shop, json={"email": "x@tech.example.com"}
    )
    assert r.json()["error"]["code"] == "already_joined"


async def test_personal_data_is_encrypted_at_rest(
    client: httpx.AsyncClient, container: Container
) -> None:
    home = await homeowner_login(client)
    await analyzed_request(client, home)
    async with container.engine.connect() as conn:
        row = (
            await conn.execute(text("SELECT name, phone, address, phone_hash FROM homeowners"))
        ).one()
        request = (
            await conn.execute(text("SELECT address, description FROM service_requests"))
        ).one()
    assert all(str(v).startswith("enc1:") for v in (*row[:3], *request))
    assert "Jordan" not in str(row) and "4045550199" not in str(row)
    assert len(row.phone_hash) == 64
    # The app still reads it normally.
    assert (await client.get("/me", headers=home)).json()["name"] == "Jordan Lee"

    # Photos are encrypted on disk too.
    def file_starts() -> list[bytes]:
        return [f.read_bytes()[:5] for f in Path(container.settings.storage_dir).iterdir()]

    starts = await asyncio.to_thread(file_starts)
    assert starts and all(start == b"enc1:" for start in starts)


async def test_invalid_phone_numbers_are_rejected(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/homeowner/start", json={"phone": "(999) 123-4567"})
    assert r.json()["error"]["code"] == "invalid_phone"


async def test_slow_ai_gives_up_after_the_time_budget(
    client: httpx.AsyncClient, container: Container
) -> None:
    class Slow:
        async def analyze(self, **_: object) -> AnalysisResult:
            await asyncio.sleep(5)
            raise AssertionError("should have timed out")

    app = client._transport.app  # type: ignore[attr-defined]
    settings = container.settings.model_copy(update={"ai_time_budget_seconds": 0.2})
    app.state.container = replace(container, analyzer=Slow(), settings=settings)
    home = await homeowner_login(client, with_card=False)
    request = await analyzed_request(client, home)
    assert "longer than" in request["diagnosis"]["ai_error"]
    assert request["status"] == "analyzed"  # the homeowner can still book


def test_hosted_postgres_urls_are_accepted() -> None:
    url, args = prepare_database_url(
        "postgresql://neondb_owner:secret@ep-cool-1234-pooler.us-east-2.aws.neon.tech/neondb"
        "?sslmode=require&channel_binding=require"
    )
    assert url.startswith("postgresql+asyncpg://neondb_owner:secret@ep-cool-1234-pooler")
    assert "sslmode" not in url and "channel_binding" not in url
    assert isinstance(args["ssl"], ssl.SSLContext)
    assert args["ssl"].verify_mode == ssl.CERT_REQUIRED
    assert args["statement_cache_size"] == 0
    url, args = prepare_database_url("postgresql+asyncpg://hvac:hvac@localhost:5432/hvac")
    assert args == {}


async def test_breach_check_uses_only_a_hash_prefix() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        # SHA-1("Furnace-Blue-27!") suffixes would be listed here if it had leaked.
        return httpx.Response(200, text="0000000000000000000000000000000000A:3\r\n")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await breach_count("Furnace-Blue-27!", http) == 0
    assert len(seen) == 1 and seen[0].startswith("https://api.pwnedpasswords.com/range/")
    assert len(seen[0].rsplit("/", 1)[1]) == 5  # only 5 hex characters leave the server
    assert "Furnace" not in seen[0]
