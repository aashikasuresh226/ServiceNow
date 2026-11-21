"""Account settings: photos and logos, shop password change, technician phone."""

from __future__ import annotations

import io

import httpx
from PIL import Image

from app.core.clock import FrozenClock
from tests.conftest import SHOP_PASSWORD, SeededShop, homeowner_login, shop_login
from tests.test_technicians import join_as_technician


def image_bytes(fmt: str = "JPEG", size: tuple[int, int] = (900, 600)) -> bytes:
    out = io.BytesIO()
    mode = "RGBA" if fmt == "PNG" else "RGB"
    Image.new(mode, size, (200, 80, 40, 128) if mode == "RGBA" else (200, 80, 40)).save(out, fmt)
    return out.getvalue()


def media_path(url: str) -> str:
    return url.split("/v1", 1)[1]


async def test_homeowner_profile_photo(client: httpx.AsyncClient) -> None:
    headers = await homeowner_login(client, with_card=False)
    r = await client.post(
        "/me/photo", headers=headers, files={"file": ("me.jpg", image_bytes(), "image/jpeg")}
    )
    assert r.status_code == 200, r.text
    url = r.json()["photo_url"]
    assert "/v1/media/" in url and url.endswith(".jpg")
    served = await client.get(media_path(url))
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(served.content)) as img:
        assert img.size == (512, 512)  # square crop
        assert not img.getexif()  # no metadata
    r = await client.post(
        "/me/photo", headers=headers, files={"file": ("x.txt", b"not an image", "image/jpeg")}
    )
    assert r.json()["error"]["code"] == "image_type"
    r = await client.delete("/me/photo", headers=headers)
    assert r.json()["photo_url"] is None
    assert (await client.get(media_path(url))).status_code == 404  # no longer served


async def test_media_only_serves_photos_and_logos(client: httpx.AsyncClient) -> None:
    assert (await client.get("/media/../../etc/passwd")).status_code == 404
    assert (await client.get("/media/" + "a" * 32 + ".jpg")).status_code == 404


async def test_shop_logo_password_and_name(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    r = await client.post(
        "/shop/logo", headers=shop, files={"file": ("logo.png", image_bytes("PNG"), "image/png")}
    )
    assert r.status_code == 200, r.text
    logo = r.json()["shop"]["logo_url"]
    served = await client.get(media_path(logo))
    with Image.open(io.BytesIO(served.content)) as img:
        assert img.format == "PNG" and img.mode == "RGBA" and max(img.size) == 512

    r = await client.patch("/shop/account", headers=shop, json={"name": "Maria Ponce"})
    assert r.json()["user_name"] == "Maria Ponce" and r.json()["has_password"] is True

    r = await client.post(
        "/shop/account/password",
        headers=shop,
        json={"current_password": "wrong", "new_password": "Brand-New-Coil-88!"},
    )
    assert r.json()["error"]["code"] == "bad_password"
    r = await client.post(
        "/shop/account/password",
        headers=shop,
        json={"current_password": SHOP_PASSWORD, "new_password": SHOP_PASSWORD},
    )
    assert r.json()["error"]["code"] == "same_password"
    r = await client.post(
        "/shop/account/password",
        headers=shop,
        json={"current_password": SHOP_PASSWORD, "new_password": "Brand-New-Coil-88!"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["refresh_token"]
    email = shops["near"].email
    r = await client.post("/auth/shop/login", json={"email": email, "password": SHOP_PASSWORD})
    assert r.status_code == 401
    r = await client.post(
        "/auth/shop/login", json={"email": email, "password": "Brand-New-Coil-88!"}
    )
    assert r.status_code == 200


async def test_technician_photo_phone_and_customer_sees_them(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    tech = await join_as_technician(client, shop, shops["near"].tech_ids[0])
    r = await client.post(
        "/tech/me/photo", headers=tech, files={"file": ("me.jpg", image_bytes(), "image/jpeg")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["photo_url"] and r.json()["sign_in"] == "authenticator"
    r = await client.patch("/tech/me", headers=tech, json={"phone": "(404) 555-0166"})
    assert r.json()["phone"] == "+14045550166"
    r = await client.patch("/tech/me", headers=tech, json={"phone": "123"})
    assert r.status_code == 400
