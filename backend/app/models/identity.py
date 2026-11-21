"""Accounts and authentication state: homeowners, shop users, OTPs, refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.core.db import Base, UTCDateTime
from app.core.fieldcrypt import EncryptedText, blind_index
from app.models.base import IdMixin, TimestampMixin


class Homeowner(IdMixin, TimestampMixin, Base):
    __tablename__ = "homeowners"

    # Personal details are encrypted in the database (see core.fieldcrypt). Phone and
    # email also keep a keyed hash ("blind index") so sign-in can look them up.
    # Phone is set only after the number is verified with a one-time code.
    phone: Mapped[str | None] = mapped_column(EncryptedText)
    phone_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Set when the homeowner signs in with Google (email verified by Google).
    email: Mapped[str | None] = mapped_column(EncryptedText)
    email_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    # Sign-in with an authenticator app (see services/authenticator.py).
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(512))
    backup_codes: Mapped[str | None] = mapped_column(Text)  # JSON list of hashes
    # True only when the number was confirmed by a texted code (none are sent right now):
    # unconfirmed numbers never unlock a shop's customer record.
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    name: Mapped[str | None] = mapped_column(EncryptedText)
    address: Mapped[str | None] = mapped_column(EncryptedText)
    photo_url: Mapped[str | None] = mapped_column(String(500))  # profile photo (services/media)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Payments: the card lives in Stripe; we keep only references and display info.
    payment_customer_id: Mapped[str | None] = mapped_column(String(64))
    default_payment_method_id: Mapped[str | None] = mapped_column(String(64))
    payment_method_label: Mapped[str | None] = mapped_column(String(64))  # e.g. "Visa •• 4242"

    @validates("phone")
    def _index_phone(self, _key: str, value: str | None) -> str | None:
        self.phone_hash = blind_index("phone", value)
        return value

    @validates("email")
    def _index_email(self, _key: str, value: str | None) -> str | None:
        self.email_hash = blind_index("email", value)
        return value


class PhoneOtp(IdMixin, TimestampMixin, Base):
    """A one-time code sent by SMS.

    With Twilio Verify, Twilio holds the code and code_hash is empty; the row is
    still kept to enforce our per-number rate limits. Without Twilio (development
    only) the code is generated here and only its hash is stored. The number itself
    isn't stored: `phone` holds its blind index.
    """

    __tablename__ = "phone_otps"
    __table_args__ = (Index("ix_phone_otps_phone_created", "phone", "created_at"),)

    phone: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ShopUser(IdMixin, TimestampMixin, Base):
    __tablename__ = "shop_users"

    shop_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    # Empty for accounts that only use "Sign in with Google".
    password_hash: Mapped[str | None] = mapped_column(String(256))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    # TOTP secret, encrypted at rest. 2-step verification is mandatory for shop users.
    totp_secret_encrypted: Mapped[str | None] = mapped_column(String(512))
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Proven by a link sent to the address (Firebase), or by Google.
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    shop = relationship("Shop", back_populates="users")


class RefreshToken(IdMixin, TimestampMixin, Base):
    """Rotating refresh tokens. Stored hashed; reuse of a rotated token revokes the family."""

    __tablename__ = "refresh_tokens"

    # homeowner | shop_user | technician
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class AuthNonce(IdMixin, TimestampMixin, Base):
    """Single-use nonce for "Sign in with Google": the ID token must carry one we issued."""

    __tablename__ = "auth_nonces"

    nonce_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class EmailChallenge(IdMixin, TimestampMixin, Base):
    """Proof that someone controls an email address: a shop owner's sign-up email, or the
    address a technician was invited at. The link is emailed by Firebase (free) or, in
    development without Firebase, printed in the API window."""

    __tablename__ = "email_challenges"

    purpose: Mapped[str] = mapped_column(String(20), nullable=False)  # shop_email | tech_invite
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    email: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # After the email is proven, the browser that proved it gets a second secret:
    # whoever only saw the link (e.g. the shop that sent the invite) can't finish.
    claim_hash: Mapped[str | None] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
