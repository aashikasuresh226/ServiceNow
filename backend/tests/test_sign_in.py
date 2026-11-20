"""Sign in with Google (real ID-token verification against a test key set) and
the homeowner phone-number checks."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

import httpx
import jwt
import pyotp
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.container import Container
from app.core.clock import FrozenClock
from app.integrations.google_auth import GoogleTokenVerifier
from app.main import create_app

CLIENT_ID = "test-client.apps.googleusercontent.com"
KID = "test-key-1"


@pytest.fixture(scope="module")
def google_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks(key: rsa.RSAPrivateKey) -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


def google_token(key: rsa.RSAPrivateKey, nonce: str | None, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "1234567890",
        "email": "Jordan.Lee@gmail.com",
        "email_verified": True,
        "name": "Jordan Lee",
        "iat": now,
        "exp": now + 3600,
        "nonce": nonce,
    }
    claims.update(overrides)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
async def google_client(container: Container, google_key: rsa.RSAPrivateKey) -> httpx.AsyncClient:
    jwks = _jwks(google_key)
    google_http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=jwks, headers={"cache-control": "public, max-age=3600"}
            )
        )
    )
    built = replace(container, google=GoogleTokenVerifier(client_ids=[CLIENT_ID], http=google_http))
    app = create_app(built.settings, built)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/v1")


async def _nonce(client: httpx.AsyncClient) -> str:
    r = await client.post("/auth/google/nonce")
    assert r.status_code == 200, r.text
    return str(r.json()["nonce"])


async def test_google_homeowner_sign_in_then_add_phone(
    google_client: httpx.AsyncClient, google_key: rsa.RSAPrivateKey
) -> None:
    async with google_client as client:
        token = google_token(google_key, await _nonce(client))
        r = await client.post("/auth/homeowner/google", json={"id_token": token})
        assert r.status_code == 200, r.text
        assert r.json()["needs_profile"] is True
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        me = (await client.get("/me", headers=auth)).json()
        assert me["email"] == "jordan.lee@gmail.com" and me["name"] == "Jordan Lee"
        assert me["phone"] is None

        # The nonce is single-use: replaying the same token fails.
        r = await client.post("/auth/homeowner/google", json={"id_token": token})
        assert r.status_code == 401

        # Add a mobile number (for the company to call; nothing is texted).
        r = await client.post("/me/phone", headers=auth, json={"phone": "4045550150"})
        assert r.status_code == 200 and r.json()["phone"] == "+14045550150"

        # Signing in with Google again finds the same account.
        token = google_token(google_key, await _nonce(client))
        r = await client.post("/auth/homeowner/google", json={"id_token": token})
        auth = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await client.get("/me", headers=auth)).json()["id"] == me["id"]


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"aud": "someone-elses-client"}, "wrong audience"),
        ({"iss": "https://evil.example.com"}, "wrong issuer"),
        ({"email_verified": False}, "unverified email"),
        ({"exp": int(time.time()) - 3600, "iat": int(time.time()) - 7200}, "expired"),
    ],
)
async def test_google_rejects_bad_tokens(
    google_client: httpx.AsyncClient,
    google_key: rsa.RSAPrivateKey,
    overrides: dict[str, Any],
    why: str,
) -> None:
    async with google_client as client:
        token = google_token(google_key, await _nonce(client), **overrides)
        r = await client.post("/auth/homeowner/google", json={"id_token": token})
        assert r.status_code == 401, why


async def test_google_rejects_unknown_nonce_and_forged_signature(
    google_client: httpx.AsyncClient, google_key: rsa.RSAPrivateKey
) -> None:
    async with google_client as client:
        r = await client.post(
            "/auth/homeowner/google",
            json={"id_token": google_token(google_key, "made-up-nonce")},
        )
        assert r.status_code == 401
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = google_token(other_key, await _nonce(client))
        r = await client.post("/auth/homeowner/google", json={"id_token": forged})
        assert r.status_code == 401


async def test_google_shop_sign_up_still_requires_authenticator(
    google_client: httpx.AsyncClient, google_key: rsa.RSAPrivateKey, clock: FrozenClock
) -> None:
    async with google_client as client:
        # No account yet and no shop name: tell the portal to show "create account".
        token = google_token(google_key, await _nonce(client), sub="shop-owner-1")
        r = await client.post("/auth/shop/google", json={"id_token": token})
        assert r.status_code == 404 and r.json()["error"]["code"] == "no_shop_account"

        token = google_token(google_key, await _nonce(client), sub="shop-owner-1")
        r = await client.post(
            "/auth/shop/google", json={"id_token": token, "shop_name": "Peach Air"}
        )
        assert r.status_code == 200 and r.json()["step"] == "mfa_setup"
        setup = {"Authorization": f"Bearer {r.json()['token']}"}
        assert (await client.get("/shop/me", headers=setup)).status_code == 401
        secret = (await client.post("/auth/shop/mfa/enroll", headers=setup)).json()["secret"]
        r = await client.post(
            "/auth/shop/mfa/activate",
            headers=setup,
            json={"code": pyotp.TOTP(secret).at(clock.now())},
        )
        shop = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await client.get("/shop/me", headers=shop)).json()["shop"]["name"] == "Peach Air"

        # Next time: Google, then the authenticator code.
        token = google_token(google_key, await _nonce(client), sub="shop-owner-1")
        r = await client.post("/auth/shop/google", json={"id_token": token})
        assert r.json()["step"] == "mfa"
        # A Google-only shop account has no password to guess.
        r = await client.post(
            "/auth/shop/login", json={"email": "jordan.lee@gmail.com", "password": ""}
        )
        assert r.status_code in (401, 422)


async def test_google_disabled_without_client_id(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/google/nonce")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "google_not_configured"


async def test_only_us_numbers_and_per_ip_limit(client: httpx.AsyncClient) -> None:
    r = await client.post("/auth/homeowner/start", json={"phone": "+44 20 7930 4832"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "phone_not_supported"
    statuses = []
    for i in range(22):
        r = await client.post("/auth/homeowner/start", json={"phone": f"40455502{i:02d}"})
        statuses.append(r.status_code)
    assert statuses[:19] == [200] * 19  # 20 starts per IP per hour (the UK number counted)
    assert statuses[-1] == 429
