"""Profile photos (homeowners, technicians) and shop logos.

Uploads are re-encoded (upright, resized, metadata and GPS removed) and stored like
request photos (encrypted, on disk or in Postgres). They're served publicly at
/v1/media/<key>, because the other side sees them (a customer sees their technician's
photo and the company's logo); keys are random, and only files that are currently
someone's photo or logo are served.
"""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError
from app.integrations.storage import normalize_avatar, normalize_logo, sniff_image_type
from app.models import Homeowner, Shop, Technician

KEY = re.compile(r"^[0-9a-f]{32}\.(jpg|png)$")
MAX_BYTES = 8 * 1024 * 1024


async def save_image(c: Container, data: bytes, *, kind: str) -> str:
    """Returns the public URL. kind: avatar | logo."""
    if len(data) > MAX_BYTES:
        raise AppError("That image is too large (8 MB max)", code="image_too_large")
    if sniff_image_type(data) is None:
        raise AppError("Choose a JPEG, PNG, WebP or GIF image", code="image_type")
    try:
        body, content_type = normalize_logo(data) if kind == "logo" else normalize_avatar(data)
    except ValueError as exc:
        raise AppError("We couldn't read that image", code="image_unreadable") from exc
    key = await c.storage.save(body, content_type)
    return f"{c.settings.public_api_url.rstrip('/')}/v1/media/{key}"


async def in_use(session: AsyncSession, key: str) -> bool:
    if not KEY.match(key):
        return False
    pattern = f"%/v1/media/{key}"
    for column in (Shop.logo_url, Homeowner.photo_url, Technician.photo_url):
        if await session.scalar(select(column).where(or_(column.like(pattern))).limit(1)):
            return True
    return False
