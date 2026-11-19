"""Unauthenticated endpoints: option lists, signed photo URLs, payment webhooks, health."""

from __future__ import annotations

import logging
import uuid
from enum import StrEnum
from typing import Any

from fastapi import APIRouter, Header, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import ContainerDep, SessionDep
from app.core.errors import NotFound
from app.domain import enums
from app.domain.pricing import DIAGNOSTIC_FEE_CENTS
from app.models import Homeowner, ProcessedWebhook, RequestPhoto, Shop
from app.services.provider_service import ProviderService

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
        "diagnostic_fee_cents": DIAGNOSTIC_FEE_CENTS,
        # What's switched on, so the apps only show features that work.
        "features": {
            "google_client_id": c.settings.google_web_client_id,
            "payments": c.payments is not None,
            "stripe_publishable_key": c.payments.publishable_key if c.payments else None,
            "photo_analysis": c.analyzer is not None,
            "texts": "twilio" if c.phone_verify is not None else "development",
            "scheduling_integrations": c.settings.scheduling_integrations_enabled,
            # Email links (shop sign-up, technician invites): sent by Firebase, or shown
            # on screen in development.
            "email_links": "firebase" if c.firebase is not None else "development",
            # Technicians have no sign-up: invited ones sign in here.
            "technician_sign_in_url": f"{c.settings.public_app_url.rstrip('/')}/tech/sign-in",
        },
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


@router.get("/providers/technicians/{technician_id}")
async def public_technician(
    technician_id: uuid.UUID, session: SessionDep, c: ContainerDep
) -> dict[str, Any]:
    """Public card for a shared technician link (no customer data)."""
    return await ProviderService(session, c).public_technician(technician_id)


@router.get("/providers/shops/{shop_id}")
async def public_shop(shop_id: uuid.UUID, session: SessionDep, c: ContainerDep) -> dict[str, Any]:
    """Public card for a shared company link."""
    return await ProviderService(session, c).public_shop(shop_id)


@router.post("/webhooks/housecall-pro/{token}", status_code=200)
async def housecall_pro_webhook(
    token: str, request: Request, session: SessionDep, c: ContainerDep
) -> dict[str, bool]:
    """Housecall Pro calls this when a job changes (the shop pastes the URL into
    Housecall Pro). The secret token identifies the shop; we then re-read the job from
    Housecall Pro with the shop's key instead of trusting the payload."""
    from app.services.external_jobs import ExternalJobService

    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    ok = await ExternalJobService(session, c).handle_webhook(
        token, payload if isinstance(payload, dict) else {}
    )
    if not ok:
        raise NotFound("Unknown webhook")
    return {"received": True}


@router.post("/webhooks/payments", status_code=200)
async def payments_webhook(
    request: Request,
    session: SessionDep,
    c: ContainerDep,
    stripe_signature: str | None = Header(None),
) -> dict[str, bool]:
    if c.payments is None:
        raise NotFound("Payments aren't set up")
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
