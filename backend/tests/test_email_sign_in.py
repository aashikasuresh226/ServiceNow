"""Signing in with an emailed link instead of an authenticator app."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx

from app.core.clock import FrozenClock
from tests.conftest import SeededShop, homeowner_login, shop_login, token_from_link

PHONE = "(404) 555-0123"


def link_parts(link: str) -> dict[str, str]:
    query = parse_qs(urlparse(link).query)
    return {k: v[0] for k, v in query.items()}


async def email_signup(client: httpx.AsyncClient, email: str = "sam@example.com") -> dict[str, str]:
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start["account"] == "new"
    r = await client.post("/auth/homeowner/email/start", json={"phone": PHONE, "email": email})
    assert r.status_code == 200, r.text
    assert r.json()["sent_to"] == f"{email[0]}***@example.com"
    return link_parts(r.json()["dev_link"])


async def test_new_homeowner_signs_up_with_an_email_link(client: httpx.AsyncClient) -> None:
    parts = await email_signup(client)
    assert parts["p"] == "14045550123"
    # No account until the link is opened.
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start["account"] == "new"

    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": parts["t"], "phone": parts["p"]}
    )
    assert r.status_code == 200, r.text
    assert r.json()["needs_profile"] is True
    me = (
        await client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    ).json()
    assert me["email"] == "sam@example.com"

    # Single use.
    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": parts["t"], "phone": parts["p"]}
    )
    assert r.json()["error"]["code"] == "link_expired"

    # Next time: the account signs in by email, to the address on file (not what's typed).
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start == {
        **start,
        "account": "existing",
        "method": "email",
        "email_hint": "s***@example.com",
    }
    r = await client.post(
        "/auth/homeowner/email/start", json={"phone": PHONE, "email": "attacker@evil.example"}
    )
    assert r.json()["sent_to"] == "s***@example.com"
    again = link_parts(r.json()["dev_link"])
    assert "p" not in again
    r = await client.post("/auth/homeowner/email/finish", json={"token": again["t"]})
    assert r.status_code == 200, r.text
    assert r.json()["needs_profile"] is True


async def test_signup_link_is_tied_to_its_phone_number(client: httpx.AsyncClient) -> None:
    parts = await email_signup(client)
    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": parts["t"], "phone": "14045550188"}
    )
    assert r.json()["error"]["code"] == "link_invalid"


async def test_links_expire(client: httpx.AsyncClient, clock: FrozenClock) -> None:
    parts = await email_signup(client)
    clock.advance(minutes=21)
    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": parts["t"], "phone": parts["p"]}
    )
    assert r.json()["error"]["code"] == "link_expired"


async def test_a_newer_link_replaces_the_older_one(client: httpx.AsyncClient) -> None:
    first = await email_signup(client)
    second = await email_signup(client)
    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": first["t"], "phone": first["p"]}
    )
    assert r.json()["error"]["code"] == "link_expired"
    r = await client.post(
        "/auth/homeowner/email/finish", json={"token": second["t"], "phone": second["p"]}
    )
    assert r.status_code == 200


async def test_authenticator_accounts_cant_be_signed_into_by_email(
    client: httpx.AsyncClient,
) -> None:
    await homeowner_login(client, PHONE, with_card=False)
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start["method"] == "authenticator"
    r = await client.post(
        "/auth/homeowner/email/start", json={"phone": PHONE, "email": "attacker@evil.example"}
    )
    assert r.json()["error"]["code"] == "use_authenticator"


async def test_an_email_used_by_another_account_cant_be_reused(client: httpx.AsyncClient) -> None:
    parts = await email_signup(client)
    await client.post(
        "/auth/homeowner/email/finish", json={"token": parts["t"], "phone": parts["p"]}
    )
    r = await client.post(
        "/auth/homeowner/email/start", json={"phone": "(404) 555-0177", "email": "sam@example.com"}
    )
    assert r.json()["error"]["code"] == "email_taken"


async def test_email_links_are_rate_limited(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        r = await client.post(
            "/auth/homeowner/email/start", json={"phone": PHONE, "email": "sam@example.com"}
        )
        assert r.status_code == 200
    r = await client.post(
        "/auth/homeowner/email/start", json={"phone": PHONE, "email": "sam@example.com"}
    )
    assert r.status_code == 429


async def test_technician_joins_and_signs_in_with_email_links(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech_id = shops["near"].tech_ids[0]
    body = (
        await client.post(
            f"/shop/technicians/{tech_id}/invite",
            headers=shop,
            json={"email": "nina@tech.example.com"},
        )
    ).json()
    token = token_from_link(body["email_link"]["dev_link"])
    claim = (
        await client.post("/auth/technician/invite/verify-email", json={"token": token})
    ).json()["claim"]
    r = await client.post(
        "/auth/technician/invite/accept",
        json={"token": token, "claim": claim, "phone": "(404) 555-0144", "email_sign_in": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["backup_codes"] == []

    # Unknown logins get the same answer, and nothing is sent.
    r = await client.post("/auth/technician/email/start", json={"login": "nobody@example.com"})
    assert r.status_code == 200 and r.json() == {"sent_to": None, "dev_link": None}

    for login in ("nina@tech.example.com", "(404) 555-0144"):
        r = await client.post("/auth/technician/email/start", json={"login": login})
        link = r.json()["dev_link"]
        assert link.startswith("http://localhost:8081/tech/email-sign-in?t=")
        r = await client.post(
            "/auth/technician/email/finish", json={"token": token_from_link(link)}
        )
        assert r.status_code == 200, r.text
        me = await client.get(
            "/tech/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
        )
        assert me.status_code == 200
    # A homeowner sign-in link can't be used as a technician one.
    parts = await email_signup(client, "other@example.com")
    r = await client.post("/auth/technician/email/finish", json={"token": parts["t"]})
    assert r.json()["error"]["code"] == "link_expired"


# --- Recovery ------------------------------------------------------------------------------
async def test_homeowner_adds_a_recovery_email_and_recovers_a_lost_authenticator(
    client: httpx.AsyncClient,
) -> None:
    headers = await homeowner_login(client, PHONE, with_card=False)
    r = await client.post("/auth/homeowner/recover", json={"phone": PHONE})
    assert r.json()["error"]["code"] == "no_recovery_email"

    r = await client.post("/me/email", headers=headers, json={"email": "Sam@Example.com"})
    assert r.status_code == 200, r.text
    parts = link_parts(r.json()["dev_link"])
    assert parts["c"] == "1"
    r = await client.post("/auth/homeowner/email/confirm", json={"token": parts["t"]})
    assert r.json()["sent_to"] == "s***@example.com"
    assert (await client.get("/me", headers=headers)).json()["email"] == "sam@example.com"
    # Still an authenticator account: the email is only for recovery.
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start["method"] == "authenticator"

    r = await client.post("/auth/homeowner/recover", json={"phone": PHONE})
    parts = link_parts(r.json()["dev_link"])
    assert parts["r"] == "1"
    r = await client.post("/auth/homeowner/recover/finish", json={"token": parts["t"]})
    assert r.status_code == 200, r.text
    # The authenticator is removed (email links from now on); old sessions are signed out.
    start = (await client.post("/auth/homeowner/start", json={"phone": PHONE})).json()
    assert start["method"] == "email"
    refresh = await client.post("/auth/refresh", json={"refresh_token": "x" * 40})
    assert refresh.status_code == 401


async def test_technician_recovers_a_lost_authenticator(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    from tests.test_technicians import join_as_technician

    shop = await shop_login(client, shops["near"], clock)
    await join_as_technician(client, shop, shops["near"].tech_ids[0])
    r = await client.post("/auth/technician/recover", json={"login": "nobody@example.com"})
    assert r.json() == {"sent_to": None, "dev_link": None}
    r = await client.post("/auth/technician/recover", json={"login": "nina@tech.example.com"})
    link = r.json()["dev_link"]
    assert "/tech/email-sign-in?r=1&t=" in link
    r = await client.post("/auth/technician/recover/finish", json={"token": link.split("t=", 1)[1]})
    assert r.status_code == 200, r.text
    # Now an email-link account.
    r = await client.post("/auth/technician/email/start", json={"login": "nina@tech.example.com"})
    assert r.json()["dev_link"]


async def test_shop_resets_a_forgotten_password(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    from tests.conftest import STRONG_PASSWORD

    r = await client.post("/auth/shop/forgot-password", json={"email": "nobody@example.com"})
    assert r.json() == {"sent_to": None, "dev_link": None}
    email = shops["near"].email
    r = await client.post("/auth/shop/forgot-password", json={"email": email.upper()})
    link = r.json()["dev_link"]
    assert link.startswith("http://localhost:5173/reset-password?t=")
    token = token_from_link(link)
    r = await client.post(
        "/auth/shop/reset-password", json={"token": token, "password": "password"}
    )
    assert r.status_code == 400  # weak passwords are refused (and the link still works)
    r = await client.post(
        "/auth/shop/reset-password", json={"token": token, "password": "Brand-New-Coil-88!"}
    )
    assert r.status_code == 204, r.text
    r = await client.post(
        "/auth/shop/reset-password", json={"token": token, "password": "Brand-New-Coil-88!"}
    )
    assert r.json()["error"]["code"] == "link_expired"
    r = await client.post("/auth/shop/login", json={"email": email, "password": STRONG_PASSWORD})
    assert r.status_code == 401
    r = await client.post(
        "/auth/shop/login", json={"email": email, "password": "Brand-New-Coil-88!"}
    )
    assert r.status_code == 200
    assert r.json()["step"] != "done"  # 2-step verification still required
