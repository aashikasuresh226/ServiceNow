"""A homeowner's service request: the central aggregate of the marketplace."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.core.fieldcrypt import EncryptedFloat, EncryptedText
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
    description: Mapped[str | None] = mapped_column(EncryptedText)
    urgency: Mapped[str] = mapped_column(String(16), default="asap", nullable=False)
    address: Mapped[str | None] = mapped_column(EncryptedText)
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
    # Why nobody could be matched, in plain language (shown to the homeowner).
    waitlist_reason: Mapped[str | None] = mapped_column(String(300))

    # Quote and payment (amounts in cents)
    final_price_cents: Mapped[int | None] = mapped_column(Integer)
    quote_notes: Mapped[str | None] = mapped_column(Text)
    payment_intent_id: Mapped[str | None] = mapped_column(String(64))
    authorized_cents: Mapped[int | None] = mapped_column(Integer)
    captured_cents: Mapped[int | None] = mapped_column(Integer)
    platform_fee_cents: Mapped[int | None] = mapped_column(Integer)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    canceled_reason: Mapped[str | None] = mapped_column(String(200))
    rating: Mapped[int | None] = mapped_column(Integer)  # the technician, 1-5
    shop_rating: Mapped[int | None] = mapped_column(Integer)  # the company, 1-5
    review: Mapped[str | None] = mapped_column(String(500))
    # The assigned technician said they can't make it (shown to the office to reassign).
    technician_flag: Mapped[str | None] = mapped_column(String(200))
    # False while the shop (its office or Housecall Pro dispatcher) hasn't picked the tech:
    # technician_id is then only our estimate of who could come, used for timing.
    technician_confirmed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Which round of offers this is (1, 2 = one shop at a time; later = several at once).
    offer_round: Mapped[int] = mapped_column(default=0, nullable=False)
    instant_booked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # The job in the shop's Housecall Pro account, once accepted.
    external_job_id: Mapped[str | None] = mapped_column(String(64))
    external_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    external_error: Mapped[str | None] = mapped_column(String(300))

    # Homeowner's choice when requesting: a company, a specific technician, or neither
    # (soonest qualified tech). Matching only considers that company / technician.
    preferred_shop_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="SET NULL")
    )
    preferred_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("technicians.id", ondelete="SET NULL")
    )

    # Optimistic locking: concurrent writers (API + worker) cannot silently clobber each other.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012

    photos = relationship(
        "RequestPhoto", back_populates="request", cascade="all, delete-orphan", lazy="selectin"
    )
    technician = relationship("Technician", lazy="joined", foreign_keys=[technician_id])
    shop = relationship("Shop", lazy="joined", foreign_keys=[shop_id])
    homeowner = relationship("Homeowner", lazy="joined")
    live_location = relationship(
        "TechLocation", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )


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


class JobOffer(IdMixin, TimestampMixin, Base):
    """One shop's offer for a confirmed request. Usually one open offer at a time
    (waterfall); after a few declines, several shops are offered at once and the first
    to accept gets the job."""

    __tablename__ = "job_offers"
    __table_args__ = (
        Index("ix_job_offers_request", "request_id"),
        Index("ix_job_offers_shop_status", "shop_id", "status"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("shops.id"), nullable=False)
    technician_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    arrival_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    round: Mapped[int] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    # open | accepted | declined | expired | withdrawn
    status: Mapped[str] = mapped_column(String(10), default="open", nullable=False)


class Message(IdMixin, TimestampMixin, Base):
    """Chat between the homeowner and the shop (office and, if allowed, the technician)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_request_created", "request_id", "created_at"),)

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False
    )
    sender: Mapped[str] = mapped_column(String(12), nullable=False)  # homeowner|technician|shop
    sender_name: Mapped[str | None] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(EncryptedText, nullable=False)


class TechLocation(IdMixin, TimestampMixin, Base):
    """The technician's latest position, ONLY while driving to this job (status en_route).
    One row per job, overwritten on each update and deleted on arrival or cancel.
    Never kept as a history. Coordinates are encrypted."""

    __tablename__ = "tech_locations"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    lat: Mapped[float] = mapped_column(EncryptedFloat, nullable=False)
    lng: Mapped[float] = mapped_column(EncryptedFloat, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)


class ProcessedWebhook(IdMixin, TimestampMixin, Base):
    """Idempotency record for payment-provider webhooks."""

    __tablename__ = "processed_webhooks"

    event_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
