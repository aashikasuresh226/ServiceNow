"""A shop's own customers and jobs that live in its software (Housecall Pro), so they show
up in our apps even though they weren't booked through us. Personal fields are encrypted."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    Uuid,
)
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

    # Progress recorded by the technician in our app. Housecall Pro's API can't set a job's
    # status, so each step is also written to the job as a timestamped note.
    app_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    on_my_way_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    arrived_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    actual_issue: Mapped[str | None] = mapped_column(String(40))  # IssueCategory, at finish


class ExternalJobEvent(IdMixin, TimestampMixin, Base):
    """An update queued for Housecall Pro: something done in our app on a Housecall Pro job
    (job_id), or on a job booked through our app that's mirrored there (request_id).
    Retried by the worker, in order, until it's sent."""

    __tablename__ = "external_job_events"
    __table_args__ = (Index("ix_external_job_events_pending", "sent_at", "created_at"),)

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("external_jobs.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("service_requests.id", ondelete="CASCADE"), index=True
    )
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("technicians.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # status|note|line_item|photo
    # status: on_my_way|arrived|started|finished. note: the text. line_item: JSON.
    # photo: storage key. Encrypted: notes can hold customer details.
    payload: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(String(300))


class IntegrationLog(IdMixin, TimestampMixin, Base):
    """What we sent to (or read from) the shop's Housecall Pro and whether it worked, so the
    shop can see it in the portal. Kept 30 days."""

    __tablename__ = "integration_logs"
    __table_args__ = (Index("ix_integration_logs_shop_created", "shop_id", "created_at"),)

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(String(400))


class StoredFile(TimestampMixin, Base):
    """A photo kept in the database (see integrations/storage.DatabaseFileStorage),
    encrypted. Used when the server's own disk doesn't survive restarts."""

    __tablename__ = "stored_files"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
