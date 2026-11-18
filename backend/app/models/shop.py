"""HVAC shops, their technicians and technician availability."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.domain.enums import SchedulingProvider
from app.models.base import IdMixin, TimestampMixin


class Shop(IdMixin, TimestampMixin, Base):
    __tablename__ = "shops"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", nullable=False)

    # Shops choose when they take on-demand work.
    is_live: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Stripe Connect (Express) account used for payouts.
    payout_account_id: Mapped[str | None] = mapped_column(String(64))
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payout_schedule: Mapped[str] = mapped_column(String(16), default="daily", nullable=False)

    scheduling_provider: Mapped[str] = mapped_column(
        String(32), default=SchedulingProvider.NONE.value, nullable=False
    )
    # Provider credentials, encrypted (see core.security.Encryptor). Never returned by the API.
    scheduling_credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    scheduling_last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    scheduling_last_error: Mapped[str | None] = mapped_column(String(500))
    write_back_jobs: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users = relationship("ShopUser", back_populates="shop", cascade="all, delete-orphan")
    technicians = relationship("Technician", back_populates="shop", cascade="all, delete-orphan")


class Technician(IdMixin, TimestampMixin, Base):
    __tablename__ = "technicians"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20))
    photo_url: Mapped[str | None] = mapped_column(String(500))
    external_id: Mapped[str | None] = mapped_column(String(64))  # id in ServiceTitan / HCP

    equipment_types: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    soft_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    service_radius_km: Mapped[float] = mapped_column(Float, default=25.0, nullable=False)
    # Where the tech starts from; falls back to the shop's location when unset.
    base_lat: Mapped[float | None] = mapped_column(Float)
    base_lng: Mapped[float | None] = mapped_column(Float)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Fallback weekly hours when the shop has no scheduling integration, e.g.
    # {"mon": [["08:00", "17:00"]], ...} in the shop's local timezone.
    working_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Secret token in the technician's calendar feed URL (.ics). Rotating it revokes old links.
    calendar_token: Mapped[str | None] = mapped_column(String(64), unique=True)

    rating_sum: Mapped[int] = mapped_column(default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(default=0, nullable=False)

    shop = relationship("Shop", back_populates="technicians")
    availability = relationship(
        "AvailabilityBlock", back_populates="technician", cascade="all, delete-orphan"
    )

    @property
    def rating(self) -> float | None:
        return round(self.rating_sum / self.rating_count, 1) if self.rating_count else None


class AvailabilityBlock(IdMixin, TimestampMixin, Base):
    """A time range when a tech is on shift (SHIFT) or booked (BUSY).

    Sources: a job booked through the app ("job", linked to its request), time a
    dispatcher blocked by hand ("manual"), or the shop's scheduling software.
    """

    __tablename__ = "availability_blocks"
    __table_args__ = (Index("ix_availability_tech_time", "technician_id", "starts_at", "ends_at"),)

    technician_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # provider name or "hours"
    label: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    details: Mapped[str | None] = mapped_column(Text)

    technician = relationship("Technician", back_populates="availability")
