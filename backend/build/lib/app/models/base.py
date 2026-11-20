"""Mixins shared by all tables."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
