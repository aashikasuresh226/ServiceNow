"""A homeowner's service request: the central aggregate of the marketplace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.domain.enums import RequestStatus
from app.models.base import IdMixin, TimestampMixin


class ServiceRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "service_requests"
    __table_args__ = (
        Index("ix_requests_status_created", "status", "created_at"),
        Index("ix_requests_technician_status", "technician_id", "status"),
    )

    homeowner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("homeowners.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default=RequestStatus.DRAFT.value)

    # What the homeowner told us
    symptoms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    urgency: Mapped[str] = mapped_column(String(16), default="asap", nullable=False)
    address: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)

    # What the AI extracted (homeowner may correct unit details)
    unit_info: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    diagnosis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    issue_category: Mapped[str | None] = mapped_column(String(40))
    requires_refrigerant_work: Mapped[bool] = mapped_column(Boolean, default=False)
    diagnostic_fee_cents: Mapped[int | None] = mapped_column(Integer)
    estimate_low_cents: Mapped[int | None] = mapped_column(Integer)

    # Matching preferences
    soft_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    require_all_skills: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Assignment
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("technicians.id", ondelete="SET NULL")
    )
    shop_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="SET NULL"), index=True
    )
    distance_km: Mapped[float | None] = mapped_column(Float)
    proposal_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    offer_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    declined_technician_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    eta_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # arrival estimate

    # Waitlist
    waitlisted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    waitlist_eta_minutes: Mapped[int | None] = mapped_column(Integer)
    waitlist_position: Mapped[int | None] = mapped_column(Integer)

    # Quote and payment (amounts in cents)
    final_price_cents: Mapped[int | None] = mapped_column(Integer)
    quote_notes: Mapped[str | None] = mapped_column(Text)
    payment_intent_id: Mapped[str | None] = mapped_column(String(64))
    authorized_cents: Mapped[int | None] = mapped_column(Integer)
    captured_cents: Mapped[int | None] = mapped_column(Integer)
    platform_fee_cents: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    canceled_reason: Mapped[str | None] = mapped_column(String(200))
    rating: Mapped[int | None] = mapped_column(Integer)

    # Optimistic locking: concurrent writers (API + worker) cannot silently clobber each other.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012

    photos = relationship(
        "RequestPhoto", back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )
    technician = relationship("Technician", lazy="joined")
    shop = relationship("Shop", lazy="joined")
    homeowner = relationship("Homeowner", lazy="joined")


class RequestPhoto(IdMixin, TimestampMixin, Base):
    __tablename__ = "request_photos"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    request = relationship("ServiceRequest", back_populates="photos")


class RequestEvent(IdMixin, TimestampMixin, Base):
    """Append-only audit log of every status change."""

    __tablename__ = "request_events"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300))
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class ProcessedWebhook(IdMixin, TimestampMixin, Base):
    """Idempotency record for payment-provider webhooks."""

    __tablename__ = "processed_webhooks"

    event_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
