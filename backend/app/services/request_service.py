"""Homeowner-side request intake: describe → photos → AI analysis → preferences."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, ExternalServiceError, InvalidState, NotFound
from app.domain.enums import (
    Actor,
    EquipmentType,
    IssueCategory,
    RequestStatus,
    Symptom,
    Urgency,
)
from app.domain.pricing import DIAGNOSTIC_FEE_CENTS, PRICE_BOOK, estimate_for, market_from_address
from app.integrations.ai.base import (
    AnalysisResult,
    Diagnosis,
    PastPrice,
    PhotoInput,
    PriceContext,
    UnitInfo,
)
from app.integrations.storage import sniff_image_type
from app.models import Homeowner, RequestPhoto, ServiceRequest
from app.services.lifecycle import transition
from app.services.validation import validate_options

S = RequestStatus
EDITABLE_STATUSES = {S.DRAFT.value, S.ANALYZED.value}


log = logging.getLogger(__name__)


class RequestService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def get_for_homeowner(
        self, request_id: uuid.UUID, homeowner: Homeowner
    ) -> ServiceRequest:
        request = await self.s.get(ServiceRequest, request_id)
        # Same error for "missing" and "not yours" so ids can't be probed.
        if request is None or request.homeowner_id != homeowner.id:
            raise NotFound("Request not found")
        return request

    async def list_for_homeowner(self, homeowner: Homeowner) -> list[ServiceRequest]:
        rows = await self.s.scalars(
            select(ServiceRequest)
            .where(ServiceRequest.homeowner_id == homeowner.id)
            .order_by(ServiceRequest.created_at.desc())
            .limit(50)
        )
        return list(rows)

    async def create(
        self,
        homeowner: Homeowner,
        *,
        symptoms: list[str],
        description: str | None,
        urgency: str,
        address: str | None,
    ) -> ServiceRequest:
        symptoms = validate_options(symptoms, Symptom, "symptom")
        validate_options([urgency], Urgency, "urgency")
        if not symptoms and not (description and description.strip()):
            raise AppError("Tell us what's going wrong", code="missing_description")

        if address and address.strip() and address.strip() != homeowner.address:
            geo = await self.c.geocoder.geocode(address)
            lat, lng, address = geo.location.lat, geo.location.lng, geo.formatted_address
        elif homeowner.lat is not None and homeowner.lng is not None:
            lat, lng, address = homeowner.lat, homeowner.lng, homeowner.address
        else:
            raise AppError("Add your service address", code="missing_address")

        request = ServiceRequest(
            homeowner_id=homeowner.id,
            symptoms=symptoms,
            description=(description or "").strip()[:2000] or None,
            urgency=urgency,
            address=address,
            lat=lat,
            lng=lng,
        )
        self.s.add(request)
        await self.s.flush()
        return request

    async def add_photo(self, request: ServiceRequest, data: bytes) -> RequestPhoto:
        if request.status not in EDITABLE_STATUSES:
            raise InvalidState("Photos can't be added at this stage")
        settings = self.c.settings
        if len(request.photos) >= settings.max_photos_per_request:
            raise AppError(
                f"Up to {settings.max_photos_per_request} photos per request",
                code="too_many_photos",
            )
        if len(data) > settings.max_photo_bytes:
            raise AppError("Photo is too large (max 10 MB)", code="photo_too_large")
        content_type = sniff_image_type(data)
        if content_type is None:
            raise AppError("Please upload a JPEG, PNG, WebP or GIF photo", code="invalid_photo")
        key = await self.c.storage.save(data, content_type)
        photo = RequestPhoto(
            request_id=request.id, storage_key=key, content_type=content_type, size_bytes=len(data)
        )
        self.s.add(photo)
        await self.s.flush()
        await self.s.refresh(request, attribute_names=["photos"])
        return photo

    async def analyze(self, request: ServiceRequest) -> ServiceRequest:
        if request.status not in EDITABLE_STATUSES:
            raise InvalidState("This request has already been analyzed and matched")
        if self.c.analyzer is not None:
            # Each analysis costs money: cap how many one homeowner can run per hour.
            self.c.rate_limiter.check(
                "ai",
                str(request.homeowner_id),
                limit=self.c.settings.ai_analyses_per_hour,
                window_seconds=3600,
            )
        context = await self.price_context(request)
        given = has_input(request)
        if given:
            result, ai_error = await self._run_analysis(request, context)
        else:
            # Nothing to look at (no photo, no description): don't guess a problem or a price.
            result, ai_error = self._on_site(), None
        analysis = (
            "skipped"
            if not given
            else "off"
            if self.c.analyzer is None
            else "failed"
            if ai_error
            else "ai"
        )
        if analysis == "ai" and result.unit.photo_feedback and not _described(request):
            # The AI couldn't use the photo and there's no description: only a retake helps.
            analysis = "photo_unusable"
            result = AnalysisResult(unit=result.unit, diagnosis=self._on_site().diagnosis)
        estimate = estimate_for(result.diagnosis.primary_issue)
        price_entry = PRICE_BOOK[result.diagnosis.primary_issue]
        fee = estimate.diagnostic_fee_cents
        identified = (
            analysis == "ai" and result.diagnosis.primary_issue != IssueCategory.GENERAL_DIAGNOSTIC
        )
        high: int | None = None
        if identified and result.estimate is not None:
            # The AI's range, from the photos + description and past prices (see price_context).
            low = fee + result.estimate.repair_low_cents
            high = fee + result.estimate.repair_high_cents
            basis, source = result.estimate.basis, "ai"
        elif identified:
            past = next((p for p in context.past_by_issue if p.issue == price_entry.label), None)
            if past is not None:
                low, high = past.low_cents, past.high_cents
                basis = f"Based on {past.jobs} past {price_entry.label.lower()} jobs here."
                source = "past_jobs"
            else:
                low = estimate.total_low_cents
                basis = f"Typical starting price for: {price_entry.label.lower()}."
                source = "price_book"
        else:
            # No problem identified: only the visit has a price; the repair is quoted on site.
            low = fee
            basis = "Your technician diagnoses the problem and gives you the price before any work."
            source = "visit_only"

        request.unit_info = {
            **asdict(result.unit),
            "equipment_type": result.unit.equipment_type.value,
        }
        request.diagnosis = {
            "primary_issue": result.diagnosis.primary_issue.value,
            "primary_issue_label": price_entry.label,
            "summary": result.diagnosis.summary,
            "alternatives": [
                {"issue": a.value, "label": PRICE_BOOK[a].label}
                for a in result.diagnosis.alternatives
            ],
            "confidence": result.diagnosis.confidence.value,
            "safety_warning": result.diagnosis.safety_warning,
            "visible_issues": result.diagnosis.visible_issues,
            "ai_used": analysis in ("ai", "photo_unusable"),
            "ai_error": ai_error,
            "analysis": analysis,  # ai | skipped (nothing given) | off | failed | photo_unusable
            "estimate_basis": basis,
            "estimate_source": source,
        }
        request.issue_category = result.diagnosis.primary_issue.value
        request.requires_refrigerant_work = price_entry.requires_refrigerant_work or any(
            PRICE_BOOK[a].requires_refrigerant_work for a in result.diagnosis.alternatives
        )
        request.diagnostic_fee_cents = fee
        request.estimate_low_cents = low
        request.estimate_high_cents = high if high is None or high > low else None
        transition(self.s, request, S.ANALYZED, Actor.SYSTEM)
        await self.s.flush()
        return request

    async def price_context(self, request: ServiceRequest) -> PriceContext:
        """What the AI bases its estimate on: final prices of completed jobs on the platform
        (last 2 years, overall and per issue), the price book, and the city/state."""
        since = self.c.clock.now() - timedelta(days=730)
        done = (
            ServiceRequest.completed_at.is_not(None),
            ServiceRequest.completed_at >= since,
            ServiceRequest.final_price_cents.is_not(None),
            ServiceRequest.final_price_cents > 0,
        )
        price = ServiceRequest.final_price_cents
        stats = (func.count(), func.avg(price), func.min(price), func.max(price))
        overall = (await self.s.execute(select(*stats).where(*done))).one()
        rows = (
            await self.s.execute(
                select(ServiceRequest.issue_category, *stats)
                .where(*done, ServiceRequest.issue_category.is_not(None))
                .group_by(ServiceRequest.issue_category)
            )
        ).all()

        def past(label: str, row: tuple[object, ...]) -> PastPrice:
            jobs, avg, low, high = row
            return PastPrice(label, int(jobs), int(avg), int(low), int(high))  # type: ignore[call-overload]

        by_issue = [
            past(PRICE_BOOK[IssueCategory(category)].label, tuple(rest))
            for category, *rest in rows
            if category in IssueCategory._value2member_map_ and rest[0]
        ]
        return PriceContext(
            market=market_from_address(request.address),
            diagnostic_fee_cents=DIAGNOSTIC_FEE_CENTS,
            price_book={entry.label: entry.repair_low_cents for entry in PRICE_BOOK.values()},
            past_overall=past("All issues", tuple(overall)) if overall[0] else None,
            past_by_issue=sorted(by_issue, key=lambda p: -p.jobs)[:12],
        )

    @staticmethod
    def _on_site() -> AnalysisResult:
        return AnalysisResult(
            unit=UnitInfo(None, None, None, EquipmentType.UNKNOWN, None),
            diagnosis=Diagnosis(
                primary_issue=IssueCategory.GENERAL_DIAGNOSTIC,
                summary="Your technician will diagnose the problem on site.",
            ),
        )

    async def _run_analysis(
        self, request: ServiceRequest, context: PriceContext
    ) -> tuple[AnalysisResult, str | None]:
        """The analysis, plus why it failed (None when it worked or is switched off).
        A failure never blocks the request: the technician diagnoses on site."""
        on_site = self._on_site()
        if self.c.analyzer is None:
            return on_site, None  # switched off (no Anthropic key): nothing is guessed
        photos = [
            PhotoInput(await self.c.storage.read(p.storage_key), p.content_type)
            for p in request.photos
        ]
        budget = self.c.settings.ai_time_budget_seconds
        try:
            async with asyncio.timeout(budget):
                result = await self.c.analyzer.analyze(
                    symptoms=request.symptoms,
                    description=request.description,
                    photos=photos,
                    current_year=self.c.clock.now().year,
                    price_context=context,
                )
        except TimeoutError:
            log.warning("Photo analysis for request %s took over %ss", request.id, budget)
            return on_site, f"the AI took longer than {int(budget)} seconds"
        except ExternalServiceError as exc:
            log.warning("Photo analysis failed for request %s: %s", request.id, exc.message)
            return on_site, getattr(exc, "reason", None) or exc.message
        return result, None

    async def update_unit(
        self,
        request: ServiceRequest,
        *,
        brand: str | None,
        model_number: str | None,
        equipment_type: str | None,
        approx_age_years: int | None,
    ) -> ServiceRequest:
        """Homeowner corrects what the AI read off the label."""
        if request.status != S.ANALYZED.value:
            raise InvalidState("Unit details can only be edited before matching")
        info = dict(request.unit_info or {})
        if equipment_type is not None:
            validate_options([equipment_type], EquipmentType, "equipment type")
            info["equipment_type"] = equipment_type
        if brand is not None:
            info["brand"] = brand.strip()[:60] or None
        if model_number is not None:
            info["model_number"] = model_number.strip()[:60] or None
        if approx_age_years is not None:
            if not 0 <= approx_age_years <= 60:
                raise AppError("Age must be between 0 and 60 years", code="invalid_age")
            info["approx_age_years"] = approx_age_years
        info["edited_by_homeowner"] = True
        request.unit_info = info
        return request


MIN_DESCRIPTION = 10  # characters: "AC broken" is a symptom, not something to analyze


def _described(request: ServiceRequest) -> bool:
    return len((request.description or "").strip()) >= MIN_DESCRIPTION


def has_input(request: ServiceRequest) -> bool:
    """Something the AI can actually look at: a photo or a real description."""
    return bool(request.photos) or _described(request)
