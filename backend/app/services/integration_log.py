"""A visible record of what we sent to each shop's Housecall Pro (portal: How you take jobs)."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.models import IntegrationLog

KEEP = timedelta(days=30)


def record(
    session: AsyncSession, shop_id: uuid.UUID, action: str, ok: bool, detail: str | None = None
) -> None:
    session.add(
        IntegrationLog(
            shop_id=shop_id, action=action[:200], ok=ok, detail=(detail or None) and detail[:400]
        )
    )


async def recent(
    session: AsyncSession, shop_id: uuid.UUID, limit: int = 40
) -> list[IntegrationLog]:
    rows = await session.scalars(
        select(IntegrationLog)
        .where(IntegrationLog.shop_id == shop_id)
        .order_by(IntegrationLog.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def purge(session: AsyncSession, container: Container) -> int:
    result = await session.execute(
        delete(IntegrationLog).where(IntegrationLog.created_at < container.clock.now() - KEEP)
    )
    return int(getattr(result, "rowcount", 0) or 0)
