"""Photo storage: in the database (HVAC_STORAGE_BACKEND=database, for hosts like Render's
free plan whose disk is wiped on restart) or on local disk (development).

Either way files are encrypted with HVAC_ENCRYPTION_KEY (customer photos can show the
home and its address), and decrypted only when served through a signed link. Photos are
re-saved before storing (normalize_photo): shrunk to 1600 px and stripped of metadata,
which removes the GPS location phones put in photos."""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import fieldcrypt
from app.core.errors import NotFound

EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


class FileStorage(Protocol):
    async def save(self, data: bytes, content_type: str) -> str: ...

    async def read(self, key: str) -> bytes: ...


class LocalFileStorage:
    def __init__(self, root: str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if not path.is_relative_to(self._root):  # keys are generated, but never trust input
            raise NotFound("File not found")
        return path

    async def save(self, data: bytes, content_type: str) -> str:
        key = f"{uuid.uuid4().hex}.{EXTENSIONS.get(content_type, 'bin')}"
        await asyncio.to_thread(self._path(key).write_bytes, fieldcrypt.encrypt_bytes(data))
        return key

    async def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFound("File not found")
        return fieldcrypt.decrypt_bytes(await asyncio.to_thread(path.read_bytes))


class DatabaseFileStorage:
    """Encrypted bytes in the stored_files table (Postgres bytea)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def save(self, data: bytes, content_type: str) -> str:
        from app.models import StoredFile  # models import this module's helpers

        key = f"{uuid.uuid4().hex}.{EXTENSIONS.get(content_type, 'bin')}"
        async with self._sessions() as session:
            session.add(
                StoredFile(
                    key=key,
                    content_type=content_type,
                    size_bytes=len(data),
                    data=fieldcrypt.encrypt_bytes(data),
                )
            )
            await session.commit()
        return key

    async def read(self, key: str) -> bytes:
        from app.models import StoredFile

        async with self._sessions() as session:
            row = await session.get(StoredFile, key)
        if row is None:
            raise NotFound("File not found")
        return fieldcrypt.decrypt_bytes(row.data)


MAX_SIDE = 1600


def normalize_photo(data: bytes) -> tuple[bytes, str]:
    """Upright, at most 1600 px, JPEG, no metadata (no GPS). Keeps storage small."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as image:
            upright = ImageOps.exif_transpose(image)
            rgb = upright.convert("RGB")
            rgb.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=82, optimize=True)  # no exif=: dropped
    except Exception as exc:  # corrupt files, decompression bombs...
        raise ValueError("unreadable image") from exc
    return out.getvalue(), "image/jpeg"


def sniff_image_type(data: bytes) -> str | None:
    """Trust the bytes, not the client's Content-Type header."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None
