"""The shop's own Housecall Pro jobs and customers: copied into our apps, and customers
invited to (and linked on) the homeowner app."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.container import Container
from app.core.clock import FrozenClock
from app.models import AvailabilityBlock, ExternalJob, ShopCustomer
from app.worker import tick
from tests.conftest import SeededShop, analyzed_request, homeowner_login, png_bytes, shop_login
from tests.test_dispatch import FakeHousecallPro, use_fake_hcp
from tests.test_technicians import join_as_technician


def hcp_job(
    clock: FrozenClock, job_id: str, *, employee: str | None = "emp_nina", hours: int = 2
) -> dict[str, Any]:
    start = clock.now() + timedelta(hours=hours)
    return {
        "id": job_id,
        "invoice_number": "1042",
        "description": "AC not cooling upstairs",
        "work_status": "scheduled",
        "customer": {
            "id": "cus_rosa",
            "first_name": "Rosa",
            "last_name": "Diaz",
            "mobile_number": "(404) 555-0123",
            "email": "rosa@example.com",
            "addresses": [
                {"street": "12 Elm St", "city": "Decatur", "state": "GA", "zip": "30030"}
            ],
        },
        "address": {"street": "12 Elm St", "city": "Decatur", "state": "GA", "zip": "30030"},
        "schedule": {
            "scheduled_start": start.isoformat(),
            "scheduled_end": (start + timedelta(hours=1)).isoformat(),
        },
        "assigned_employees": [{"id": employee}] if employee else [],
    }


async def connect(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> tuple[FakeHousecallPro, Container, dict[str, str]]:
    fake = FakeHousecallPro()
    c = use_fake_hcp(client, container, fake)
    shop = await shop_login(client, shops["near"], clock)
    nina = shops["near"].tech_ids[0]
    await client.patch(f"/shop/technicians/{nina}", headers=shop, json={"external_id": "emp_nina"})
    r = await client.put(
        "/shop/scheduling",
        headers=shop,
        json={"provider": "housecall_pro", "credentials": {"api_key": "key_abc"}},
    )
    assert r.status_code == 200, r.text
    return fake, c, shop


async def test_new_housecall_pro_job_reaches_the_technician_within_a_minute(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> None:
    fake, c, shop = await connect(client, container, shops, clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    assert (await client.get("/tech/jobs", headers=tech)).json()["outside_jobs"] == []

    # The office books a new customer's job in Housecall Pro and assigns Nina.
    fake.own_jobs = [hcp_job(clock, "job_77")]
    clock.advance(seconds=61)
    await tick(c)
    board = (await client.get("/tech/jobs", headers=tech)).json()
    [job] = board["outside_jobs"]
    assert job["customer_name"] == "Rosa Diaz" and job["address"].startswith("12 Elm St, Decatur")
    assert job["customer_phone"] == "+14045550123" and job["invoice_number"] == "1042"
    assert job["description"] == "AC not cooling upstairs" and job["provider"] == "housecall_pro"
    detail = await client.get(f"/tech/outside-jobs/{job['id']}", headers=tech)
    assert detail.status_code == 200

    # The office sees it too, and Nina's time is blocked for matching.
    office = (await client.get("/shop/outside-jobs", headers=shop)).json()
    assert [j["technician_name"] for j in office] == ["Nina Near"]
    async with c.session_factory() as session:
        busy = (
            await session.scalars(
                select(AvailabilityBlock).where(AvailabilityBlock.source == "housecall_pro")
            )
        ).all()
        assert [b.technician_id for b in busy] == [shops["near"].tech_ids[0]]

    # Reassigned to someone else in Housecall Pro: gone from Nina's app at the next sync.
    fake.own_jobs = [hcp_job(clock, "job_77", employee="emp_sam")]
    clock.advance(seconds=61)
    await tick(c)
    assert (await client.get("/tech/jobs", headers=tech)).json()["outside_jobs"] == []
    # Deleted in Housecall Pro: gone for the office too.
    fake.own_jobs = []
    clock.advance(seconds=61)
    await tick(c)
    assert (await client.get("/shop/outside-jobs", headers=shop)).json() == []


async def test_webhook_imports_right_away(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> None:
    fake, c, shop = await connect(client, container, shops, clock)
    token = (await client.get("/shop/me", headers=shop)).json()["shop"]["scheduling_webhook_url"]
    fake.own_jobs = [hcp_job(clock, "job_88")]
    r = await client.post(
        f"/webhooks/housecall-pro/{token.rsplit('/', 1)[1]}",
        json={"event": "job.created", "job": {"id": "job_88"}},
    )
    assert r.status_code == 200
    async with c.session_factory() as s:
        assert (await s.scalars(select(ExternalJob.external_id))).all() == ["job_88"]


async def test_customers_are_imported_invited_and_linked(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> None:
    fake, c, shop = await connect(client, container, shops, clock)
    fake.customers = [
        {
            "id": "cus_jordan",
            "first_name": "Jordan",
            "last_name": "Lee",
            "mobile_number": "404-555-0199",
            "addresses": [
                {"street": "191 Peachtree St NE", "city": "Atlanta", "state": "GA", "zip": "30303"}
            ],
        },
        {"id": "cus_kim", "first_name": "Kim", "last_name": "Park", "email": "kim@example.com"},
    ]
    r = await client.post("/shop/customers/import", headers=shop)
    assert r.json() == {"count": 2}
    listed = (await client.get("/shop/customers", headers=shop)).json()
    assert listed["total"] == 2 and listed["joined"] == 0
    assert listed["shop_invite_url"].startswith("http://localhost:8081/join/")
    jordan = next(x for x in listed["customers"] if x["name"] == "Jordan Lee")
    assert jordan["status"] == "not_invited" and jordan["phone"] == "+14045550199"
    assert (
        "Near HVAC" in jordan["invite_message"] and jordan["invite_url"] in jordan["invite_message"]
    )
    assert jordan["invite_message"].startswith("Hi Jordan!")

    r = await client.post(f"/shop/customers/{jordan['id']}/invited", headers=shop)
    assert r.json()["status"] == "invited"
    code = jordan["invite_url"].rsplit("/", 1)[1]
    info = (await client.get(f"/invites/{code}")).json()
    assert info == {"shop_name": "Near HVAC", "shop_phone": info["shop_phone"]}

    # Jordan signs up with the number the shop has on file: linked automatically.
    home = await homeowner_login(client)
    r = await client.post("/me/invite", headers=home, json={"code": code})
    assert r.json()["shop_name"] == "Near HVAC"
    suggestions = (await client.get("/me/suggestions", headers=home)).json()
    assert suggestions["companies"] == ["Near HVAC"]
    assert suggestions["address"].startswith("191 Peachtree St NE")
    listed = (await client.get("/shop/customers", headers=shop, params={"status": "joined"})).json()
    assert [x["name"] for x in listed["customers"]] == ["Jordan Lee"] and listed["joined"] == 1

    # A forwarded link used by someone else doesn't attach them to Jordan's record.
    other = await homeowner_login(client, "(404) 555-0188")
    await client.post("/me/invite", headers=other, json={"code": code})
    assert (await client.get("/me/suggestions", headers=other)).json()["address"] is None
    async with c.session_factory() as s:
        rows = (await s.scalars(select(ShopCustomer))).all()
        assert sorted(r.provider for r in rows) == ["app", "housecall_pro", "housecall_pro"]

    # Their company is listed first when choosing who comes.
    rid = (await analyzed_request(client, home))["id"]
    providers = (await client.get(f"/requests/{rid}/providers", headers=home)).json()
    assert providers["shops"][0]["name"] == "Near HVAC" and providers["shops"][0]["your_company"]

    # Search works on the (encrypted) names.
    found = (await client.get("/shop/customers", headers=shop, params={"q": "kim"})).json()
    assert [x["name"] for x in found["customers"]] == ["Kim Park"]
    assert (await client.get("/invites/NOPE1234")).status_code == 404


async def test_technician_runs_a_housecall_pro_job_in_the_app(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> None:
    fake, c, shop = await connect(client, container, shops, clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    fake.own_jobs = [hcp_job(clock, "job_77")]
    clock.advance(seconds=61)
    await tick(c)
    [job] = (await client.get("/tech/jobs", headers=tech)).json()["outside_jobs"]
    url = f"/tech/outside-jobs/{job['id']}"

    r = await client.post(f"{url}/step", headers=tech, json={"step": "on_my_way"})
    assert r.status_code == 200, r.text
    assert r.json()["app_status"] == "en_route" and r.json()["on_my_way_at"]
    # Can't finish before arriving / starting; can't go back.
    bad = await client.post(f"{url}/step", headers=tech, json={"step": "finished"})
    assert bad.status_code == 409
    await client.post(f"{url}/step", headers=tech, json={"step": "arrived"})
    await client.post(f"{url}/step", headers=tech, json={"step": "started"})

    r = await client.post(
        f"{url}/line-items",
        headers=tech,
        json={"name": "Run capacitor 45/5 uF", "quantity": 1, "unit_price_cents": 18_500},
    )
    detail = r.json()
    assert detail["line_items"] == [
        {
            "name": "Run capacitor 45/5 uF",
            "quantity": 1.0,
            "unit_price_cents": 18_500,
            "total_cents": 18_500,
        }
    ]
    assert fake.line_items["job_77"][0]["unit_price"] == 18_500  # cents, as Housecall Pro wants
    await client.post(f"{url}/notes", headers=tech, json={"body": "Contactor pitted, replace soon"})
    photo = await client.post(
        f"{url}/photos", headers=tech, files={"file": ("unit.png", png_bytes(), "image/png")}
    )
    assert photo.status_code == 200, photo.text
    assert len(fake.attachments["job_77"]) == 1

    # Housecall Pro goes down: actions wait, in order, and are retried by the worker.
    fake.down = True
    r = await client.post(
        f"{url}/step",
        headers=tech,
        json={"step": "finished", "summary": "Replaced run capacitor, tested OK"},
    )
    done = r.json()
    assert done["app_status"] == "finished" and done["unsent"] == 1
    assert done["activity"][-1]["sent"] is False and done["activity"][-1]["error"]
    [waiting] = (await client.get("/shop/outside-jobs", headers=shop)).json()
    assert waiting["unsent"] == 1  # the office sees it too
    fake.down = False
    await tick(c)
    done = (await client.get(url, headers=tech)).json()
    assert done["unsent"] == 0 and all(a["sent"] for a in done["activity"])
    assert [a["kind"] for a in done["activity"]] == [
        "status",
        "status",
        "status",
        "line_item",
        "note",
        "photo",
        "status",
    ]

    notes = fake.notes["job_77"]
    assert notes[0].startswith("On my way, ") and "Nina Near" in notes[0]
    assert "sent from HVAC Connect" in notes[0]
    assert notes[3].startswith("Nina Near: Contactor pitted")
    assert "Work done: Replaced run capacitor" in notes[-1]
    assert "Finish and invoice this job in Housecall Pro" in notes[-1]

    # The office sees where it stands; the next import keeps the app's progress.
    clock.advance(seconds=61)
    await tick(c)
    [row] = (await client.get("/shop/outside-jobs", headers=shop)).json()
    assert row["app_status"] == "finished" and row["finished_at"]
    # Another technician can't touch it.
    assert (
        await client.post(f"{url}/step", headers=shop, json={"step": "arrived"})
    ).status_code in (
        401,
        403,
    )


async def test_customer_using_both_sees_the_housecall_pro_visit_in_the_app(
    client: httpx.AsyncClient,
    container: Container,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
) -> None:
    fake, c, shop = await connect(client, container, shops, clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    fake.own_jobs = [hcp_job(clock, "job_77")]  # Rosa, (404) 555-0123
    clock.advance(seconds=61)
    await tick(c)

    rosa = await homeowner_login(client, "(404) 555-0123")  # the number the shop has on file
    [visit] = (await client.get("/me/visits", headers=rosa)).json()
    assert visit["shop_name"] == "Near HVAC" and visit["technician_first_name"] == "Nina"
    assert visit["status"] == "scheduled" and visit["description"] == "AC not cooling upstairs"

    [job] = (await client.get("/tech/jobs", headers=tech)).json()["outside_jobs"]
    await client.post(
        f"/tech/outside-jobs/{job['id']}/step", headers=tech, json={"step": "on_my_way"}
    )
    assert (await client.get("/me/visits", headers=rosa)).json()[0]["status"] == "en_route"
    # Someone else sees nothing.
    other = await homeowner_login(client, "(404) 555-0188")
    assert (await client.get("/me/visits", headers=other)).json() == []
