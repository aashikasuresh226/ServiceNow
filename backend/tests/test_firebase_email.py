"""Verification emails through Firebase (Identity Toolkit REST), against a fake Firebase."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.container import Container
from app.core.errors import AppError
from app.integrations.firebase_email import FirebaseEmailSender
from app.main import create_app
from tests.conftest import STRONG_PASSWORD


class FakeFirebase:
    """Just enough of accounts:signUp / signInWithPassword / sendOobCode / lookup."""

    def __init__(self, *, email_password_on: bool = True) -> None:
        self.users: dict[str, dict[str, Any]] = {}  # email -> {password, verified}
        self.sent: list[dict[str, str]] = []  # emails Firebase would send
        self.email_password_on = email_password_on
        self.keys: set[str] = set()

    def open_email(self, email: str) -> str:
        """The person clicks the link: Firebase marks the address verified, returns our URL."""
        self.users[email]["verified"] = True
        return [m for m in self.sent if m["email"] == email][-1]["continue_url"]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.keys.add(request.url.params["key"])
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)

        def error(code: str) -> httpx.Response:
            return httpx.Response(400, json={"error": {"code": 400, "message": code}})

        if method == "accounts:signUp":
            if not self.email_password_on:
                return error("OPERATION_NOT_ALLOWED")
            if body["email"] in self.users:
                return error("EMAIL_EXISTS")
            self.users[body["email"]] = {"password": body["password"], "verified": False}
            return httpx.Response(200, json={"idToken": f"id:{body['email']}"})
        if method == "accounts:signInWithPassword":
            user = self.users.get(body["email"])
            if user is None:
                return error("EMAIL_NOT_FOUND")
            if user["password"] != body["password"]:
                return error("INVALID_LOGIN_CREDENTIALS")
            return httpx.Response(200, json={"idToken": f"id:{body['email']}"})
        if method == "accounts:sendOobCode":
            assert body["requestType"] == "VERIFY_EMAIL"
            email = body["idToken"].removeprefix("id:")
            self.sent.append({"email": email, "continue_url": body["continueUrl"]})
            return httpx.Response(200, json={"email": email})
        if method == "accounts:lookup":
            email = body["idToken"].removeprefix("id:")
            return httpx.Response(
                200,
                json={"users": [{"email": email, "emailVerified": self.users[email]["verified"]}]},
            )
        return httpx.Response(404)


def sender(fake: FakeFirebase, secret: str = "s" * 44) -> FirebaseEmailSender:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return FirebaseEmailSender(api_key="web-key", secret=secret, http=http)


async def test_sender_creates_user_sends_and_checks() -> None:
    fake = FakeFirebase()
    firebase = sender(fake)
    assert await firebase.is_verified("a@example.com") is False  # no user yet
    await firebase.send_verification("a@example.com", "http://x/verify?t=1")
    await firebase.send_verification("a@example.com", "http://x/verify?t=2")  # resend reuses user
    assert [m["continue_url"] for m in fake.sent] == ["http://x/verify?t=1", "http://x/verify?t=2"]
    assert fake.keys == {"web-key"}
    assert await firebase.is_verified("a@example.com") is False
    fake.open_email("a@example.com")
    assert await firebase.is_verified("a@example.com") is True


async def test_sender_explains_setup_problems() -> None:
    with pytest.raises(AppError, match="Email/Password"):
        await sender(FakeFirebase(email_password_on=False)).send_verification("a@x.com", "u")
    fake = FakeFirebase()
    fake.users["old@x.com"] = {"password": "made-by-an-older-setup", "verified": False}
    with pytest.raises(AppError, match="Authentication > Users") as info:
        await sender(fake).send_verification("old@x.com", "u")
    assert info.value.code == "firebase_user_exists"


@pytest.fixture
async def firebase_client(container: Container) -> Any:
    fake = FakeFirebase()
    wired = replace(
        container, firebase=sender(fake, container.settings.encryption_key.get_secret_value())
    )
    app = create_app(wired.settings, wired)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1"
    ) as http:
        yield http, fake


async def test_shop_signup_with_firebase(firebase_client: Any) -> None:
    client, fake = firebase_client
    r = await client.post(
        "/auth/shop/signup",
        json={
            "email": "owner@fireshop.example.com",
            "password": STRONG_PASSWORD,
            "shop_name": "Fire HVAC",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # Firebase sent the email; the link (with its token) is never handed to the browser.
    assert body["email_link"] == {
        "email": "owner@fireshop.example.com",
        "continue_url": "",
        "delivery": "firebase",
        "dev_link": None,
    }
    assert [m["email"] for m in fake.sent] == ["owner@fireshop.example.com"]
    link = fake.sent[0]["continue_url"]
    token = parse_qs(urlparse(link).query)["t"][0]
    # The token alone isn't enough: Firebase must say the address is verified.
    r = await client.post("/auth/shop/verify-email", json={"token": token})
    assert r.status_code == 401 and r.json()["error"]["code"] == "email_unverified"

    fake.open_email("owner@fireshop.example.com")
    setup = {"Authorization": f"Bearer {body['token']}"}
    # The waiting sign-up page notices on its own (e.g. the email was opened on a phone).
    status = (await client.get("/auth/shop/setup-status", headers=setup)).json()
    assert status["step"] != "verify_email"
