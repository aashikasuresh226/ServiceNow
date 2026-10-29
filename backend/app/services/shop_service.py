"""Shop-side setup: profile, payouts, going live, scheduling integration,
technicians and the availability board."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.domain.availability import Block, is_free_at, validate_working_hours
from app.domain.enums import (
    ACTIVE_JOB_STATUSES,
    AvailabilityKind,
    Certification,
    EquipmentType,
    RequestStatus,
    SchedulingProvider,
    SoftSkill,
)
from app.models import AvailabilityBlock, ServiceRequest, Shop, ShopUser, Technician
from app.services.availability_service import AvailabilityService
from app.services.validation import validate_options

PAYOUT_SCHEDULES = {"daily", "weekly", "manual"}
MANUAL_SOURCE = "manual"


@dataclass(frozen=True, slots=True)
class TechDay:
    technician: Technician
    blocks: list[Block]
    free_now: bool
    on_job: bool


class ShopService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    # --- Profile ---------------------------------------------------------------
    async def update_profile(
        self,
        shop: Shop,
        *,
        name: str | None,
        phone: str | None,
        address: str | None,
        timezone: str | None,
    ) -> Shop:
        if name is not None:
            if not name.strip():
                raise AppError("Shop name can't be empty", code="invalid_name")
            shop.name = name.strip()[:160]
        if phone is not None:
            shop.phone = phone.strip()[:20] or None
        if address is not None:
            geo = await self.c.geocoder.geocode(address)
            shop.address = geo.formatted_address
            shop.lat, shop.lng = geo.location.lat, geo.location.lng
        if timezone is not None:
            try:
                ZoneInfo(timezone)
            except Exception as exc:
                raise AppError("Unknown timezone", code="invalid_timezone") from exc
            shop.timezone = timezone
        return shop

    async def set_live(self, shop: Shop, live: bool) -> Shop:
        if live:
            problems = []
            if not shop.payouts_enabled:
                problems.append("finish payout setup")
            if shop.lat is None:
                problems.append("add your shop address")
            active = await self.s.scalar(
                select(func.count())
                .select_from(Technician)
                .where(Technician.shop_id == shop.id, Technician.is_active)
            )
            if not active:
                problems.append("add at least one technician")
            if problems:
                raise InvalidState(
                    "Before going live: " + ", ".join(problems), code="not_ready_to_go_live"
                )
        shop.is_live = live
        return shop

    # --- Payouts (Stripe Connect) -------------------------------------------------
    async def payout_onboarding_link(self, shop: Shop, user: ShopUser) -> str:
        if not shop.payout_account_id:
            shop.payout_account_id = await self.c.payments.create_payout_account(
                email=user.email, business_name=shop.name, reference=str(shop.id)
            )
        base = self.c.settings.public_web_url
        return await self.c.payments.payout_onboarding_link(
            account_id=shop.payout_account_id,
            return_url=f"{base}/onboarding/payouts?status=done",
            refresh_url=f"{base}/onboarding/payouts?status=retry",
        )

    async def refresh_payout_status(self, shop: Shop) -> Shop:
        if shop.payout_account_id:
            status = await self.c.payments.payout_account_status(account_id=shop.payout_account_id)
            shop.payouts_enabled = status.payouts_enabled
            if not shop.payouts_enabled:
                shop.is_live = False
        return shop

    async def set_payout_schedule(self, shop: Shop, schedule: str) -> Shop:
        if schedule not in PAYOUT_SCHEDULES:
            raise AppError("Choose daily, weekly or manual payouts", code="invalid_schedule")
        if shop.payout_account_id:
            await self.c.payments.set_payout_schedule(
                account_id=shop.payout_account_id, interval=schedule
            )
        shop.payout_schedule = schedule
        return shop

    # --- Scheduling integration ----------------------------------------------------
    async def connect_scheduling(
        self,
        shop: Shop,
        provider: SchedulingProvider,
        credentials: dict[str, Any],
        write_back: bool,
    ) -> int:
        client = self.c.scheduling(provider, credentials)  # validates required fields
        await client.verify()
        shop.scheduling_provider = provider.value
        shop.scheduling_credentials_encrypted = self.c.encryptor.encrypt(json.dumps(credentials))
        shop.write_back_jobs = write_back
        shop.scheduling_last_error = None
        imported = await self.import_technicians(shop)
        await AvailabilityService(self.s, self.c).sync_shop(shop)
        return imported

    async def disconnect_scheduling(self, shop: Shop) -> None:
        shop.scheduling_provider = SchedulingProvider.NONE.value
        shop.scheduling_credentials_encrypted = None
        shop.scheduling_last_synced_at = None

    async def import_technicians(self, shop: Shop) -> int:
        """Create technicians that exist in the scheduling software but not here yet."""
        provider = SchedulingProvider(shop.scheduling_provider)
        if provider == SchedulingProvider.NONE or not shop.scheduling_credentials_encrypted:
            raise InvalidState("Connect your scheduling software first")
        credentials = json.loads(self.c.encryptor.decrypt(shop.scheduling_credentials_encrypted))
        external = await self.c.scheduling(provider, credentials).list_technicians()
        existing = set(
            await self.s.scalars(
                select(Technician.external_id).where(
                    Technician.shop_id == shop.id, Technician.external_id.is_not(None)
                )
            )
        )
        created = 0
        for tech in external:
            if tech.external_id in existing:
                continue
            self.s.add(
                Technician(
                    shop_id=shop.id,
                    name=tech.name,
                    phone=tech.phone,
                    external_id=tech.external_id,
                    is_active=False,
                )
            )
            created += 1
        await self.s.flush()
        return created

    # --- Technicians ----------------------------------------------------------------
    async def list_technicians(self, shop: Shop) -> list[Technician]:
        rows = await self.s.scalars(
            select(Technician).where(Technician.shop_id == shop.id).order_by(Technician.name)
        )
        return list(rows)

    async def get_technician(self, shop: Shop, technician_id: uuid.UUID) -> Technician:
        tech = await self.s.get(Technician, technician_id)
        if tech is None or tech.shop_id != shop.id:
            raise NotFound("Technician not found")
        return tech

    async def save_technician(
        self, shop: Shop, tech: Technician | None, data: dict[str, Any]
    ) -> Technician:
        if tech is None:
            if not str(data.get("name") or "").strip():
                raise AppError("Technician name is required", code="invalid_name")
            tech = Technician(shop_id=shop.id, name="")
            self.s.add(tech)
        if "name" in data and data["name"] is not None:
            tech.name = str(data["name"]).strip()[:120]
        for field, enum_cls in (
            ("equipment_types", EquipmentType),
            ("certifications", Certification),
            ("soft_skills", SoftSkill),
        ):
            if data.get(field) is not None:
                setattr(
                    tech, field, validate_options(data[field], enum_cls, field.replace("_", " "))
                )
        if data.get("working_hours") is not None:
            try:
                validate_working_hours(data["working_hours"])
            except ValueError as exc:
                raise AppError(str(exc), code="invalid_hours") from exc
            tech.working_hours = data["working_hours"]
        if data.get("service_radius_km") is not None:
            radius = float(data["service_radius_km"])
            if not 1 <= radius <= 100:
                raise AppError("Service radius must be 1-100 km", code="invalid_radius")
            tech.service_radius_km = radius
        for simple in ("phone", "photo_url", "external_id"):
            if simple in data:
                setattr(tech, simple, (data[simple] or None))
        if data.get("is_active") is not None:
            tech.is_active = bool(data["is_active"])
        await self.s.flush()
        return tech

    async def mark_busy(self, tech: Technician, minutes: int) -> None:
        """Dispatcher blocks a tech's time by hand (lunch, a job booked by phone, etc.)."""
        if not 5 <= minutes <= 12 * 60:
            raise AppError("Choose between 5 minutes and 12 hours", code="invalid_duration")
        now = self.c.clock.now()
        self.s.add(
            AvailabilityBlock(
                technician_id=tech.id,
                kind=AvailabilityKind.BUSY.value,
                starts_at=now,
                ends_at=now + timedelta(minutes=minutes),
                source=MANUAL_SOURCE,
                label="Busy",
            )
        )
        await self.s.flush()

    async def clear_busy(self, tech: Technician) -> None:
        """Remove manual busy blocks that cover now or the future."""
        await self.s.execute(
            delete(AvailabilityBlock).where(
                AvailabilityBlock.technician_id == tech.id,
                AvailabilityBlock.source == MANUAL_SOURCE,
                AvailabilityBlock.ends_at > self.c.clock.now(),
            )
        )

    # --- Availability board + dashboard ---------------------------------------------------
    async def availability_board(self, shop: Shop, day: date | None = None) -> list[TechDay]:
        now = self.c.clock.now()
        techs = await self.list_technicians(shop)
        service = AvailabilityService(self.s, self.c)
        blocks = await service.load_tech_blocks(techs, {shop.id: shop}, now)
        busy = await service.busy_technician_ids()
        tz = ZoneInfo(shop.timezone)
        day = day or now.astimezone(tz).date()
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        return [
            TechDay(
                technician=t,
                blocks=sorted(
                    (
                        b
                        for b in blocks.get(t.id, [])
                        if b.ends_at > day_start and b.starts_at < day_end
                    ),
                    key=lambda b: b.starts_at,
                ),
                free_now=t.is_active and t.id not in busy and is_free_at(blocks.get(t.id, []), now),
                on_job=t.id in busy,
            )
            for t in techs
        ]

    async def dashboard(self, shop: Shop) -> dict[str, int]:
        board = await self.availability_board(shop)
        open_offers = await self.s.scalar(
            select(func.count())
            .select_from(ServiceRequest)
            .where(
                ServiceRequest.shop_id == shop.id,
                ServiceRequest.status == RequestStatus.OFFERED.value,
            )
        )
        active_jobs = await self.s.scalar(
            select(func.count())
            .select_from(ServiceRequest)
            .where(
                ServiceRequest.shop_id == shop.id,
                ServiceRequest.status.in_(
                    [s.value for s in ACTIVE_JOB_STATUSES if s != RequestStatus.PROPOSED]
                ),
            )
        )
        waitlisted = await self.s.scalar(
            select(func.count())
            .select_from(ServiceRequest)
            .where(ServiceRequest.status == RequestStatus.WAITLISTED.value)
        )
        return {
            "techs_free_now": sum(1 for d in board if d.free_now),
            "techs_on_job": sum(1 for d in board if d.on_job),
            "open_offers": open_offers or 0,
            "active_jobs": active_jobs or 0,
            "waitlisted_nearby": waitlisted or 0,
        }
