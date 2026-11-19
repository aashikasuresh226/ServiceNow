"""Authentication and authorization rules."""

from __future__ import annotations

import httpx
import pyotp

from app.container import Container
from app.core.clock import FrozenClock
from app.integrations.payments.fake import FakePaymentGateway
from tests.conftest import (
    SHOP_PASSWORD,
    STRONG_PASSWORD,
    SeededShop,
    analyzed_request,
    homeowner_login,
    signup_shop,
    token_from_link,
)


async def test_wrong_otp_then_lockout(client: httpx.AsyncClient) -> None:
    phone = "4045550111"
    await client.post("/auth/homeowner/otp/start", json={"phone": phone})
    for _ in range(5):
        r = await client.post("/auth/homeowner/otp/verify", json={"phone": phone, "code": "000000"})
        assert r.json()["error"]["code"] in {"otp_invalid"}
    r = await client.post("/auth/homeowner/otp/verify", json={"phone": phone, "code": "000000"})
    assert r.json()["error"]["code"] == "otp_locked"


async def test_otp_resend_cooldown(client: httpx.AsyncClient, clock: FrozenClock) -> None:
    await client.post("/auth/homeowner/otp/start", json={"phone": "4045550112"})
    r = await client.post("/auth/homeowner/otp/start", json={"phone": "4045550112"})
    assert r.status_code == 429
    clock.advance(seconds=31)
    r = await client.post("/auth/homeowner/otp/start", json={"phone": "4045550112"})
    assert r.status_code == 200


async def test_refresh_rotation_and_reuse_detection(client: httpx.AsyncClient) -> None:
    phone = "4045550113"
    code = (await client.post("/auth/homeowner/otp/start", json={"phone": phone})).json()
    tokens = (
        await client.post(
            "/auth/homeowner/otp/verify", json={"phone": phone, "code": code["dev_code"]}
        )
    ).json()
    first = tokens["refresh_token"]
    rotated = (await client.post("/auth/refresh", json={"refresh_token": first})).json()
    assert rotated["refresh_token"] != first
    # Reusing the old token is treated as theft: the whole session family is revoked.
    assert (await client.post("/auth/refresh", json={"refresh_token": first})).status_code == 401
    r = await client.post("/auth/refresh", json={"refresh_token": rotated["refresh_token"]})
    assert r.status_code == 401


async def test_homeowners_cannot_see_each_others_requests(
    client: httpx.AsyncClient, shops: dict[str, SeededShop]
) -> None:
    alice = await homeowner_login(client, "4045550120", with_card=False)
    bob = await homeowner_login(client, "4045550121", with_card=False)
    rid = (await analyzed_request(client, alice))["id"]
    assert (await client.get(f"/requests/{rid}", headers=bob)).status_code == 404


async def test_shop_signup_requires_email_then_2step_before_access(
    client: httpx.AsyncClient, clock: FrozenClock
) -> None:
    r = await client.post(
        "/auth/shop/signup",
        json={
            "email": "Owner@NewShop.example.com",
            "password": STRONG_PASSWORD,
            "shop_name": "New",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["step"] == "verify_email"
    assert body["email_link"]["delivery"] == "development"
    setup_token = {"Authorization": f"Bearer {body['token']}"}
    # The setup token can't reach shop endpoints.
    assert (await client.get("/shop/me", headers=setup_token)).status_code == 401
    # Still waiting for the link to be opened.
    status = (await client.get("/auth/shop/setup-status", headers=setup_token)).json()
    assert status["step"] == "verify_email"
    # 2-step can be enrolled, but the account stays locked until the email is proven.
    enrolled = (await client.post("/auth/shop/mfa/enroll", headers=setup_token)).json()
    code = pyotp.TOTP(enrolled["secret"]).at(clock.now())
    tokens = (
        await client.post("/auth/shop/mfa/activate", headers=setup_token, json={"code": code})
    ).json()
    locked = await client.get(
        "/shop/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert locked.status_code == 403 and locked.json()["error"]["code"] == "email_unverified"

    token = token_from_link(body["email_link"]["dev_link"])
    info = (await client.get(f"/auth/email-proof/{token}")).json()
    assert info == {"email": "owner@newshop.example.com", "purpose": "shop_email"}
    assert (await client.post("/auth/shop/verify-email", json={"token": token})).status_code == 204
    # The link works once.
    assert (await client.post("/auth/shop/verify-email", json={"token": token})).status_code == 404
    me = await client.get("/shop/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user_email"] == "owner@newshop.example.com"


async def test_password_rules(client: httpx.AsyncClient) -> None:
    for weak, why in (
        ("Short1!", "8 characters"),
        ("alllowercase1!", "capital"),
        ("NoNumbers!!", "number"),
        ("NoSymbols123", "symbol"),
        ("Password1!", "too common"),
        ("P@ssw0rd99", "too common"),
    ):
        r = await client.post(
            "/auth/shop/signup",
            json={"email": "weak@shop.example.com", "password": weak, "shop_name": "Weak Air"},
        )
        assert r.status_code == 400, weak
        assert why in r.json()["error"]["message"], (weak, r.json())
    r = await client.post(
        "/auth/shop/signup",
        json={"email": "someone@gmial.com", "password": STRONG_PASSWORD, "shop_name": "Typo Air"},
    )
    assert r.json()["error"]["code"] == "email_typo"
    assert "gmail.com" in r.json()["error"]["message"]


async def test_shop_login_rejects_bad_password_and_code(
    client: httpx.AsyncClient, shops: dict[str, SeededShop]
) -> None:
    r = await client.post(
        "/auth/shop/login", json={"email": "near@shop.example.com", "password": "wrong-password"}
    )
    assert r.status_code == 401
    r = await client.post(
        "/auth/shop/login", json={"email": "near@shop.example.com", "password": SHOP_PASSWORD}
    )
    r = await client.post(
        "/auth/shop/login/mfa", json={"token": r.json()["token"], "code": "000000"}
    )
    assert r.status_code == 401


async def test_homeowner_token_cannot_call_shop_api(client: httpx.AsyncClient) -> None:
    home = await homeowner_login(client, with_card=False)
    assert (await client.get("/shop/me", headers=home)).status_code == 403


async def test_go_live_requires_payouts(
    client: httpx.AsyncClient, clock: FrozenClock, container: Container
) -> None:
    shop = await signup_shop(client, clock, "x@shop.example.com", "X Air")
    r = await client.put("/shop/live", headers=shop, json={"is_live": True})
    assert r.status_code == 409
    assert "payout" in r.json()["error"]["message"]

    link = (await client.post("/shop/payouts/onboarding-link", headers=shop)).json()["url"]
    account_id = link.rsplit("/", 1)[1]
    # Stand-in for finishing Stripe's hosted onboarding.
    assert isinstance(container.payments, FakePaymentGateway)
    container.payments.complete_onboarding(account_id)
    me = (await client.post("/shop/payouts/refresh", headers=shop)).json()
    assert me["shop"]["payouts_enabled"] is True
    await client.patch("/shop/me", headers=shop, json={"address": "1 Main St, Atlanta, GA 30303"})
    await client.post(
        "/shop/technicians",
        headers=shop,
        json={
            "name": "Sam",
            "equipment_types": ["central_ac"],
            "working_hours": {"mon": [["08:00", "17:00"]]},
        },
    )
    r = await client.put("/shop/live", headers=shop, json={"is_live": True})
    assert r.status_code == 200 and r.json()["shop"]["is_live"] is True


async def test_validation_errors_use_standard_shape(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/auth/shop/signup",
        json={"email": "not-an-email", "password": "", "shop_name": "Ok Shop"},
    )
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert set(error["fields"]) == {"email", "password"}
