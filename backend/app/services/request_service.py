"""Homeowner-side request intake: describe → photos → AI analysis → preferences."""

from __future__ import annotations

import uuid
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, InvalidState, NotFound
from app.domain.enums import Actor, EquipmentType, RequestStatus, SoftSkill, Symptom, Urgency
from app.domain.pricing import PRICE_BOOK, estimate_for
from app.integrations.ai.base import PhotoInput
from app.integrations.storage import sniff_image_type
from app.models import Homeowner, RequestPhoto, ServiceRequest
from app.services.lifecycle import transition
from app.services.validation import validate_options

S = RequestStatus
EDITABLE_STATUSES = {S.DRAFT.value, S.ANALYZED.value}


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
        lat: float | None,
        lng: float | None,
    ) -> ServiceRequest:
        symptoms = validate_options(symptoms, Symptom, "symptom")
        validate_options([urgency], Urgency, "urgency")
        if not symptoms and not (description and description.strip()):
            raise AppError("Tell us what's going wrong", code="missing_description")

        if lat is None or lng is None:
            if address:
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
        photos = [
            PhotoInput(await self.c.storage.read(p.storage_key), p.content_type)
            for p in request.photos
        ]
        result = await self.c.analyzer.analyze(
            symptoms=request.symptoms, description=request.description, photos=photos
        )
        estimate = estimate_for(result.diagnosis.primary_issue)
        price_entry = PRICE_BOOK[result.diagnosis.primary_issue]

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
        }
        request.issue_category = result.diagnosis.primary_issue.value
        request.requires_refrigerant_work = price_entry.requires_refrigerant_work or any(
            PRICE_BOOK[a].requires_refrigerant_work for a in result.diagnosis.alternatives
        )
        request.diagnostic_fee_cents = estimate.diagnostic_fee_cents
        request.estimate_low_cents = estimate.total_low_cents
        transition(self.s, request, S.ANALYZED, Actor.SYSTEM)
        await self.s.flush()
        return request

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

    async def set_preferences(
        self, request: ServiceRequest, *, soft_skills: list[str], require_all: bool
    ) -> ServiceRequest:
        if request.status != S.ANALYZED.value:
            raise InvalidState("Preferences can only be set before matching")
        request.soft_skills = validate_options(soft_skills, SoftSkill, "soft skill")
        request.require_all_skills = require_all and bool(request.soft_skills)
        return request
