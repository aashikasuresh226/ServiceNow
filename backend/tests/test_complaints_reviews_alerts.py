"""Private reviews, complaints about technicians, and new-message alerts for homeowners."""

from __future__ import annotations

import httpx
from sqlalchemy import text

from app.container import Container
from app.core.clock import FrozenClock
from tests.conftest import ADMIN_KEY, SeededShop, analyzed_request, homeowner_login, shop_login
from tests.test_providers import _complete
from tests.test_technicians import booked_request, join_as_technician

ADMIN = {"X-Admin-Key": ADMIN_KEY}


async def test_shops_see_only_averages_admin_sees_reviews(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    shop = await shop_login(client, shops["near"], clock)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    await _complete(client, home, shop, rid)
    r = await client.post(
        f"/requests/{rid}/rating",
        headers=home,
        json={"technician_rating": 2, "shop_rating": 3, "review": "Tracked mud everywhere"},
    )
    assert r.status_code == 200

    jobs = (await client.get("/shop/jobs", headers=shop, params={"status": "completed"})).json()
    [job] = [j for j in jobs if j["id"] == rid]
    assert not {"technician_rating", "shop_rating", "review"} & job.keys()
    assert "Tracked mud" not in str(jobs)
    me = (await client.get("/shop/me", headers=shop)).json()
    assert me["shop"]["rating"] == 3.0 and me["shop"]["rating_count"] == 1  # the average only
    techs = (await client.get("/shop/technicians", headers=shop)).json()
    assert techs[0]["rating"] == 2.0

    assert (await client.get("/admin/reviews")).status_code == 401
    preflight = await client.options(
        "/admin/reviews",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-admin-key",
        },
    )
    assert preflight.status_code == 200  # the portal's /admin page can send the key
    assert (await client.get("/admin/reviews", headers={"X-Admin-Key": "nope"})).status_code == 401
    [review] = (await client.get("/admin/reviews", headers=ADMIN)).json()
    assert review["review"] == "Tracked mud everywhere" and review["shop_name"] == "Near HVAC"
    assert review["technician_name"] == "Nina Near" and review["technician_rating"] == 2


async def test_complaint_goes_to_shop_and_admin_not_technician(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    home = await homeowner_login(client)
    rid = await booked_request(client, home)

    # Not before a technician is assigned.
    state = (await client.get(f"/requests/{rid}/complaint", headers=home)).json()
    assert state["can_file"] is False and "late" in state["categories"]
    await client.post(f"/tech/jobs/{rid}/accept", headers=tech)
    assert (await client.get(f"/requests/{rid}/complaint", headers=home)).json()["can_file"]

    bad = await client.post(
        f"/requests/{rid}/complaint", headers=home, json={"category": "late", "details": "late"}
    )
    assert bad.status_code == 400  # too short
    r = await client.post(
        f"/requests/{rid}/complaint",
        headers=home,
        json={"category": "unprofessional", "details": "He was rude and left the gate open."},
    )
    assert r.status_code == 201, r.text
    again = await client.post(
        f"/requests/{rid}/complaint",
        headers=home,
        json={"category": "late", "details": "Also he was two hours late."},
    )
    assert again.status_code == 409

    [seen] = (await client.get("/shop/complaints", headers=shop)).json()
    assert seen["technician_name"] == "Nina Near" and seen["customer_name"] == "Jordan"
    assert seen["category_label"] == "Rude or unprofessional" and seen["status"] == "open"
    [admin] = (await client.get("/admin/complaints", headers=ADMIN)).json()
    assert admin["shop_name"] == "Near HVAC" and admin["details"].startswith("He was rude")
    # Other shops and the technician can't see it.
    far = await shop_login(client, shops["far"], clock)
    assert (await client.get("/shop/complaints", headers=far)).json() == []
    assert "rude" not in str((await client.get("/tech/jobs", headers=tech)).json())
    assert "rude" not in str((await client.get(f"/tech/jobs/{rid}", headers=tech)).json())
    # Stored encrypted.
    async with container.engine.connect() as conn:
        raw = (await conn.execute(text("SELECT details FROM complaints"))).scalar()
    assert str(raw).startswith("enc1:")

    # The company replies and resolves; the homeowner sees the reply.
    r = await client.post(
        f"/shop/complaints/{seen['id']}/response",
        headers=shop,
        json={
            "response": "Sorry. We spoke with Nina and will credit your visit.",
            "resolved": True,
        },
    )
    assert r.json()["status"] == "resolved" and r.json()["resolved_by"] == "shop"
    mine = (await client.get(f"/requests/{rid}/complaint", headers=home)).json()
    assert mine["can_file"] is False
    assert mine["complaint"]["shop_response"].startswith("Sorry.")
    # The admin can reopen it with a private note.
    r = await client.patch(
        f"/admin/complaints/{seen['id']}",
        headers=ADMIN,
        json={"note": "Second complaint about this tech", "status": "open"},
    )
    assert r.json()["status"] == "open" and r.json()["admin_note"].startswith("Second")
    assert "admin_note" not in (await client.get("/shop/complaints", headers=shop)).json()[0]


async def test_homeowner_is_alerted_to_new_messages(
    client: httpx.AsyncClient,
    shops: dict[str, SeededShop],
    clock: FrozenClock,
    container: Container,
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    home = await homeowner_login(client)
    rid = await booked_request(client, home)
    await client.post(f"/tech/jobs/{rid}/accept", headers=tech)
    assert (await client.get("/me/notifications", headers=home)).json()["total_unread"] == 0

    texts: list[str] = []
    original = container.sms.send  # type: ignore[union-attr]

    async def capture(*, to: str, body: str) -> None:
        texts.append(body)
        await original(to=to, body=body)

    container.sms.send = capture  # type: ignore[method-assign,union-attr]
    await client.post(f"/tech/jobs/{rid}/messages", headers=tech, json={"body": "On my way!"})
    clock.advance(seconds=5)
    await client.post(
        f"/shop/jobs/{rid}/messages", headers=shop, json={"body": "Nina is 10 min out"}
    )
    alerts = (await client.get("/me/notifications", headers=home)).json()
    assert alerts["total_unread"] == 2
    [chat] = alerts["unread_messages"]
    assert (
        chat["request_id"] == rid and chat["count"] == 2 and chat["preview"] == "Nina is 10 min out"
    )
    assert len(texts) == 1 and "New message" in texts[0]  # one text per burst, not per message

    await client.get(f"/requests/{rid}/messages", headers=home)  # opening the chat reads them
    assert (await client.get("/me/notifications", headers=home)).json()["total_unread"] == 0
    clock.advance(seconds=5)
    await client.post(f"/tech/jobs/{rid}/messages", headers=tech, json={"body": "Here now"})
    assert (await client.get("/me/notifications", headers=home)).json()["total_unread"] == 1
    assert len(texts) == 2
