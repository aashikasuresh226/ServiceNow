"""Turn models into API responses. Keeps privacy rules (what each side may see) in one place."""

from __future__ import annotations

import math
from datetime import timedelta

from app.container import Container
from app.domain.enums import RequestStatus
from app.domain.pricing import platform_fee
from app.models import Message, RequestPhoto, ServiceRequest, Technician
from app.schemas.api import (
    EstimateInfo,
    MessageOut,
    PaymentInfo,
    PhotoOut,
    QuoteInfo,
    RequestOut,
    ShopJobOut,
    TechJobOut,
    TechnicianSummary,
    WaitlistInfo,
)
from app.services.message_service import chat_open, technician_can_contact

PHOTO_URL_TTL = timedelta(hours=1)
S = RequestStatus
DISPATCHED_OR_LATER = {
    s.value for s in (S.DISPATCHED, S.EN_ROUTE, S.ON_SITE, S.QUOTED, S.IN_PROGRESS, S.COMPLETED)
}


def photo_out(container: Container, photo: RequestPhoto) -> PhotoOut:
    expires = container.clock.now() + PHOTO_URL_TTL
    sig = container.url_signer.sign(f"photo:{photo.id}", expires)
    base = container.settings.public_api_url
    return PhotoOut(
        id=photo.id, url=f"{base}{container.settings.api_prefix}/photos/{photo.id}?sig={sig}"
    )


def _technician_summary(
    container: Container, request: ServiceRequest, tech: Technician | None
) -> TechnicianSummary | None:
    if tech is None or request.shop is None:
        return None
    now = container.clock.now()
    eta = None
    if request.eta_at and request.status in {
        S.PROPOSED.value,
        S.OFFERED.value,
        S.DISPATCHED.value,
        S.EN_ROUTE.value,
    }:
        eta = max(1, math.ceil((request.eta_at - now).total_seconds() / 60))
    shop = request.shop
    # Live location only while driving to THIS job. Before that (even when the tech is
    # assigned for later today, or driving to another customer) and after arrival: none.
    location = None
    location_at = None
    live = request.live_location
    if request.status == S.EN_ROUTE.value and live is not None:
        location = {"lat": live.lat, "lng": live.lng}
        location_at = live.recorded_at
    contact = technician_can_contact(tech) and request.status in DISPATCHED_OR_LATER
    return TechnicianSummary(
        id=tech.id,
        name=tech.name,
        first_name=tech.name.split()[0],
        photo_url=tech.photo_url,
        rating=tech.rating,
        rating_count=tech.rating_count,
        certifications=tech.certifications,
        shop_name=shop.name,
        shop_phone=shop.phone if request.status in DISPATCHED_OR_LATER else None,
        distance_km=request.distance_km,
        eta_minutes=eta,
        arrival_at=request.eta_at,
        location=location,
        location_updated_at=location_at,
        phone=tech.phone if contact else None,
        can_message=contact,
    )


def _quote(request: ServiceRequest) -> QuoteInfo | None:
    if request.final_price_cents is None:
        return None
    return QuoteInfo(final_price_cents=request.final_price_cents, notes=request.quote_notes)


def request_out(container: Container, request: ServiceRequest) -> RequestOut:
    waitlist = None
    if request.status == S.WAITLISTED.value:
        waitlist = WaitlistInfo(
            position=request.waitlist_position,
            eta_minutes=request.waitlist_eta_minutes,
            since=request.waitlisted_at,
            reason=request.waitlist_reason,
        )
    return RequestOut(
        id=request.id,
        status=request.status,
        created_at=request.created_at,
        symptoms=request.symptoms,
        description=request.description,
        urgency=request.urgency,
        address=request.address,
        lat=request.lat,
        lng=request.lng,
        photos=[photo_out(container, p) for p in request.photos],
        unit=request.unit_info,
        diagnosis=request.diagnosis,
        estimate=EstimateInfo(
            diagnostic_fee_cents=request.diagnostic_fee_cents, low_cents=request.estimate_low_cents
        ),
        technician=_technician_summary(container, request, request.technician),
        proposal_expires_at=request.proposal_expires_at,
        offer_expires_at=request.offer_expires_at,
        waitlist=waitlist,
        quote=_quote(request),
        payment=PaymentInfo(
            authorized_cents=request.authorized_cents, captured_cents=request.captured_cents
        ),
        rating=request.rating,
        shop_rating=request.shop_rating,
        preferred_shop_id=request.preferred_shop_id,
        preferred_technician_id=request.preferred_technician_id,
        canceled_reason=request.canceled_reason,
        completed_at=request.completed_at,
        chat_open=chat_open(request, container.clock.now()),
    )


def shop_job_out(container: Container, request: ServiceRequest) -> ShopJobOut:
    """Before dispatch the shop sees the job but not the customer's contact details."""
    revealed = request.status in DISPATCHED_OR_LATER
    homeowner = request.homeowner
    first_name = (homeowner.name or "").split()[0] if homeowner and homeowner.name else None
    area = "Nearby"
    if request.distance_km is not None:
        area = f"{request.distance_km * 0.621371:.1f} mi away"
    payout = None
    amount = request.captured_cents or request.final_price_cents or request.estimate_low_cents
    if amount:
        payout = amount - platform_fee(amount, container.settings.platform_fee_bps)
    return ShopJobOut(
        id=request.id,
        status=request.status,
        created_at=request.created_at,
        arrival_at=request.eta_at,
        customer_first_name=first_name,
        customer_phone=homeowner.phone if revealed and homeowner else None,
        address=request.address if revealed else None,
        area_label=area,
        distance_km=request.distance_km,
        symptoms=request.symptoms,
        description=request.description,
        photos=[photo_out(container, p) for p in request.photos],
        unit=request.unit_info,
        diagnosis=request.diagnosis,
        estimate=EstimateInfo(
            diagnostic_fee_cents=request.diagnostic_fee_cents, low_cents=request.estimate_low_cents
        ),
        technician_id=request.technician_id,
        technician_name=request.technician.name if request.technician else None,
        offer_expires_at=request.offer_expires_at,
        quote=_quote(request),
        payment=PaymentInfo(
            authorized_cents=request.authorized_cents, captured_cents=request.captured_cents
        ),
        payout_cents=payout,
        picked_by_customer=request.preferred_shop_id is not None
        and request.preferred_shop_id == request.shop_id,
        technician_rating=request.rating,
        shop_rating=request.shop_rating,
        review=request.review,
        technician_flag=request.technician_flag,
        chat_open=chat_open(request, container.clock.now()),
        driving=request.status == S.EN_ROUTE.value and request.live_location is not None,
    )


def _area(request: ServiceRequest) -> str:
    if request.distance_km is None:
        return "Nearby"
    return f"{request.distance_km * 0.621371:.1f} mi away"


def tech_job_out(container: Container, request: ServiceRequest, tech: Technician) -> TechJobOut:
    """What a technician sees. Before they (or the office) accept: no name or address."""
    accepted = request.status in DISPATCHED_OR_LATER
    homeowner = request.homeowner
    contact = accepted and tech.can_contact_customers
    return TechJobOut(
        id=request.id,
        status=request.status,
        arrival_at=request.eta_at,
        offer_expires_at=request.offer_expires_at,
        customer_name=(homeowner.name if accepted else None) if homeowner else None,
        customer_phone=homeowner.phone if contact and homeowner else None,
        address=request.address if accepted else None,
        area_label=_area(request),
        distance_km=request.distance_km,
        symptoms=request.symptoms,
        description=request.description,
        photos=[photo_out(container, p) for p in request.photos],
        unit=request.unit_info,
        diagnosis=request.diagnosis,
        quote=_quote(request),
        approved=request.status in (S.IN_PROGRESS.value, S.COMPLETED.value),
        technician_flag=request.technician_flag,
        chat_open=contact and chat_open(request, container.clock.now()),
        can_contact=contact,
        completed_at=request.completed_at,
    )


def message_out(message: Message) -> MessageOut:
    return MessageOut.model_validate(message)
