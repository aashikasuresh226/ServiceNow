"""End-to-end API flows through the real app, database and services."""

from __future__ import annotations

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

    r = await client.put(
        f"/requests/{rid}/preferences",
        headers=home,
        json={"soft_skills": ["punctual"], "require_all": False},
    )
    assert r.status_code == 200

    r = await client.post(f"/requests/{rid}/match", headers=home)
    body = r.json()
    assert body["status"] == "proposed"
    assert body["technician"]["name"] == "Nina Near"  # closest qualified + has the skill
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


async def test_waitlist_then_match_when_tech_frees_up(
    client: httpx.AsyncClient,
    container: Container,
    clock: FrozenClock,
    shops: dict[str, SeededShop],
) -> None:
    near_shop = await shop_login(client, shops["near"], clock)
    far_shop = await shop_login(client, shops["far"], clock)
    for headers, seeded in ((near_shop, shops["near"]), (far_shop, shops["far"])):
        for tid in seeded.tech_ids:
            r = await client.post(
                f"/shop/technicians/{tid}/busy", headers=headers, json={"minutes": 45}
            )
            assert r.status_code == 200, r.text

    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    body = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert body["status"] == "waitlisted"
    assert body["waitlist"]["position"] == 1
    assert 45 <= body["waitlist"]["eta_minutes"] <= 60  # busy 45 min + short drive

    # The near tech frees up; the background worker matches the waitlist.
    r = await client.delete(
        f"/shop/technicians/{shops['near'].tech_ids[0]}/busy", headers=near_shop
    )
    assert r.status_code == 200
    async with container.session_factory() as s:
        assert await MatchingService(s, container).process_waitlist() == 1
        await s.commit()

    body = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert body["status"] == "proposed"
    assert body["technician"]["name"] == "Nina Near"
    assert any("technician is available" in m for _, m in container.sms.outbox)  # type: ignore[attr-defined]


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
    rid = (
        await client.post(
            "/requests", headers=home, json={"symptoms": ["noisy"], "lat": 33.7, "lng": -84.4}
        )
    ).json()["id"]
    r = await client.post(
        f"/requests/{rid}/photos", headers=home, files={"file": ("x.jpg", bad, "image/jpeg")}
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_photo"
