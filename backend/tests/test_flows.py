"""End-to-end API flows through the real app, database and services."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.container import Container
from app.core.clock import FrozenClock
from app.integrations.payments.fake import FakePaymentGateway
from app.services.matching_service import MatchingService
from tests.conftest import (
    SeededShop,
    analyzed_request,
    homeowner_login,
    shop_login,
)


async def test_full_job_lifecycle(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    home = await homeowner_login(client)
    req = await analyzed_request(client, home)
    rid = req["id"]
    assert req["status"] == "analyzed"
    assert req["unit"]["brand"] == "Carrier"
    assert req["diagnosis"]["primary_issue"] == "capacitor"
    assert req["estimate"]["low_cents"] == 89_00 + 150_00

    r = await client.post(f"/requests/{rid}/match", headers=home)
    body = r.json()
    assert body["status"] == "proposed"
    assert body["technician"]["name"] == "Nina Near"  # closest qualified, free now
    assert body["technician"]["shop_phone"] is None  # hidden until dispatch

    r = await client.post(f"/requests/{rid}/confirm", headers=home)
    body = r.json()
    assert body["status"] == "offered"
    assert body["payment"]["authorized_cents"] == 239_00

    shop = await shop_login(client, shops["near"], clock)
    offers = (await client.get("/shop/jobs", headers=shop, params={"status": "offered"})).json()
    assert [o["id"] for o in offers] == [rid]
    assert offers[0]["address"] is None and offers[0]["customer_phone"] is None

    r = await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})
    assert r.json()["status"] == "dispatched"
    assert r.json()["customer_phone"] == "+14045550199"  # revealed after dispatch

    for step in ("en-route", "on-site"):
        assert (await client.post(f"/shop/jobs/{rid}/{step}", headers=shop)).status_code == 200

    # Final quote above the hold → approving it re-authorizes the higher amount.
    r = await client.post(
        f"/shop/jobs/{rid}/quote",
        headers=shop,
        json={"final_price_cents": 310_00, "notes": "Capacitor + contactor"},
    )
    assert r.json()["status"] == "quoted"
    r = await client.post(f"/requests/{rid}/approve-quote", headers=home)
    assert r.json()["status"] == "in_progress"
    assert r.json()["payment"]["authorized_cents"] == 310_00

    r = await client.post(f"/shop/jobs/{rid}/complete", headers=shop)
    assert r.json()["status"] == "completed"
    assert r.json()["payout_cents"] == 310_00 - 46_50  # 15% platform fee

    r = await client.post(f"/requests/{rid}/rating", headers=home, json={"rating": 5})
    assert r.json()["rating"] == 5

    gateway = container.payments
    assert isinstance(gateway, FakePaymentGateway)
    captured = [i for i in gateway.intents.values() if i.status == "succeeded"]
    assert len(captured) == 1 and captured[0].captured == 310_00
    assert any(i.status == "canceled" for i in gateway.intents.values())  # old hold released


async def test_busy_techs_book_the_earliest_opening(
    client: httpx.AsyncClient,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    """Nobody free right now: book whoever can arrive first after their current work."""
    near_shop = await shop_login(client, shops["near"], clock)
    far_shop = await shop_login(client, shops["far"], clock)
    await client.post(
        f"/shop/technicians/{shops['near'].tech_ids[0]}/busy",
        headers=near_shop,
        json={"minutes": 120},
    )
    await client.post(
        f"/shop/technicians/{shops['far'].tech_ids[0]}/busy",
        headers=far_shop,
        json={"minutes": 45},
    )
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    body = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert body["status"] == "proposed"
    # Fred is farther but free in 45 minutes; Nina is busy for 2 hours.
    assert body["technician"]["name"] == "Fred Far"
    assert 45 < body["technician"]["eta_minutes"] <= 65


async def test_waitlist_explains_then_matches_when_a_tech_qualifies(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    # Nobody nearby works on boilers.
    await client.patch(f"/requests/{rid}/unit", headers=home, json={"equipment_type": "boiler"})
    body = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert body["status"] == "waitlisted"
    assert body["waitlist"]["position"] == 1
    assert "qualified" in body["waitlist"]["reason"]

    # The near shop adds boilers to Nina's skills; the worker's batch places the request.
    near_shop = await shop_login(client, shops["near"], clock)
    r = await client.patch(
        f"/shop/technicians/{shops['near'].tech_ids[0]}",
        headers=near_shop,
        json={"equipment_types": ["central_ac", "boiler"]},
    )
    assert r.status_code == 200, r.text
    async with container.session_factory() as s:
        assert await MatchingService(s, container).process_waitlist() == 1
        await s.commit()

    body = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert body["status"] == "proposed"
    assert body["technician"]["name"] == "Nina Near"
    assert any("technician is available" in m for _, m in container.sms.outbox)  # type: ignore[attr-defined]


async def test_after_hours_request_books_next_morning(
    client: httpx.AsyncClient, clock: FrozenClock, shops: dict[str, SeededShop]
) -> None:
    """Both techs work 8:00-17:00 only; at 9 PM the homeowner gets tomorrow 8 AM, and the
    shop has until an hour before the visit to accept."""
    hours = {d: [["08:00", "17:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    for key in ("near", "far"):
        shop = await shop_login(client, shops[key], clock)
        r = await client.patch(
            f"/shop/technicians/{shops[key].tech_ids[0]}",
            headers=shop,
            json={"working_hours": hours},
        )
        assert r.status_code == 200, r.text
    clock.set(datetime(2026, 7, 16, 1, 0, tzinfo=UTC))  # 9:00 PM in Atlanta (EDT)
    home = await homeowner_login(client, "4045550111")
    rid = (await analyzed_request(client, home))["id"]
    body = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert body["status"] == "proposed", body
    assert body["technician"]["name"] == "Nina Near"
    arrival = datetime.fromisoformat(body["technician"]["arrival_at"])
    local = arrival.astimezone(ZoneInfo("America/New_York"))
    assert (local.day, local.hour) == (16, 8)  # tomorrow, first thing
    body = (await client.post(f"/requests/{rid}/confirm", headers=home)).json()
    offer_deadline = datetime.fromisoformat(body["offer_expires_at"])
    assert arrival - offer_deadline == timedelta(hours=1)


async def test_decline_offers_job_to_next_tech(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    await client.post(f"/requests/{rid}/confirm", headers=home)

    near = await shop_login(client, shops["near"], clock)
    assert (await client.post(f"/shop/jobs/{rid}/decline", headers=near)).status_code == 204

    body = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert body["status"] == "offered"
    assert body["technician"]["name"] == "Fred Far"
    # The near shop can no longer see the job.
    assert (await client.get(f"/shop/jobs/{rid}", headers=near)).status_code == 404


async def test_unanswered_offer_expires_and_moves_on(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    await client.post(f"/requests/{rid}/confirm", headers=home)

    clock.advance(seconds=container.settings.offer_ttl_seconds + 1)
    async with container.session_factory() as s:
        assert await MatchingService(s, container).expire_offers() == 1
        await s.commit()
    body = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert body["technician"]["name"] == "Fred Far"


async def test_proposal_expires_back_to_analyzed(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    clock.advance(seconds=container.settings.proposal_ttl_seconds + 1)
    async with container.session_factory() as s:
        assert await MatchingService(s, container).expire_proposals() == 1
        await s.commit()
    r = await client.post(f"/requests/{rid}/confirm", headers=home)
    assert r.status_code == 409


async def test_booking_requires_card(
    client: httpx.AsyncClient, shops: dict[str, SeededShop]
) -> None:
    home = await homeowner_login(client, with_card=False)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    r = await client.post(f"/requests/{rid}/confirm", headers=home)
    assert r.status_code == 402
    assert r.json()["error"]["code"] == "payment_method_required"


async def test_cancel_releases_hold(
    client: httpx.AsyncClient, container: Container, shops: dict[str, SeededShop]
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    await client.post(f"/requests/{rid}/confirm", headers=home)
    body = (await client.post(f"/requests/{rid}/cancel", headers=home)).json()
    assert body["status"] == "canceled"
    gateway = container.payments
    assert isinstance(gateway, FakePaymentGateway)
    assert all(i.status == "canceled" for i in gateway.intents.values())


@pytest.mark.parametrize("bad", [b"not an image", b"%PDF-1.4 fake"])
async def test_rejects_non_image_uploads(client: httpx.AsyncClient, bad: bytes) -> None:
    home = await homeowner_login(client, with_card=False)
    rid = (await client.post("/requests", headers=home, json={"symptoms": ["noisy"]})).json()["id"]
    r = await client.post(
        f"/requests/{rid}/photos", headers=home, files={"file": ("x.jpg", bad, "image/jpeg")}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_photo"
