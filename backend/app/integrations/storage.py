"""Photo storage. Local disk for dev/demo; swap for S3/GCS behind the same interface."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Protocol

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
        await asyncio.to_thread(self._path(key).write_bytes, data)
        return key

    async def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise NotFound("File not found")
        return await asyncio.to_thread(path.read_bytes)


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
