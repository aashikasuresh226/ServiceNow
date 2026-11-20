"""Photos kept in the database (no metadata/GPS), the technician's actual fix, and the
training-data export for the admin."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace

import httpx
from PIL import Image
from sqlalchemy import text

from app.container import Container
from app.core.clock import FrozenClock
from app.integrations.storage import DatabaseFileStorage
from app.main import create_app
from tests.conftest import ADMIN_KEY, SeededShop, homeowner_login, shop_login


def photo_with_location() -> bytes:
    image = Image.new("RGB", (3000, 2000), "gray")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {1: "N", 2: (33.0, 45.0, 0.0)}  # GPS: latitude
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


async def test_photos_in_the_database_fix_recorded_and_exported(
    container: Container, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    db = replace(container, storage=DatabaseFileStorage(container.session_factory))
    app = create_app(db.settings, db)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1"
    ) as client:
        home = await homeowner_login(client)
        shop = await shop_login(client, shops["near"], clock)
        r = await client.post(
            "/requests",
            headers=home,
            json={"symptoms": ["no_cooling"], "description": "Outdoor fan not spinning"},
        )
        rid = r.json()["id"]
        r = await client.post(
            f"/requests/{rid}/photos",
            headers=home,
            files={"file": ("unit.jpg", photo_with_location(), "image/jpeg")},
        )
        assert r.status_code == 200, r.text
        await client.post(f"/requests/{rid}/analyze", headers=home)
        await client.post(f"/requests/{rid}/match", headers=home)
        await client.post(f"/requests/{rid}/confirm", headers=home)
        for step in ("accept", "en-route", "on-site"):
            await client.post(f"/shop/jobs/{rid}/{step}", headers=shop, json={})
        bad = await client.post(
            f"/shop/jobs/{rid}/quote",
            headers=shop,
            json={"final_price_cents": 24_500, "notes": "x", "actual_issue": "gremlins"},
        )
        assert bad.status_code == 400
        r = await client.post(
            f"/shop/jobs/{rid}/quote",
            headers=shop,
            json={
                "final_price_cents": 24_500,
                "notes": "Replaced the condenser fan motor",
                "actual_issue": "fan_motor",
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["quote"]["actual_issue"] == "fan_motor"
        await client.post(f"/requests/{rid}/approve-quote", headers=home)
        await client.post(f"/shop/jobs/{rid}/complete", headers=shop)

        # Stored in the database, encrypted; resized and without metadata (no GPS).
        async with db.engine.connect() as conn:
            row = (await conn.execute(text("SELECT data, size_bytes FROM stored_files"))).one()
        assert bytes(row[0]).startswith(b"enc1:")
        [key] = [p for p in (await client.get(f"/requests/{rid}", headers=home)).json()["photos"]]
        async with db.session_factory() as session:
            photo = (await session.execute(text("SELECT storage_key FROM request_photos"))).scalar()
        stored = await db.storage.read(str(photo))
        with Image.open(io.BytesIO(stored)) as image:
            assert max(image.size) == 1600
            assert not image.getexif()  # Make and GPS are gone
        assert key  # the app still lists the photo

        assert (await client.get("/admin/training-data")).status_code == 401
        r = await client.get("/admin/training-data", headers={"X-Admin-Key": ADMIN_KEY})
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        archive = zipfile.ZipFile(io.BytesIO(r.content))
        [line] = archive.read("labels.jsonl").decode().splitlines()
        job = json.loads(line)
        assert job["actual"] == {
            "issue": "fan_motor",
            "fix": "Replaced the condenser fan motor",
            "final_price_cents": 24_500,
        }
        assert job["ai"]["primary_issue"] and job["reported"]["symptoms"] == ["no_cooling"]
        assert job["market"] == "Atlanta, GA"
        [image_name] = job["images"]
        assert archive.read(image_name) == stored
        everything = r.content.decode("latin-1")
        assert "Jordan" not in everything and "Peachtree" not in everything
        assert "+1404" not in everything
