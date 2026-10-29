"""Loads technician availability from the database and keeps it in sync with
each shop's scheduling software."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError
from app.domain.availability import Block, is_free_at, next_free_at, shifts_from_working_hours
from app.domain.enums import ACTIVE_JOB_STATUSES, AvailabilityKind, SchedulingProvider
from app.domain.geo import LatLng
from app.domain.matching import TechCandidate
from app.models import AvailabilityBlock, ServiceRequest, Shop, Technician

log = logging.getLogger(__name__)

PLANNING_HORIZON = timedelta(hours=24)
SYNC_WINDOW_BEFORE = timedelta(hours=12)
SYNC_WINDOW_AFTER = timedelta(hours=48)
# Coarse bounding box before exact distance checks (≈ 1 degree latitude = 111 km).
MAX_SERVICE_RADIUS_KM = 100.0


@dataclass(frozen=True, slots=True)
class TechAvailability:
    candidate: TechCandidate
    blocks: tuple[Block, ...]
    next_free_at: datetime | None


class AvailabilityService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def busy_technician_ids(self) -> set[uuid.UUID]:
        """Techs occupied by an active marketplace job."""
        rows = await self.s.scalars(
            select(ServiceRequest.technician_id).where(
                ServiceRequest.status.in_([s.value for s in ACTIVE_JOB_STATUSES]),
                ServiceRequest.technician_id.is_not(None),
            )
        )
        return {r for r in rows if r}

    async def load_tech_blocks(
        self, technicians: list[Technician], shops: dict[uuid.UUID, Shop], now: datetime
    ) -> dict[uuid.UUID, list[Block]]:
        """Synced blocks, plus SHIFT blocks from working hours where the shop's
        provider doesn't supply shifts."""
        tech_ids = [t.id for t in technicians]
        blocks: dict[uuid.UUID, list[Block]] = defaultdict(list)
        if not tech_ids:
            return blocks
        rows = await self.s.scalars(
            select(AvailabilityBlock).where(
                AvailabilityBlock.technician_id.in_(tech_ids),
                AvailabilityBlock.ends_at > now - timedelta(hours=1),
                AvailabilityBlock.starts_at < now + PLANNING_HORIZON,
            )
        )
        for row in rows:
            blocks[row.technician_id].append(
                Block(AvailabilityKind(row.kind), row.starts_at, row.ends_at)
            )
        for tech in technicians:
            shop = shops[tech.shop_id]
            if not _provider_supplies_shifts(shop) and tech.working_hours:
                local_today = now.astimezone(_tz(shop)).date()
                blocks[tech.id].extend(
                    shifts_from_working_hours(
                        tech.working_hours, shop.timezone, local_today - timedelta(days=1), 3
                    )
                )
        return blocks

    async def load_candidates(self, *, near: LatLng, now: datetime) -> list[TechAvailability]:
        """All active techs of job-ready shops near a location, with availability."""
        dlat = MAX_SERVICE_RADIUS_KM / 111.0
        dlng = dlat * 2  # generous for US latitudes
        shops = list(
            await self.s.scalars(
                select(Shop).where(
                    Shop.is_live.is_(True),
                    Shop.payouts_enabled.is_(True),
                    Shop.lat.between(near.lat - dlat, near.lat + dlat),
                    Shop.lng.between(near.lng - dlng, near.lng + dlng),
                )
            )
        )
        if not shops:
            return []
        shop_by_id = {s.id: s for s in shops}
        techs = list(
            await self.s.scalars(
                select(Technician).where(Technician.shop_id.in_(shop_by_id), Technician.is_active)
            )
        )
        blocks = await self.load_tech_blocks(techs, shop_by_id, now)
        busy = await self.busy_technician_ids()

        result: list[TechAvailability] = []
        for tech in techs:
            shop = shop_by_id[tech.shop_id]
            tech_blocks = tuple(blocks.get(tech.id, ()))
            occupied = tech.id in busy
            location = LatLng(
                tech.base_lat if tech.base_lat is not None else shop.lat or 0.0,
                tech.base_lng if tech.base_lng is not None else shop.lng or 0.0,
            )
            candidate = TechCandidate(
                technician_id=tech.id,
                shop_id=shop.id,
                location=location,
                service_radius_km=tech.service_radius_km,
                equipment_types=frozenset(tech.equipment_types),
                certifications=frozenset(tech.certifications),
                soft_skills=frozenset(tech.soft_skills),
                is_free_now=not occupied and is_free_at(tech_blocks, now),
                rating=tech.rating,
            )
            # An occupied tech frees up roughly one average job from now.
            earliest = (
                now + timedelta(minutes=self.c.settings.default_job_duration_minutes)
                if occupied
                else now
            )
            result.append(
                TechAvailability(
                    candidate, tech_blocks, next_free_at(tech_blocks, earliest, PLANNING_HORIZON)
                )
            )
        return result

    # --- Sync with ServiceTitan / Housecall Pro -------------------------------------
    async def sync_shop(self, shop: Shop) -> int:
        """Replace synced blocks in the sync window. Returns the number of blocks stored."""
        provider = SchedulingProvider(shop.scheduling_provider)
        if provider == SchedulingProvider.NONE or not shop.scheduling_credentials_encrypted:
            return 0
        credentials = json.loads(self.c.encryptor.decrypt(shop.scheduling_credentials_encrypted))
        client = self.c.scheduling(provider, credentials)
        now = self.c.clock.now()
        start, end = now - SYNC_WINDOW_BEFORE, now + SYNC_WINDOW_AFTER
        try:
            external = await client.fetch_blocks(start=start, end=end)
        except AppError as exc:
            shop.scheduling_last_error = exc.message[:500]
            log.warning("Sync failed for shop %s: %s", shop.id, exc.message)
            return 0

        techs = list(
            await self.s.scalars(
                select(Technician).where(
                    Technician.shop_id == shop.id, Technician.external_id.is_not(None)
                )
            )
        )
        by_external = {t.external_id: t for t in techs}
        await self.s.execute(
            delete(AvailabilityBlock).where(
                AvailabilityBlock.technician_id.in_([t.id for t in techs]),
                AvailabilityBlock.source == provider.value,
                AvailabilityBlock.starts_at < end,
                AvailabilityBlock.ends_at > start,
            )
        )
        stored = 0
        for block in external:
            tech = by_external.get(block.external_technician_id)
            if tech is None or block.ends_at <= block.starts_at:
                continue
            self.s.add(
                AvailabilityBlock(
                    technician_id=tech.id,
                    kind=block.kind.value,
                    starts_at=block.starts_at,
                    ends_at=block.ends_at,
                    source=provider.value,
                    label=block.label,
                )
            )
            stored += 1
        shop.scheduling_last_synced_at = now
        shop.scheduling_last_error = None
        await self.s.flush()
        return stored


def _provider_supplies_shifts(shop: Shop) -> bool:
    return shop.scheduling_provider == SchedulingProvider.SERVICETITAN.value


def _tz(shop: Shop) -> ZoneInfo:
    return ZoneInfo(shop.timezone)
