"""Jobs in the shop's own software (Housecall Pro), for shops whose dispatcher assigns
technicians there.

1. push: when the shop accepts (or an instant book happens) we create the customer and
   the job in Housecall Pro with the arrival window, our notes (problem, the AI's read
   of the data plate) and photo links. The job is left unassigned, unless the homeowner
   picked a specific technician, so the dispatcher assigns someone as they already do.
2. sync: we read the job back (polling every minute, or right away when Housecall Pro
   calls our webhook) and copy over who's assigned, schedule changes and status.

A failed push is kept as `external_error` (shown in the portal) and retried.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError
from app.domain.enums import Actor, RequestStatus, SchedulingProvider
from app.integrations.scheduling.housecall_pro import HcpJob, HousecallProClient, parse_us_address
from app.models import Homeowner, ServiceRequest, Shop, Technician
from app.services.calendar_service import CalendarService
from app.services.lifecycle import transition
from app.services.notifications import notify_homeowner

log = logging.getLogger(__name__)
S = RequestStatus
SYNCED = [S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS]
SYNCED_VALUES = [s.value for s in SYNCED]
PHOTO_LINK_TTL = timedelta(days=14)
ARRIVAL_WINDOW_MINUTES = 60


class ExternalJobService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    def _client(self, shop: Shop) -> HousecallProClient | None:
        if (
            shop.scheduling_provider != SchedulingProvider.HOUSECALL_PRO.value
            or not shop.scheduling_credentials_encrypted
        ):
            return None
        credentials = json.loads(self.c.encryptor.decrypt(shop.scheduling_credentials_encrypted))
        client = self.c.scheduling(SchedulingProvider.HOUSECALL_PRO, credentials)
        assert isinstance(client, HousecallProClient)
        return client

    # --- Push ------------------------------------------------------------------------------
    async def push(self, request: ServiceRequest, shop: Shop) -> None:
        if request.external_job_id:
            return
        client = self._client(shop)
        if client is None:
            request.external_error = "Housecall Pro isn't connected (Integrations)"
            return
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        assert homeowner
        name = (homeowner.name or "HVAC Connect customer").split()
        try:
            customer_id, address_id = await client.find_or_create_customer(
                first_name=name[0],
                last_name=" ".join(name[1:]),
                mobile=homeowner.phone,
                email=homeowner.email,
                address=parse_us_address(request.address or ""),
            )
            employee_ids = []
            if request.technician_confirmed and request.technician_id:
                tech = await self.s.get(Technician, request.technician_id)
                if tech and tech.external_id:
                    employee_ids = [tech.external_id]
            start = request.eta_at or self.c.clock.now()
            job_id = await client.create_job(
                customer_id=customer_id,
                address_id=address_id,
                start=start,
                end=start + timedelta(minutes=self.c.settings.default_job_duration_minutes),
                arrival_window_minutes=ARRIVAL_WINDOW_MINUTES,
                notes=self._notes(request),
                employee_ids=employee_ids,
            )
        except AppError as exc:
            request.external_error = exc.message[:300]
            log.warning("Housecall Pro push failed for %s: %s", request.id, exc.message)
            return
        request.external_job_id = job_id
        request.external_error = None
        request.external_synced_at = self.c.clock.now()
        await self.s.flush()
        # Photo links are a nice-to-have: don't fail the push over them.
        for index, photo in enumerate(request.photos, start=1):
            expires = self.c.clock.now() + PHOTO_LINK_TTL
            sig = self.c.url_signer.sign(f"photo:{photo.id}", expires)
            url = (
                f"{self.c.settings.public_api_url}{self.c.settings.api_prefix}"
                f"/photos/{photo.id}?sig={sig}"
            )
            try:
                await client.add_link(job_id, f"Customer photo {index}", url)
            except AppError as exc:
                log.info("Couldn't attach photo link to HCP job %s: %s", job_id, exc.message)

    def _notes(self, request: ServiceRequest) -> str:
        unit = request.unit_info or {}
        dx = request.diagnosis or {}
        lines = ["Booked through HVAC Connect."]
        if request.symptoms:
            lines.append("Problem: " + ", ".join(s.replace("_", " ") for s in request.symptoms))
        if request.description:
            lines.append(f'Customer says: "{request.description}"')
        plate = " ".join(str(v) for v in (unit.get("brand"), unit.get("model_number")) if v)
        if plate:
            lines.append(f"Unit (read from the photo): {plate}")
        details = [
            f"{unit['approx_age_years']} years old" if unit.get("approx_age_years") else None,
            f"refrigerant {unit['refrigerant']}" if unit.get("refrigerant") else None,
            f"serial {unit['serial_number']}" if unit.get("serial_number") else None,
        ]
        if any(details):
            lines.append("Unit details: " + ", ".join(d for d in details if d))
        if dx.get("primary_issue_label"):
            lines.append(
                f"Likely issue: {dx['primary_issue_label']}. {dx.get('summary') or ''}".strip()
            )
        if request.estimate_low_cents:
            lines.append(
                f"Customer was shown a starting price of ${request.estimate_low_cents / 100:.0f}."
            )
        return "\n".join(lines)

    async def note_canceled(self, request: ServiceRequest, shop: Shop, reason: str) -> None:
        client = self._client(shop)
        if client is None or not request.external_job_id:
            return
        try:
            await client.add_note(request.external_job_id, f"Canceled in HVAC Connect: {reason}")
            await client.unschedule(request.external_job_id)
        except AppError as exc:
            log.info("Couldn't mark HCP job %s canceled: %s", request.external_job_id, exc.message)

    # --- Sync ---------------------------------------------------------------------------------
    async def sync_due(self) -> int:
        """Worker: retry failed pushes and read back accepted jobs that are due."""
        now = self.c.clock.now()
        due = now - timedelta(seconds=self.c.settings.external_job_poll_seconds)
        rows = list(
            await self.s.scalars(
                select(ServiceRequest)
                .join(Shop, Shop.id == ServiceRequest.shop_id)
                .where(
                    Shop.dispatch_mode == "software",
                    ServiceRequest.status.in_(SYNCED_VALUES),
                    or_(
                        ServiceRequest.external_synced_at.is_(None),
                        ServiceRequest.external_synced_at <= due,
                    ),
                )
                .limit(200)
            )
        )
        done = 0
        for request in rows:
            shop = await self.s.get(Shop, request.shop_id)
            if shop is None:
                continue
            if not request.external_job_id:
                request.external_synced_at = now  # don't retry every tick
                await self.push(request, shop)
            else:
                await self.sync(request, shop)
            done += 1
        return done

    async def sync(self, request: ServiceRequest, shop: Shop) -> None:
        client = self._client(shop)
        if client is None or not request.external_job_id:
            return
        try:
            job = await client.get_job(request.external_job_id)
        except AppError as exc:
            request.external_error = exc.message[:300]
            request.external_synced_at = self.c.clock.now()
            return
        request.external_synced_at = self.c.clock.now()
        request.external_error = None
        if job is None or job.canceled:
            await self._canceled_by_shop(request, shop)
            return
        await self._apply_assignment(request, shop, job, client)
        await self._apply_status(request, job)

    async def _apply_assignment(
        self, request: ServiceRequest, shop: Shop, job: HcpJob, client: HousecallProClient
    ) -> None:
        calendar = CalendarService(self.s, self.c)
        tech = None
        if job.employee_ids:
            tech = await self._tech_for(shop, job.employee_ids[0], client)
        moved = False
        if tech is not None and (
            tech.id != request.technician_id or not request.technician_confirmed
        ):
            await calendar.release(request)
            request.technician_id = tech.id
            request.technician_confirmed = True
            moved = True
            homeowner = await self.s.get(Homeowner, request.homeowner_id)
            if homeowner:
                await notify_homeowner(
                    self.c, homeowner, f"{tech.name} from {shop.name} is your technician."
                )
        if job.scheduled_start and (
            request.eta_at is None
            or abs(job.scheduled_start - request.eta_at) > timedelta(minutes=1)
        ):
            if not moved:
                await calendar.release(request)
            request.eta_at = job.scheduled_start
            moved = True
        if moved:
            await self.s.flush()
            await calendar.book(request)
            await calendar.confirm(request)

    async def _tech_for(
        self, shop: Shop, employee_id: str, client: HousecallProClient
    ) -> Technician | None:
        query = select(Technician).where(
            Technician.shop_id == shop.id, Technician.external_id == employee_id
        )
        tech = await self.s.scalar(query)
        if tech is not None:
            return tech
        # Someone new in Housecall Pro: add them (inactive for our matching until the
        # shop sets their skills and hours).
        for person in await client.list_technicians():
            if person.external_id == employee_id:
                tech = Technician(
                    shop_id=shop.id,
                    name=person.name,
                    external_id=person.external_id,
                    is_active=False,
                )
                self.s.add(tech)
                await self.s.flush()
                return tech
        return None

    async def _apply_status(self, request: ServiceRequest, job: HcpJob) -> None:
        if job.started and request.status in (S.DISPATCHED.value, S.EN_ROUTE.value):
            transition(self.s, request, S.ON_SITE, Actor.SYSTEM, note="Started in Housecall Pro")
        if job.completed and request.status == S.IN_PROGRESS.value:
            from app.services.job_service import JobService  # avoid import cycle

            await JobService(self.s, self.c).complete(request, Actor.SYSTEM)

    async def _canceled_by_shop(self, request: ServiceRequest, shop: Shop) -> None:
        if request.status not in (S.DISPATCHED.value, S.EN_ROUTE.value):
            request.external_error = "Canceled or deleted in Housecall Pro after work started"
            return
        from app.services.matching_service import MatchingService  # avoid import cycle

        await MatchingService(self.s, self.c).cancel(
            request, Actor.SHOP, f"{shop.name} canceled the visit"
        )
        homeowner = await self.s.get(Homeowner, request.homeowner_id)
        if homeowner:
            await notify_homeowner(
                self.c,
                homeowner,
                f"{shop.name} canceled your visit. Open the app to find another technician.",
            )

    # --- Webhook ------------------------------------------------------------------------------
    async def handle_webhook(self, token: str, payload: dict[str, object]) -> bool:
        """Housecall Pro tells us something changed: re-read that job now. We never trust
        the payload itself; the job is fetched with the shop's key."""
        shop = await self.s.scalar(select(Shop).where(Shop.scheduling_webhook_token == token))
        if shop is None:
            return False
        job_id = _job_id(payload)
        if not job_id:
            return True
        request = await self.s.scalar(
            select(ServiceRequest).where(
                ServiceRequest.shop_id == shop.id, ServiceRequest.external_job_id == job_id
            )
        )
        if request is not None and request.status in SYNCED_VALUES:
            await self.sync(request, shop)
        return True


def _job_id(payload: dict[str, object]) -> str | None:
    for key in ("job", "appointment", "data"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            found = inner.get("job_id") or inner.get("id")
            if found:
                return str(found)
    found = payload.get("job_id") or payload.get("id")
    return str(found) if found else None
