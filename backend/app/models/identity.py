"""Accounts and authentication state: homeowners, shop users, OTPs, refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, UTCDateTime
from app.models.base import IdMixin, TimestampMixin


class Homeowner(IdMixin, TimestampMixin, Base):
    __tablename__ = "homeowners"

    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(300))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Payments: the card lives in Stripe; we keep only references and display info.
    payment_customer_id: Mapped[str | None] = mapped_column(String(64))
    default_payment_method_id: Mapped[str | None] = mapped_column(String(64))
    payment_method_label: Mapped[str | None] = mapped_column(String(64))  # e.g. "Visa •• 4242"


class PhoneOtp(IdMixin, TimestampMixin, Base):
    """A one-time code sent by SMS. Only a hash of the code is stored."""

    __tablename__ = "phone_otps"
    __table_args__ = (Index("ix_phone_otps_phone_created", "phone", "created_at"),)

    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ShopUser(IdMixin, TimestampMixin, Base):
    __tablename__ = "shop_users"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    # TOTP secret, encrypted at rest. 2-step verification is mandatory for shop users.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(512))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    shop = relationship("Shop", back_populates="users")


class RefreshToken(IdMixin, TimestampMixin, Base):
    """Rotating refresh tokens. Stored hashed; reuse of a rotated token revokes the family."""

    __tablename__ = "refresh_tokens"

    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)  # homeowner | shop_user
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
