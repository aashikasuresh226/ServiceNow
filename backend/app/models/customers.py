"""A shop's own customers and jobs that live in its software (Housecall Pro), so they show
up in our apps even though they weren't booked through us. Personal fields are encrypted."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.db import Base, UTCDateTime
from app.core.fieldcrypt import EncryptedText, blind_index
from app.models.base import IdMixin, TimestampMixin


class ShopCustomer(IdMixin, TimestampMixin, Base):
    """Someone who is a customer of this shop: imported from Housecall Pro, or a person who
    joined our app through the shop's invite link. Linked to their homeowner account once
    they use the app (matched by phone or email)."""

    __tablename__ = "shop_customers"
    __table_args__ = (
        UniqueConstraint("shop_id", "provider", "external_id", name="uq_shop_customer_external"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # housecall_pro | app
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(EncryptedText)
    phone: Mapped[str | None] = mapped_column(EncryptedText)  # E.164
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(EncryptedText)
    email_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    address: Mapped[str | None] = mapped_column(EncryptedText)

    homeowner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("homeowners.id", ondelete="SET NULL"), index=True
    )
    # Personal invite link /join/<code>; not secret (it only names the shop).
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    invited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    joined_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_job_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    @validates("phone")
    def _index_phone(self, _key: str, value: str | None) -> str | None:
        self.phone_hash = blind_index("phone", value)
        return value

    @validates("email")
    def _index_email(self, _key: str, value: str | None) -> str | None:
        self.email_hash = blind_index("email", value)
        return value


class ExternalJob(IdMixin, TimestampMixin, Base):
    """A job created in the shop's software (not booked through us), copied every minute so
    the assigned technician sees it in the app and the office sees it in the portal."""

    __tablename__ = "external_jobs"
    __table_args__ = (
        UniqueConstraint("shop_id", "provider", "external_id", name="uq_external_job"),
        Index("ix_external_jobs_tech_time", "technician_id", "starts_at"),
    )

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("technicians.id", ondelete="SET NULL")
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("shop_customers.id", ondelete="SET NULL")
    )
    invoice_number: Mapped[str | None] = mapped_column(String(40))
    work_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(EncryptedText)
    customer_name: Mapped[str | None] = mapped_column(EncryptedText)
    customer_phone: Mapped[str | None] = mapped_column(EncryptedText)
    address: Mapped[str | None] = mapped_column(EncryptedText)
    starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # None: unscheduled
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
