"""How shops take jobs: tiered waterfall (loyal shop first, instant book, one shop at a
time, then several at once), the office picking the technician, time off, and shops whose
Housecall Pro dispatcher assigns technicians."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx

from app.container import Container
from app.core.clock import FrozenClock
from app.domain.enums import SchedulingProvider
from app.integrations.scheduling.housecall_pro import HousecallProClient, parse_us_address
from app.services.external_jobs import ExternalJobService
from tests.conftest import (
    SeededShop,
    analyzed_request,
    homeowner_login,
    make_shop,
    shop_login,
)

AC_TECH = {"equipment_types": ["central_ac"], "certifications": ["epa_608"]}


async def book(
    client: httpx.AsyncClient, home: dict[str, str], choice: dict[str, str] | None = None
) -> dict[str, Any]:
    rid = (await analyzed_request(client, home))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=home, json=choice or {})).json()
    assert proposed["status"] == "proposed", proposed
    return (await client.post(f"/requests/{rid}/confirm", headers=home)).json()


async def finish(
    client: httpx.AsyncClient, shop: dict[str, str], home: dict[str, str], rid: str
) -> None:
    await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})
    for step in ("en-route", "on-site"):
        await client.post(f"/shop/jobs/{rid}/{step}", headers=shop)
    await client.post(f"/shop/jobs/{rid}/quote", headers=shop, json={"final_price_cents": 20000})
    await client.post(f"/requests/{rid}/approve-quote", headers=home)
    r = await client.post(f"/shop/jobs/{rid}/complete", headers=shop)
    assert r.json()["status"] == "completed"


async def test_instant_book_accepts_right_away_up_to_the_daily_limit(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    r = await client.patch(
        "/shop/dispatch", headers=shop, json={"instant_book": True, "instant_book_daily_limit": 1}
    )
    assert r.json()["shop"]["instant_book"] is True

    home = await homeowner_login(client)
    req = await book(client, home)
    assert req["status"] == "dispatched"  # no waiting for the shop
    assert req["technician"]["name"] == "Nina Near"
    jobs = (await client.get("/shop/jobs", headers=shop)).json()
    assert jobs[0]["instant_booked"] is True

    # Limit reached: the next job is offered normally.
    home2 = await homeowner_login(client, "(404) 555-0145")
    req2 = await book(client, home2, {"shop_id": str(shops["near"].shop_id)})
    assert req2["status"] == "offered"


async def test_returning_customer_gets_their_previous_shop_first(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    far = await shop_login(client, shops["far"], clock)
    first = await book(client, home, {"shop_id": str(shops["far"].shop_id)})
    await finish(client, far, home, first["id"])

    # Near HVAC could come a few minutes sooner, but Far HVAC did their last job.
    rid = (await analyzed_request(client, home))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert proposed["technician"]["shop_name"] == "Far HVAC"

    # A brand-new customer gets the soonest.
    other = await homeowner_login(client, "(404) 555-0146")
    rid = (await analyzed_request(client, other))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=other)).json()
    assert proposed["technician"]["shop_name"] == "Near HVAC"


async def test_waterfall_then_several_shops_at_once(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    mid = await make_shop(
        container,
        name="Mid HVAC",
        email="mid@shop.example.com",
        offset=(0.03, 0.0),
        techs=[{"name": "Mo Mid", **AC_TECH}],
    )
    mid2 = await make_shop(
        container,
        name="Mid Two HVAC",
        email="mid2@shop.example.com",
        offset=(0.05, 0.0),
        techs=[{"name": "Mia Mid", **AC_TECH}],
    )
    home = await homeowner_login(client)
    req = await book(client, home)
    rid = req["id"]
    near = await shop_login(client, shops["near"], clock)
    mid_h = await shop_login(client, mid, clock)
    mid2_h = await shop_login(client, mid2, clock)
    far = await shop_login(client, shops["far"], clock)

    # Round 1 and 2: one shop at a time.
    await client.post(f"/shop/jobs/{rid}/decline", headers=near)
    assert [j["id"] for j in (await client.get("/shop/jobs", headers=mid_h)).json()] == [rid]
    assert (await client.get("/shop/jobs", headers=mid2_h)).json() == []
    await client.post(f"/shop/jobs/{rid}/decline", headers=mid_h)

    # Round 3: the next best shops are offered at once, each with its own timing.
    offers2 = (await client.get("/shop/jobs", headers=mid2_h)).json()
    offers_far = (await client.get("/shop/jobs", headers=far)).json()
    assert [o["id"] for o in offers2] == [rid] and [o["id"] for o in offers_far] == [rid]
    assert offers2[0]["offered_to_several"] and offers_far[0]["technician_name"] == "Fred Far"
    assert offers_far[0]["arrival_at"] > offers2[0]["arrival_at"]

    # The farther shop accepts first and gets the job; the other offer is withdrawn.
    r = await client.post(f"/shop/jobs/{rid}/accept", headers=far, json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "dispatched"
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["technician"]["name"] == "Fred Far"
    assert (await client.get("/shop/jobs", headers=mid2_h)).json() == []
    late = await client.post(f"/shop/jobs/{rid}/accept", headers=mid2_h, json={})
    assert late.status_code in (403, 404, 409)


async def test_broadcast_round_moves_on_when_everyone_declines(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    container.settings.__dict__["waterfall_single_rounds"] = 1  # broadcast right after one decline
    mid = await make_shop(
        container,
        name="Mid HVAC",
        email="mid@shop.example.com",
        offset=(0.03, 0.0),
        techs=[{"name": "Mo Mid", **AC_TECH}],
    )
    home = await homeowner_login(client)
    rid = (await book(client, home))["id"]
    near = await shop_login(client, shops["near"], clock)
    await client.post(f"/shop/jobs/{rid}/decline", headers=near)
    mid_h = await shop_login(client, mid, clock)
    far = await shop_login(client, shops["far"], clock)
    assert len((await client.get("/shop/jobs", headers=mid_h)).json()) == 1
    assert len((await client.get("/shop/jobs", headers=far)).json()) == 1
    await client.post(f"/shop/jobs/{rid}/decline", headers=mid_h)
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["status"] == "offered" and req["technician"]["name"] == "Fred Far"
    await client.post(f"/shop/jobs/{rid}/decline", headers=far)
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["status"] == "waitlisted"


async def test_office_picks_the_technician(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    await client.patch("/shop/dispatch", headers=shop, json={"dispatch_mode": "office"})
    r = await client.post(
        "/shop/technicians",
        headers=shop,
        json={
            "name": "Omar Office",
            "equipment_types": ["central_ac"],
            "certifications": ["epa_608"],
            "working_hours": {
                d: [["00:00", "23:59"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
            },
        },
    )
    omar = r.json()["id"]
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    # The office decides who goes: the homeowner sees the company until then.
    assert proposed["technician"]["name"] == "Near HVAC technician"
    assert proposed["technician"]["assigned"] is False
    await client.post(f"/requests/{rid}/confirm", headers=home)

    options = (await client.get(f"/shop/jobs/{rid}/technician-options", headers=shop)).json()
    assert {o["name"] for o in options} == {"Nina Near", "Omar Office"}
    assert options[0]["suggested"] and options[0]["available"]
    r = await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={"technician_id": omar})
    assert r.json()["technician_name"] == "Omar Office"
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["technician"]["name"] == "Omar Office" and req["technician"]["assigned"]


async def test_time_off_keeps_a_technician_out_of_matching(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    nina = shops["near"].tech_ids[0]
    now = clock.now()
    r = await client.post(
        f"/shop/technicians/{nina}/time-off",
        headers=shop,
        json={
            "starts_at": now.isoformat(),
            "ends_at": (now + timedelta(days=2)).isoformat(),
            "label": "Vacation",
        },
    )
    assert r.status_code == 201
    block = r.json()
    listed = (await client.get(f"/shop/technicians/{nina}/time-off", headers=shop)).json()
    assert [b["label"] for b in listed] == ["Vacation"]

    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert proposed["technician"]["name"] == "Fred Far"

    await client.delete(f"/shop/technicians/{nina}/time-off/{block['id']}", headers=shop)
    assert (await client.get(f"/shop/technicians/{nina}/time-off", headers=shop)).json() == []


# --- Housecall Pro ---------------------------------------------------------------------------
class FakeHousecallPro:
    """Stand-in for api.housecallpro.com following its documented endpoints."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.job: dict[str, Any] = {
            "id": "job_1",
            "work_status": "scheduled",
            "assigned_employees": [],
        }
        self.deleted = False
        self.own_jobs: list[dict[str, Any]] = []  # created in Housecall Pro by the shop
        self.customers: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        self.calls.append((request.method, path, body))
        if not request.headers.get("authorization", "").startswith("Bearer key_"):
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/employees":
            return httpx.Response(
                200,
                json={
                    "employees": [
                        {"id": "emp_nina", "first_name": "Nina", "last_name": "Near"},
                        {
                            "id": "emp_sam",
                            "first_name": "Sam",
                            "last_name": "Hill",
                            "mobile_number": "4045550170",
                        },
                    ],
                    "total_pages": 1,
                },
            )
        if path == "/jobs" and request.method == "GET":
            return httpx.Response(200, json={"jobs": self.own_jobs, "total_pages": 1})
        if path == "/customers" and request.method == "GET":
            if request.url.params.get("q"):
                return httpx.Response(200, json={"customers": []})
            return httpx.Response(200, json={"customers": self.customers, "total_pages": 1})
        if path == "/customers" and request.method == "POST":
            street = body["addresses"][0]["street"]
            return httpx.Response(
                201, json={"id": "cus_1", "addresses": [{"id": "adr_1", "street": street}]}
            )
        if path == "/jobs" and request.method == "POST":
            self.job["schedule"] = body["schedule"]
            return httpx.Response(201, json={"id": "job_1"})
        if path == "/jobs/job_1" and request.method == "GET":
            if self.deleted:
                return httpx.Response(404, json={"error": "not found"})
            return httpx.Response(200, json=self.job)
        if path.startswith("/jobs/job_1/"):
            return httpx.Response(201, json={})
        return httpx.Response(404, json={"error": f"unexpected {path}"})


def use_fake_hcp(
    client: httpx.AsyncClient, container: Container, fake: FakeHousecallPro
) -> Container:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake))

    def factory(provider: SchedulingProvider, credentials: dict[str, Any]) -> HousecallProClient:
        assert provider == SchedulingProvider.HOUSECALL_PRO
        return HousecallProClient(
            api_key=credentials["api_key"],
            http=http,
            auth_scheme=credentials.get("auth_scheme", "Token"),
        )

    patched = replace(container, scheduling=factory)  # type: ignore[arg-type]
    client._transport.app.state.container = patched  # type: ignore[attr-defined]
    return patched


async def test_housecall_pro_dispatcher_assigns_the_technician(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    fake = FakeHousecallPro()
    c = use_fake_hcp(client, container, fake)
    shop = await shop_login(client, shops["near"], clock)
    nina = shops["near"].tech_ids[0]
    await client.patch(f"/shop/technicians/{nina}", headers=shop, json={"external_id": "emp_nina"})

    # Software dispatch needs the connection first.
    r = await client.patch("/shop/dispatch", headers=shop, json={"dispatch_mode": "software"})
    assert r.json()["error"]["code"] == "not_connected"
    r = await client.put(
        "/shop/scheduling",
        headers=shop,
        json={"provider": "housecall_pro", "credentials": {"api_key": "key_abc"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1  # Sam Hill imported; Nina already linked
    me = (
        await client.patch("/shop/dispatch", headers=shop, json={"dispatch_mode": "software"})
    ).json()
    assert me["shop"]["dispatch_mode"] == "software"
    hook = me["shop"]["scheduling_webhook_url"]
    assert "/v1/webhooks/housecall-pro/" in hook
    token = hook.rsplit("/", 1)[1]
    # The key format that worked ("Bearer") was remembered.
    assert any(call[0] == "GET" and call[1] == "/employees" for call in fake.calls)

    home = await homeowner_login(client)
    req = await book(client, home)
    rid = req["id"]
    assert req["technician"]["name"] == "Near HVAC technician"

    r = await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})
    job = r.json()
    assert job["status"] == "dispatched" and job["external_job_id"] == "job_1"
    assert job["technician_confirmed"] is False
    created = next(b for m, p, b in fake.calls if m == "POST" and p == "/jobs")
    assert "assigned_employee_ids" not in created  # the dispatcher picks
    assert created["customer_id"] == "cus_1" and created["address_id"] == "adr_1"
    assert "Booked through HVAC Connect" in created["notes"] and "Likely issue" in created["notes"]
    customer = next(b for m, p, b in fake.calls if m == "POST" and p == "/customers")
    assert customer["mobile_number"] == "+14045550199"
    assert (
        customer["addresses"][0]
        == {
            "street": "1 Test St",
            "city": "Atlanta",
            "state": "GA",
            "zip": "30303",
            "country": "US",
        }
        or customer["addresses"][0]["street"]
    )
    assert any(p == "/jobs/job_1/links" for _, p, _ in fake.calls)  # photo links
    home_view = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert home_view["technician"]["assigned"] is False

    # The dispatcher assigns Sam in Housecall Pro; our next sync picks it up.
    later = clock.now() + timedelta(hours=1)
    fake.job["assigned_employees"] = [{"id": "emp_sam"}]
    fake.job["schedule"] = {
        "scheduled_start": later.isoformat(),
        "scheduled_end": (later + timedelta(hours=1)).isoformat(),
    }
    clock.advance(seconds=61)
    async with c.session_factory() as s:
        assert await ExternalJobService(s, c).sync_due() == 1
        await s.commit()
    home_view = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert home_view["technician"]["name"] == "Sam Hill" and home_view["technician"]["assigned"]
    assert home_view["technician"]["arrival_at"].startswith(later.isoformat()[:16])

    # Housecall Pro calls our webhook when the tech starts: we re-read the job right away.
    fake.job["work_status"] = "in progress"
    assert (await client.post("/webhooks/housecall-pro/wrong", json={})).status_code == 404
    r = await client.post(
        f"/webhooks/housecall-pro/{token}", json={"event": "job.started", "job": {"id": "job_1"}}
    )
    assert r.status_code == 200
    home_view = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert home_view["status"] == "on_site"


async def test_housecall_pro_cancel_and_push_errors(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    fake = FakeHousecallPro()
    c = use_fake_hcp(client, container, fake)
    shop = await shop_login(client, shops["near"], clock)
    await client.put(
        "/shop/scheduling",
        headers=shop,
        json={"provider": "housecall_pro", "credentials": {"api_key": "key_abc"}},
    )
    await client.patch("/shop/dispatch", headers=shop, json={"dispatch_mode": "software"})
    home = await homeowner_login(client)
    rid = (await book(client, home))["id"]
    await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})

    # The job was deleted in Housecall Pro: the visit is canceled and the homeowner told.
    fake.deleted = True
    clock.advance(seconds=61)
    async with c.session_factory() as s:
        await ExternalJobService(s, c).sync_due()
        await s.commit()
    req = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert req["status"] == "canceled" and "Near HVAC canceled" in req["canceled_reason"]

    # A rejected key on push is shown to the shop and retried by the worker.
    r = await client.put(
        "/shop/scheduling",
        headers=shop,
        json={"provider": "housecall_pro", "credentials": {"api_key": "bad"}},
    )
    assert r.status_code >= 400
    assert "rejected" in r.json()["error"]["message"]


def test_us_address_parsing() -> None:
    a = parse_us_address("191 Peachtree St NE, Atlanta, GA 30303")
    assert (a.street, a.city, a.state, a.zip) == ("191 Peachtree St NE", "Atlanta", "GA", "30303")
    assert parse_us_address("Somewhere odd").street == "Somewhere odd"
