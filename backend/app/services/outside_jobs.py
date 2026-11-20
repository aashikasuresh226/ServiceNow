"""Reading the jobs copied from the shop's own software (see ExternalJobService.import_shop)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import NotFound
from app.models import ExternalJob, ExternalJobEvent, ShopCustomer, Technician

TECH_PAST = timedelta(hours=12)
TECH_AHEAD = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class OutsideJob:
    job: ExternalJob
    technician_name: str | None
    customer_uses_app: bool
    unsent: int = 0  # actions from our app still waiting to reach Housecall Pro


def _open(job: ExternalJob) -> bool:
    return "cancel" not in job.work_status and not job.work_status.startswith("complete")


class OutsideJobService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def _wrap(self, rows: list[ExternalJob]) -> list[OutsideJob]:
        tech_ids = {r.technician_id for r in rows if r.technician_id}
        names = (
            {
                t.id: t.name
                for t in await self.s.scalars(select(Technician).where(Technician.id.in_(tech_ids)))
            }
            if tech_ids
            else {}
        )
        customer_ids = {r.customer_id for r in rows if r.customer_id}
        joined = (
            set(
                await self.s.scalars(
                    select(ShopCustomer.id).where(
                        ShopCustomer.id.in_(customer_ids), ShopCustomer.homeowner_id.is_not(None)
                    )
                )
            )
            if customer_ids
            else set()
        )
        job_ids = [r.id for r in rows]
        unsent: dict[uuid.UUID, int] = {}
        if job_ids:
            counted = await self.s.execute(
                select(ExternalJobEvent.job_id, func.count())
                .where(ExternalJobEvent.job_id.in_(job_ids), ExternalJobEvent.sent_at.is_(None))
                .group_by(ExternalJobEvent.job_id)
            )
            unsent = {job_id: int(count) for job_id, count in counted.all()}
        return [
            OutsideJob(
                r,
                names.get(r.technician_id) if r.technician_id else None,
                r.customer_id in joined,
                int(unsent.get(r.id, 0)),
            )
            for r in rows
        ]

    async def for_technician(self, tech: Technician) -> list[OutsideJob]:
        """The technician's own upcoming Housecall Pro jobs (not canceled or finished)."""
        now = self.c.clock.now()
        rows = list(
            await self.s.scalars(
                select(ExternalJob)
                .where(
                    ExternalJob.technician_id == tech.id,
                    ExternalJob.starts_at >= now - TECH_PAST,
                    ExternalJob.starts_at <= now + TECH_AHEAD,
                )
                .order_by(ExternalJob.starts_at)
            )
        )
        return await self._wrap([r for r in rows if _open(r)])

    async def for_shop(
        self, shop_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[OutsideJob]:
        """Scheduled in [start, end), plus every unscheduled job."""
        rows = list(
            await self.s.scalars(
                select(ExternalJob)
                .where(ExternalJob.shop_id == shop_id)
                .order_by(ExternalJob.starts_at.nulls_first())
            )
        )
        rows = [r for r in rows if r.starts_at is None or start <= r.starts_at < end]
        return await self._wrap(rows)

    async def get_for_technician(self, tech: Technician, job_id: uuid.UUID) -> OutsideJob:
        for item in await self.for_technician(tech):
            if item.job.id == job_id:
                return item
        raise NotFound("Job not found")
