"""Authentication for homeowners (SMS one-time code) and shop users
(password + mandatory TOTP 2-step), with rotating refresh tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.config import Environment
from app.core.errors import Conflict, RateLimited, Unauthorized
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    Role,
    TokenClaims,
    TokenType,
    constant_time_equals,
    generate_otp_code,
    hash_otp,
    hash_password,
    hash_token,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models import Homeowner, PhoneOtp, RefreshToken, Shop, ShopUser
from app.services.phone import normalize_phone

MIN_PASSWORD_LENGTH = 12
APP_NAME = "HVAC Connect"


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class OtpStarted:
    phone: str
    resend_after_seconds: int
    dev_code: str | None  # only populated with the console SMS provider (local demo)


class AuthService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container
        self.settings = container.settings

    # --- Sessions --------------------------------------------------------------
    async def issue_session(
        self, claims: TokenClaims, *, family_id: uuid.UUID | None = None
    ) -> SessionTokens:
        now = self.c.clock.now()
        ttl = timedelta(minutes=self.settings.access_token_ttl_minutes)
        access = self.c.tokens.issue(claims, now=now, ttl=ttl)
        refresh = new_refresh_token()
        self.s.add(
            RefreshToken(
                subject_type=claims.role.value,
                subject_id=claims.subject_id,
                family_id=family_id or uuid.uuid4(),
                token_hash=hash_token(refresh),
                expires_at=now + timedelta(days=self.settings.refresh_token_ttl_days),
            )
        )
        await self.s.flush()
        return SessionTokens(access, refresh, int(ttl.total_seconds()))

    async def refresh(self, refresh_token: str) -> SessionTokens:
        now = self.c.clock.now()
        stored = await self.s.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
        if stored is None or stored.expires_at <= now:
            raise Unauthorized("Please sign in again", code="session_ended")
        if stored.revoked_at is not None:
            # A rotated token was reused: assume theft and end every session in the family.
            await self._revoke_family(stored.family_id)
            await self.s.commit()
            raise Unauthorized("Please sign in again", code="session_ended")

        stored.revoked_at = now
        role = Role(stored.subject_type)
        shop_id = None
        if role == Role.SHOP_USER:
            user = await self.s.get(ShopUser, stored.subject_id)
            if user is None or not user.mfa_enabled:
                raise Unauthorized("Please sign in again", code="session_ended")
            shop_id = user.shop_id
        elif await self.s.get(Homeowner, stored.subject_id) is None:
            raise Unauthorized("Please sign in again", code="session_ended")

        claims = TokenClaims(stored.subject_id, role, TokenType.ACCESS, shop_id)
        return await self.issue_session(claims, family_id=stored.family_id)

    async def logout(self, refresh_token: str) -> None:
        stored = await self.s.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_token))
        )
        if stored:
            await self._revoke_family(stored.family_id)

    async def _revoke_family(self, family_id: uuid.UUID) -> None:
        await self.s.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=self.c.clock.now())
        )

    # --- Homeowners: SMS one-time code -----------------------------------------------
    async def start_phone_otp(self, raw_phone: str) -> OtpStarted:
        phone = normalize_phone(raw_phone)
        now = self.c.clock.now()
        latest = await self.s.scalar(
            select(PhoneOtp).where(PhoneOtp.phone == phone).order_by(PhoneOtp.created_at.desc())
        )
        cooldown = self.settings.otp_resend_cooldown_seconds
        if latest and (wait := cooldown - (now - latest.created_at).total_seconds()) > 0:
            raise RateLimited(f"Please wait {int(wait) + 1} seconds before requesting a new code")
        sent_last_hour = await self.s.scalar(
            select(func.count())
            .select_from(PhoneOtp)
            .where(PhoneOtp.phone == phone, PhoneOtp.created_at > now - timedelta(hours=1))
        )
        if (sent_last_hour or 0) >= self.settings.otp_max_per_hour:
            raise RateLimited("Too many codes requested. Please try again later.")

        code = generate_otp_code()
        self.s.add(
            PhoneOtp(
                phone=phone,
                code_hash=hash_otp(code, phone, self.settings.jwt_secret.get_secret_value()),
                expires_at=now + timedelta(minutes=self.settings.otp_ttl_minutes),
                created_at=now,  # rate limits compare against the injected clock
            )
        )
        await self.s.flush()
        await self.c.sms.send(
            to=phone, body=f"{code} is your {APP_NAME} code. It expires in 10 minutes."
        )
        dev_code = code if self.settings.sms_provider == "console" else None
        return OtpStarted(phone, cooldown, dev_code)

    async def verify_phone_otp(
        self, raw_phone: str, code: str
    ) -> tuple[Homeowner, SessionTokens, bool]:
        phone = normalize_phone(raw_phone)
        now = self.c.clock.now()
        otp = await self.s.scalar(
            select(PhoneOtp)
            .where(
                PhoneOtp.phone == phone, PhoneOtp.consumed_at.is_(None), PhoneOtp.expires_at > now
            )
            .order_by(PhoneOtp.created_at.desc())
        )
        if otp is None:
            raise Unauthorized(
                "That code has expired. Please request a new one.", code="otp_expired"
            )
        otp.attempts += 1
        if otp.attempts > self.settings.otp_max_attempts:
            otp.consumed_at = now
            await self.s.commit()
            raise Unauthorized("Too many attempts. Please request a new code.", code="otp_locked")
        expected = hash_otp(code.strip(), phone, self.settings.jwt_secret.get_secret_value())
        if not constant_time_equals(expected, otp.code_hash):
            await self.s.commit()  # persist the failed attempt before raising
            raise Unauthorized("That code isn't right", code="otp_invalid")
        otp.consumed_at = now

        homeowner = await self.s.scalar(select(Homeowner).where(Homeowner.phone == phone))
        is_new = homeowner is None
        if homeowner is None:
            homeowner = Homeowner(phone=phone)
            self.s.add(homeowner)
            await self.s.flush()
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, is_new or not homeowner.name

    # --- Shop users: password + TOTP ------------------------------------------------
    async def shop_signup(
        self, *, email: str, password: str, shop_name: str, name: str | None
    ) -> tuple[ShopUser, str]:
        email = email.strip().lower()
        if len(password) < MIN_PASSWORD_LENGTH:
            raise Conflict(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters", code="weak_password"
            )
        if await self.s.scalar(select(ShopUser.id).where(ShopUser.email == email)):
            raise Conflict("An account with this email already exists", code="email_taken")
        shop = Shop(name=shop_name.strip())
        self.s.add(shop)
        await self.s.flush()
        user = ShopUser(
            shop_id=shop.id, email=email, password_hash=hash_password(password), name=name
        )
        self.s.add(user)
        await self.s.flush()
        return user, self._limited_token(user, TokenType.MFA_SETUP)

    async def shop_login(self, *, email: str, password: str) -> tuple[ShopUser, str, TokenType]:
        user = await self.s.scalar(select(ShopUser).where(ShopUser.email == email.strip().lower()))
        # Verify against a dummy hash when the user doesn't exist, so response
        # timing doesn't reveal which emails have accounts.
        ok = verify_password(password, user.password_hash if user else DUMMY_PASSWORD_HASH)
        if user is None or not ok:
            raise Unauthorized("Email or password is incorrect", code="bad_credentials")
        kind = TokenType.MFA if user.mfa_enabled else TokenType.MFA_SETUP
        return user, self._limited_token(user, kind), kind

    def _limited_token(self, user: ShopUser, kind: TokenType) -> str:
        ttl = timedelta(
            minutes=self.settings.mfa_token_ttl_minutes if kind == TokenType.MFA else 30
        )
        return self.c.tokens.issue(
            TokenClaims(user.id, Role.SHOP_USER, kind, user.shop_id),
            now=self.c.clock.now(),
            ttl=ttl,
        )

    def dev_totp_code(self, user: ShopUser) -> str | None:
        """Current 2-step code, exposed only in local dev so demos don't need a phone."""
        if self.settings.environment != Environment.DEV or not user.totp_secret_encrypted:
            return None
        import pyotp

        secret = self.c.encryptor.decrypt(user.totp_secret_encrypted)
        return pyotp.TOTP(secret).at(self.c.clock.now())

    async def enroll_mfa(self, user: ShopUser) -> tuple[str, str]:
        if user.mfa_enabled:
            raise Conflict("2-step verification is already on", code="mfa_already_enabled")
        secret = new_totp_secret()
        user.totp_secret_encrypted = self.c.encryptor.encrypt(secret)
        await self.s.flush()
        return secret, totp_uri(secret, user.email, APP_NAME)

    async def activate_mfa(self, user: ShopUser, code: str) -> SessionTokens:
        if not user.totp_secret_encrypted:
            raise Conflict("Start 2-step setup first", code="mfa_not_enrolled")
        self._check_totp(user, code)
        user.mfa_enabled = True
        return await self.issue_session(
            TokenClaims(user.id, Role.SHOP_USER, TokenType.ACCESS, user.shop_id)
        )

    async def complete_mfa_login(self, user: ShopUser, code: str) -> SessionTokens:
        self._check_totp(user, code)
        return await self.issue_session(
            TokenClaims(user.id, Role.SHOP_USER, TokenType.ACCESS, user.shop_id)
        )

    def _check_totp(self, user: ShopUser, code: str) -> None:
        secret = self.c.encryptor.decrypt(user.totp_secret_encrypted or "")
        if not verify_totp(secret, code, at=self.c.clock.now()):
            raise Unauthorized("That code isn't right", code="mfa_invalid")
