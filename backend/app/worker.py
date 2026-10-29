"""Background loop: expire proposals/offers, match the waitlist, sync schedules.

Each step runs in its own transaction so one failure can't block the others.
Run standalone in production:  python -m app.worker
In dev/demo it runs inside the API process (HVAC_RUN_WORKER_IN_PROCESS=true).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.container import Container, build_container
from app.core.config import get_settings
from app.domain.enums import SchedulingProvider
from app.models import Shop
from app.services.availability_service import AvailabilityService
from app.services.matching_service import MatchingService

log = logging.getLogger("app.worker")


async def _run_step(
    container: Container, name: str, step: Callable[[AsyncSession], Awaitable[object]]
) -> None:
    async with container.session_factory() as session:
        try:
            result = await step(session)
            await session.commit()
            if result:
                log.info("%s: %s", name, result)
        except StaleDataError:
            # Someone else (e.g. the homeowner) changed the request meanwhile; retry next tick.
            await session.rollback()
            log.info("%s: skipped a request that changed concurrently", name)
        except Exception:
            await session.rollback()
            log.exception("Worker step %s failed", name)


async def _sync_due_shops(container: Container, session: AsyncSession) -> int:
    now = container.clock.now()
    interval = timedelta(seconds=container.settings.scheduling_sync_interval_seconds)
    shops = list(
        await session.scalars(
            select(Shop).where(Shop.scheduling_provider != SchedulingProvider.NONE.value)
        )
    )
    synced = 0
    service = AvailabilityService(session, container)
    for shop in shops:
        if shop.scheduling_last_synced_at and now - shop.scheduling_last_synced_at < interval:
            continue
        await service.sync_shop(shop)
        synced += 1
    return synced


async def tick(container: Container) -> None:
    await _run_step(
        container, "expire_proposals", lambda s: MatchingService(s, container).expire_proposals()
    )
    await _run_step(
        container, "expire_offers", lambda s: MatchingService(s, container).expire_offers()
    )
    await _run_step(container, "sync_schedules", lambda s: _sync_due_shops(container, s))
    await _run_step(
        container, "process_waitlist", lambda s: MatchingService(s, container).process_waitlist()
    )


async def run_forever(container: Container, stop: asyncio.Event | None = None) -> None:
    stop = stop or asyncio.Event()
    log.info("Worker started (tick every %ss)", container.settings.worker_tick_seconds)
    while not stop.is_set():
        await tick(container)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=container.settings.worker_tick_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    container = build_container(get_settings())

    async def _main() -> None:
        try:
            await run_forever(container)
        finally:
            await container.aclose()

    asyncio.run(_main())


if __name__ == "__main__":
    main()
