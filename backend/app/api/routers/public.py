"""Unauthenticated endpoints: option lists, signed photo URLs, payment webhooks, health."""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ContainerDep, SessionDep
from app.core.errors import NotFound
from app.domain import enums
from app.domain.pricing import DIAGNOSTIC_FEE_CENTS
from app.models import Homeowner, ProcessedWebhook, RequestPhoto, Shop

log = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

LABELS = {
    "no_cooling": "No cooling",
    "no_heat": "No heat",
    "noisy": "Noisy",
    "leaking": "Leaking",
    "wont_start": "Won't start",
    "odd_smell": "Odd smell",
    "asap": "ASAP",
    "this_week": "This week",
    "flexible": "Flexible",
    "central_ac": "Central AC",
    "heat_pump": "Heat pump",
    "furnace": "Furnace",
    "boiler": "Boiler",
    "mini_split": "Mini-split",
    "packaged_unit": "Packaged unit",
    "unknown": "Not sure",
    "epa_608": "EPA 608",
    "nate": "NATE certified",
    "state_license": "State HVAC license",
    "explains_clearly": "Explains clearly",
    "punctual": "Punctual",
    "patient": "Patient",
    "tidy": "Tidy & respectful",
    "spanish_speaking": "Speaks Spanish",
    "shows_work": "Shows work photos",
}


def _options(enum_cls: type[StrEnum]) -> list[dict[str, str]]:
    return [{"value": e.value, "label": LABELS.get(e.value, e.value)} for e in enum_cls]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/meta/options")
async def options(c: ContainerDep) -> dict[str, object]:
    return {
        "symptoms": _options(enums.Symptom),
        "urgency": _options(enums.Urgency),
        "equipment_types": _options(enums.EquipmentType),
        "certifications": _options(enums.Certification),
        "soft_skills": _options(enums.SoftSkill),
        "diagnostic_fee_cents": DIAGNOSTIC_FEE_CENTS,
        "demo_mode": c.settings.environment.value == "dev",
    }


@router.get("/photos/{photo_id}")
async def get_photo(
    photo_id: uuid.UUID, session: SessionDep, c: ContainerDep, sig: str = Query(...)
) -> Response:
    if not c.url_signer.verify(f"photo:{photo_id}", sig, now=c.clock.now()):
        raise NotFound("Photo not found")
    photo = await session.get(RequestPhoto, photo_id)
    if photo is None:
        raise NotFound("Photo not found")
    data = await c.storage.read(photo.storage_key)
    return Response(
        content=data,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/webhooks/payments", status_code=200)
async def payments_webhook(
    request: Request,
    session: SessionDep,
    c: ContainerDep,
    stripe_signature: str | None = Header(None),
) -> dict[str, bool]:
    event = c.payments.parse_webhook(payload=await request.body(), signature=stripe_signature)
    session.add(ProcessedWebhook(event_id=event.id))
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return {"duplicate": True}  # already handled; webhooks are delivered at least once

    obj = event.data
    if event.type == "account.updated":
        shop = await session.scalar(select(Shop).where(Shop.payout_account_id == obj.get("id")))
        if shop:
            shop.payouts_enabled = bool(obj.get("payouts_enabled"))
            if not shop.payouts_enabled:
                shop.is_live = False
    elif event.type == "setup_intent.succeeded":
        homeowner = await session.scalar(
            select(Homeowner).where(Homeowner.payment_customer_id == obj.get("customer"))
        )
        if homeowner and obj.get("payment_method") and not homeowner.default_payment_method_id:
            homeowner.default_payment_method_id = obj["payment_method"]
            homeowner.payment_method_label = homeowner.payment_method_label or "Saved card"
    else:
        log.info("Ignoring payment webhook %s", event.type)
    return {"duplicate": False}
