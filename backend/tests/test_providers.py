"""Choosing a company or technician, rating both, and sharing a contact."""

from __future__ import annotations

import httpx

from app.core.clock import FrozenClock
from tests.conftest import SeededShop, analyzed_request, homeowner_login, shop_login


async def _complete(
    client: httpx.AsyncClient,
    home: dict[str, str],
    shop: dict[str, str],
    rid: str,
) -> None:
    await client.post(f"/requests/{rid}/confirm", headers=home)
    for step in ("accept", "en-route", "on-site"):
        r = await client.post(f"/shop/jobs/{rid}/{step}", headers=shop, json={})
        assert r.status_code == 200, r.text
    await client.post(f"/shop/jobs/{rid}/quote", headers=shop, json={"final_price_cents": 20_000})
    await client.post(f"/requests/{rid}/approve-quote", headers=home)
    r = await client.post(f"/shop/jobs/{rid}/complete", headers=shop)
    assert r.json()["status"] == "completed", r.text


async def test_homeowner_lists_and_picks_a_company_or_technician(
    client: httpx.AsyncClient, shops: dict[str, SeededShop]
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]

    providers = (await client.get(f"/requests/{rid}/providers", headers=home)).json()
    assert [s["name"] for s in providers["shops"]] == ["Near HVAC", "Far HVAC"]  # soonest first
    assert [t["name"] for t in providers["technicians"]] == ["Nina Near", "Fred Far"]
    assert providers["technicians"][0]["arrival_at"]

    # Pick the farther company: matching stays within it.
    far_shop = providers["shops"][1]["id"]
    body = (
        await client.post(f"/requests/{rid}/match", headers=home, json={"shop_id": far_shop})
    ).json()
    assert body["status"] == "proposed"
    assert body["technician"]["name"] == "Fred Far"
    assert body["preferred_shop_id"] == far_shop
    await client.post(f"/requests/{rid}/cancel", headers=home)

    # Pick a specific technician.
    rid = (await analyzed_request(client, home))["id"]
    fred = shops["far"].tech_ids[0]
    body = (
        await client.post(f"/requests/{rid}/match", headers=home, json={"technician_id": str(fred)})
    ).json()
    assert body["technician"]["name"] == "Fred Far"


async def test_picked_technician_without_opening_says_so(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    far = await shop_login(client, shops["far"], clock)
    fred = shops["far"].tech_ids[0]
    await client.patch(f"/shop/technicians/{fred}", headers=far, json={"working_hours": {}})
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    r = await client.post(f"/requests/{rid}/match", headers=home, json={"technician_id": str(fred)})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "provider_unavailable"
    assert "no opening" in r.json()["error"]["message"]
    # The request is still open: book the soonest available instead.
    body = (await client.post(f"/requests/{rid}/match", headers=home, json={})).json()
    assert body["technician"]["name"] == "Nina Near"


async def test_declined_pick_goes_to_another_tech(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    nina = shops["near"].tech_ids[0]
    await client.post(f"/requests/{rid}/match", headers=home, json={"technician_id": str(nina)})
    await client.post(f"/requests/{rid}/confirm", headers=home)
    near = await shop_login(client, shops["near"], clock)
    await client.post(f"/shop/jobs/{rid}/decline", headers=near)
    body = (await client.get(f"/requests/{rid}", headers=home)).json()
    assert body["status"] == "offered"
    assert body["technician"]["name"] == "Fred Far"


async def test_rate_technician_and_company_then_share(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    near = await shop_login(client, shops["near"], clock)
    await client.patch("/shop/me", headers=near, json={"phone": "(404) 555-0123"})
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)

    r = await client.get(f"/requests/{rid}/share", headers=home)
    assert r.status_code == 409  # only after the job is done

    await _complete(client, home, near, rid)
    r = await client.post(
        f"/requests/{rid}/rating",
        headers=home,
        json={"technician_rating": 5, "shop_rating": 4, "review": "Fast and friendly"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["rating"], r.json()["shop_rating"]) == (5, 4)
    r = await client.post(f"/requests/{rid}/rating", headers=home, json={"shop_rating": 5})
    assert r.status_code == 409  # once per job

    share = (await client.get(f"/requests/{rid}/share", headers=home)).json()
    tech_msg = share["technician"]["message"]
    assert "Nina Near" in tech_msg and "(404) 555-0123" in tech_msg and "★ 5.0" in tech_msg
    assert share["technician"]["url"].endswith(f"/p/technician/{shops['near'].tech_ids[0]}")
    assert "★ 4.0" in share["shop"]["message"]

    # The shared links open public cards (no customer data).
    tech_card = (await client.get(f"/providers/technicians/{shops['near'].tech_ids[0]}")).json()
    assert tech_card["name"] == "Nina Near" and tech_card["rating"] == 5.0
    assert tech_card["shop"]["phone"] == "(404) 555-0123"
    shop_card = (await client.get(f"/providers/shops/{shops['near'].shop_id}")).json()
    assert shop_card["rating"] == 4.0 and shop_card["rating_count"] == 1
