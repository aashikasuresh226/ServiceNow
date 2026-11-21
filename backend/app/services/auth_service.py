"""Authentication.

Homeowners: "Continue with Google" or a one-time code texted to their phone
(Twilio Verify). Google users then verify a phone number too, so technicians
can reach them.
Shop users: "Continue with Google" or email + password (the email is proven with a
link first), always followed by a mandatory authenticator-app code (TOTP).
Technicians: invited by their company by email; they prove the email, then sign in
with a texted code or Google.
All sessions use short-lived access tokens + rotating refresh tokens.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core import passwords
from app.core.config import Environment
from app.core.errors import AppError, Conflict, Forbidden, NotFound, RateLimited, Unauthorized
from app.core.fieldcrypt import blind_index
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    Role,
    TokenClaims,
    TokenType,
    hash_password,
    hash_token,
    new_refresh_token,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.integrations.google_auth import GoogleIdentity
from app.models import AuthNonce, Homeowner, RefreshToken, Shop, ShopUser, Technician
from app.services import authenticator
from app.services.customer_service import CustomerService
from app.services.email_check import check_email
from app.services.email_proof import EmailLink, EmailProofService
from app.services.phone import normalize_phone

APP_NAME = "HVAC Connect"
NONCE_TTL = timedelta(minutes=10)
# Per-IP ceilings (on top of the per-number limits stored in the database).
OTP_STARTS_PER_IP_PER_HOUR = 20
EMAIL_LINKS_PER_ACCOUNT_PER_HOUR = 5
# A new homeowner's sign-up link is tied to their phone number through this namespace.
_SIGNUP_NS = uuid.UUID("6b0b3f4e-8a52-4d0c-9c1e-2f1b7d0e5a11")


def mask_email(email: str) -> str:
    """j***@gmail.com: enough to recognise, not enough to read off a screen."""
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}" if domain else "***"


SIGN_IN_ATTEMPTS_PER_IP_PER_15_MIN = 50


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class ShopStep:
    """Where a shop user is in sign-up / sign-in: verify_email -> mfa_setup | mfa."""

    step: str
    token: str
    email_link: EmailLink | None = None


@dataclass(frozen=True, slots=True)
class OtpStarted:
    phone: str
    resend_after_seconds: int
    dev_code: str | None  # only when Twilio isn't set up (development): shown on screen


@dataclass(frozen=True, slots=True)
class HomeownerStart:
    account: str  # existing | new
    setup: authenticator.Setup | None  # new: an authenticator to set up (or choose email)
    method: str | None  # existing: authenticator | email
    email_hint: str | None  # existing email accounts: j***@gmail.com


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
            if user is None or not user.mfa_enabled or user.email_verified_at is None:
                raise Unauthorized("Please sign in again", code="session_ended")
            shop_id = user.shop_id
        elif role == Role.TECHNICIAN:
            tech = await self.s.get(Technician, stored.subject_id)
            if tech is None or tech.app_status != "active" or not tech.is_active:
                raise Unauthorized("Please sign in again", code="session_ended")
            shop_id = tech.shop_id
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

    async def _revoke_all(self, subject_id: uuid.UUID) -> None:
        """Signs the account out everywhere (after a password reset or account recovery)."""
        await self.s.execute(
            update(RefreshToken)
            .where(RefreshToken.subject_id == subject_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=self.c.clock.now())
        )

    def _limit_account(self, key: str) -> None:
        self.c.rate_limiter.check(
            "email_link", key, limit=EMAIL_LINKS_PER_ACCOUNT_PER_HOUR, window_seconds=3600
        )

    # --- Recovery ---------------------------------------------------------------------
    # Homeowners and technicians have no password; "forgot password" for them means a
    # lost authenticator. A link to the account's verified email removes the authenticator
    # (they sign in with email links from then on) and signs them out everywhere else.
    async def homeowner_recover_start(self, raw_phone: str, *, ip: str | None) -> EmailLink:
        self.limit_ip(ip, "otp")
        phone = self._normalize_allowed(raw_phone)
        homeowner = await self._homeowner_by_phone(phone)
        if homeowner is None or not homeowner.totp_secret_encrypted or not homeowner.email:
            raise Conflict(
                "There's no email on this account to send a recovery link to. Use one of your "
                "backup codes, or contact support.",
                code="no_recovery_email",
            )
        self._limit_account(f"homeowner:{homeowner.id}")
        return await EmailProofService(self.s, self.c).start(
            purpose="homeowner_recovery",
            subject_id=homeowner.id,
            email=homeowner.email,
            page_url=f"{self.settings.public_app_url.rstrip('/')}/email-sign-in?r=1",
        )

    async def homeowner_recover_finish(
        self, token: str, *, ip: str | None
    ) -> tuple[Homeowner, SessionTokens, bool]:
        self.limit_ip(ip)
        challenge = await EmailProofService(self.s, self.c).redeem(token, "homeowner_recovery")
        homeowner = await self.s.get(Homeowner, challenge.subject_id)
        if homeowner is None:
            raise NotFound("This account no longer exists")
        homeowner.totp_secret_encrypted = None
        homeowner.backup_codes = None
        await self._revoke_all(homeowner.id)
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner)

    async def tech_recover_start(self, login: str, *, ip: str | None) -> EmailLink | None:
        """Same answer whether or not the account exists (None: nothing sent)."""
        self.limit_ip(ip, "otp")
        tech = await self._tech_by_login(login)
        if tech is None or not tech.totp_secret_encrypted or not tech.email:
            return None
        self._limit_account(f"tech:{tech.id}")
        return await EmailProofService(self.s, self.c).start(
            purpose="tech_recovery",
            subject_id=tech.id,
            email=tech.email,
            page_url=f"{self.settings.public_app_url.rstrip('/')}/tech/email-sign-in?r=1",
        )

    async def tech_recover_finish(self, token: str, *, ip: str | None) -> SessionTokens:
        self.limit_ip(ip)
        challenge = await EmailProofService(self.s, self.c).redeem(token, "tech_recovery")
        tech = await self.s.get(Technician, challenge.subject_id)
        if tech is None or tech.app_status != "active" or not tech.is_active:
            raise Forbidden("This technician account can't sign in. Ask your company.")
        tech.totp_secret_encrypted = None
        tech.backup_codes = None
        await self._revoke_all(tech.id)
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )

    async def shop_forgot_password(self, email: str, *, ip: str | None) -> EmailLink | None:
        """Same answer whether or not the account exists (None: nothing sent)."""
        self.limit_ip(ip, "otp")
        address = email.strip().lower()
        user = await self.s.scalar(select(ShopUser).where(ShopUser.email == address))
        if user is None:
            return None
        self._limit_account(f"shop:{user.id}")
        return await EmailProofService(self.s, self.c).start(
            purpose="shop_password_reset",
            subject_id=user.id,
            email=user.email,
            page_url=f"{self.settings.public_web_url.rstrip('/')}/reset-password",
        )

    async def shop_reset_password(self, token: str, password: str, *, ip: str | None) -> None:
        """New password. 2-step verification still applies at the next sign-in."""
        self.limit_ip(ip)
        proof = EmailProofService(self.s, self.c)
        challenge = await proof.get(token, "shop_password_reset")
        await passwords.ensure_strong(
            password,
            http=self.c.http,
            check_breaches=self.settings.password_breach_check
            and self.settings.environment != Environment.TEST,
        )
        await proof.redeem(token, "shop_password_reset")
        user = await self.s.get(ShopUser, challenge.subject_id)
        if user is None:
            raise NotFound("This account no longer exists")
        user.password_hash = hash_password(password)
        if user.email_verified_at is None:
            user.email_verified_at = self.c.clock.now()  # the link proved the address
        await self._revoke_all(user.id)
        await self.s.flush()

    async def change_shop_password(
        self, user: ShopUser, current: str | None, new: str, *, ip: str | None
    ) -> SessionTokens:
        """Signed in: change the password (or set one after Google sign-up). Signs out every
        other session and returns fresh tokens for this one."""
        self.limit_ip(ip)
        if user.password_hash:
            self.c.rate_limiter.check("password", str(user.id), limit=10, window_seconds=900)
            if not current or not verify_password(current, user.password_hash):
                raise Unauthorized("Your current password isn't right", code="bad_password")
            if verify_password(new, user.password_hash):
                raise AppError("Choose a password you haven't used here", code="same_password")
        await passwords.ensure_strong(
            new,
            http=self.c.http,
            check_breaches=self.settings.password_breach_check
            and self.settings.environment != Environment.TEST,
        )
        user.password_hash = hash_password(new)
        await self._revoke_all(user.id)
        await self.s.flush()
        return await self.issue_session(
            TokenClaims(user.id, Role.SHOP_USER, TokenType.ACCESS, user.shop_id)
        )

    # --- Rate limiting ----------------------------------------------------------------
    def limit_ip(self, ip: str | None, bucket: str = "sign_in") -> None:
        if not ip:
            return
        if bucket == "otp":
            self.c.rate_limiter.check(
                "otp", ip, limit=OTP_STARTS_PER_IP_PER_HOUR, window_seconds=3600
            )
        else:
            self.c.rate_limiter.check(
                "sign_in", ip, limit=SIGN_IN_ATTEMPTS_PER_IP_PER_15_MIN, window_seconds=900
            )

    # --- Homeowners: phone number + authenticator app ---------------------------------
    def _normalize_allowed(self, raw_phone: str) -> str:
        phone = normalize_phone(raw_phone)
        allowed = self.settings.sms_allowed_country_codes
        if allowed and not any(phone.startswith(code) for code in allowed):
            raise AppError("Only US numbers for now", code="phone_not_supported")
        return phone

    async def homeowner_start(self, raw_phone: str, *, ip: str | None = None) -> HomeownerStart:
        """Existing account: how it signs in (authenticator code, or an emailed link).
        New: an authenticator setup, or they can choose email instead."""
        self.limit_ip(ip, "otp")  # per-IP cap on starts (number lookups)
        phone = self._normalize_allowed(raw_phone)
        homeowner = await self._homeowner_by_phone(phone)
        if homeowner is not None and homeowner.totp_secret_encrypted:
            return HomeownerStart("existing", None, "authenticator", None)
        if homeowner is not None and homeowner.email:
            return HomeownerStart("existing", None, "email", mask_email(homeowner.email))
        if homeowner is not None and self.settings.environment == Environment.PROD:
            # An account from before authenticator sign-in: we can't prove it's theirs.
            if homeowner.google_sub:
                raise Conflict("Sign in with Google for this account.", code="use_google")
            raise Conflict(
                "This number already has an account. Contact support to reset its sign-in.",
                code="needs_reset",
            )
        setup = authenticator.start(self.c, account=phone, subject=f"homeowner:{phone}")
        return HomeownerStart("new", setup, None, None)

    # --- Homeowners: phone number + emailed sign-in link (no authenticator app) ---------
    async def homeowner_email_start(
        self, raw_phone: str, email: str | None, *, ip: str | None = None
    ) -> EmailLink:
        """Existing email accounts: a link to the address on the account (whatever was
        typed). New: a link to the address they typed; the account is created only when
        it's opened."""
        self.limit_ip(ip, "otp")
        phone = self._normalize_allowed(raw_phone)
        self.c.rate_limiter.check(
            "email_link",
            _phone_key(phone),
            limit=EMAIL_LINKS_PER_ACCOUNT_PER_HOUR,
            window_seconds=3600,
        )
        page = f"{self.settings.public_app_url.rstrip('/')}/email-sign-in"
        proof = EmailProofService(self.s, self.c)
        homeowner = await self._homeowner_by_phone(phone)
        if homeowner is not None and homeowner.totp_secret_encrypted:
            raise Conflict(
                "This account signs in with an authenticator app. Lost your phone? Use a "
                "backup code.",
                code="use_authenticator",
            )
        if homeowner is not None and homeowner.email:
            return await proof.start(
                purpose="homeowner_sign_in",
                subject_id=homeowner.id,
                email=homeowner.email,
                page_url=page,
            )
        if homeowner is not None and self.settings.environment == Environment.PROD:
            raise Conflict(
                "This number already has an account. Contact support to reset its sign-in.",
                code="needs_reset",
            )
        if not email:
            raise AppError("Enter your email address", code="email_required")
        address = email.strip().lower()
        await self._ensure_email_free(address)
        return await proof.start(
            purpose="homeowner_sign_in",
            subject_id=uuid.uuid5(_SIGNUP_NS, _phone_key(phone)),
            email=address,
            page_url=f"{page}?p={phone.lstrip('+')}",
        )

    async def homeowner_email_finish(
        self, token: str, raw_phone: str | None, *, ip: str | None = None
    ) -> tuple[Homeowner, SessionTokens, bool]:
        self.limit_ip(ip)
        challenge = await EmailProofService(self.s, self.c).redeem(token, "homeowner_sign_in")
        homeowner = await self.s.get(Homeowner, challenge.subject_id)
        if homeowner is None:
            # A new account: the link names the phone number it was asked for.
            phone = self._normalize_allowed("+" + (raw_phone or "").lstrip("+"))
            if uuid.uuid5(_SIGNUP_NS, _phone_key(phone)) != challenge.subject_id:
                raise Unauthorized("This link isn't valid", code="link_invalid")
            if await self._homeowner_by_phone(phone) is not None:
                raise Conflict("This number already has an account: sign in.", code="exists")
            await self._ensure_email_free(challenge.email)
            homeowner = Homeowner(phone=phone, email=challenge.email)
            self.s.add(homeowner)
            await self.s.flush()
        elif homeowner.totp_secret_encrypted:
            raise Unauthorized("This account signs in with an authenticator app")
        await CustomerService(self.s, self.c).link_homeowner(homeowner)
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner)

    async def homeowner_add_email(self, homeowner: Homeowner, email: str) -> EmailLink:
        """A recovery email (for authenticator users): saved once its link is opened."""
        address = email.strip().lower()
        await self._ensure_email_free(address, homeowner.id)
        self._limit_account(f"homeowner:{homeowner.id}")
        return await EmailProofService(self.s, self.c).start(
            purpose="homeowner_email",
            subject_id=homeowner.id,
            email=address,
            page_url=f"{self.settings.public_app_url.rstrip('/')}/email-sign-in?c=1",
        )

    async def homeowner_confirm_email(self, token: str, *, ip: str | None) -> str:
        self.limit_ip(ip)
        challenge = await EmailProofService(self.s, self.c).redeem(token, "homeowner_email")
        homeowner = await self.s.get(Homeowner, challenge.subject_id)
        if homeowner is None:
            raise NotFound("This account no longer exists")
        await self._ensure_email_free(challenge.email, homeowner.id)
        homeowner.email = challenge.email
        await CustomerService(self.s, self.c).link_homeowner(homeowner)
        await self.s.flush()
        return challenge.email

    async def _ensure_email_free(self, email: str, owner: uuid.UUID | None = None) -> None:
        other = await self.s.scalar(
            select(Homeowner.id).where(Homeowner.email_hash == blind_index("email", email))
        )
        if other is not None and other != owner:
            raise Conflict(
                "This email is already used by another account. Sign in with that account's "
                "phone number, or with Google.",
                code="email_taken",
            )

    async def homeowner_signup(
        self, raw_phone: str, setup_token: str, code: str, *, ip: str | None = None
    ) -> tuple[Homeowner, SessionTokens, bool, list[str]]:
        self.limit_ip(ip)
        phone = self._normalize_allowed(raw_phone)
        secret = authenticator.finish(self.c, setup_token, code, subject=f"homeowner:{phone}")
        homeowner = await self._homeowner_by_phone(phone)
        if homeowner is not None and homeowner.totp_secret_encrypted:
            raise Conflict("This number already has an account: sign in instead.", code="exists")
        if homeowner is not None and self.settings.environment == Environment.PROD:
            raise Conflict("This number already has an account.", code="needs_reset")
        if homeowner is None:
            homeowner = Homeowner(phone=phone)
            self.s.add(homeowner)
        codes, hashes = authenticator.new_backup_codes()
        homeowner.totp_secret_encrypted = self.c.encryptor.encrypt(secret)
        homeowner.backup_codes = hashes
        await self.s.flush()
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner), codes

    async def homeowner_login(
        self, raw_phone: str, code: str, *, ip: str | None = None
    ) -> tuple[Homeowner, SessionTokens, bool]:
        self.limit_ip(ip)
        phone = self._normalize_allowed(raw_phone)
        homeowner = await self._homeowner_by_phone(phone)
        if homeowner is None or not homeowner.totp_secret_encrypted:
            raise Unauthorized("That code isn't right", code="mfa_invalid")
        updated = authenticator.check(
            self.c,
            secret_encrypted=homeowner.totp_secret_encrypted,
            backup_codes=homeowner.backup_codes,
            code=code,
            key=f"homeowner:{homeowner.id}",
        )
        if updated is not None:
            homeowner.backup_codes = updated
        await CustomerService(self.s, self.c).link_homeowner(homeowner)
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner)

    async def _homeowner_by_phone(self, phone: str) -> Homeowner | None:
        return await self.s.scalar(
            select(Homeowner).where(Homeowner.phone_hash == _phone_key(phone))
        )

    async def set_phone(self, homeowner: Homeowner, raw_phone: str) -> Homeowner:
        """A Google user adds their mobile number (for the company to call; not texted)."""
        phone = self._normalize_allowed(raw_phone)
        await self._ensure_phone_free(homeowner, phone)
        if phone != homeowner.phone:
            homeowner.phone = phone
            homeowner.phone_verified = False
        await self.s.flush()
        return homeowner

    async def _ensure_phone_free(self, homeowner: Homeowner, phone: str) -> None:
        owner = await self.s.scalar(
            select(Homeowner.id).where(Homeowner.phone_hash == _phone_key(phone))
        )
        if owner is not None and owner != homeowner.id:
            raise Conflict(
                "This number belongs to another account. Sign out and sign in with your "
                "phone number and authenticator instead.",
                code="phone_taken",
            )

    # --- Sign in with Google ------------------------------------------------------------
    async def new_google_nonce(self) -> str:
        if self.c.google is None:
            raise NotFound("Google sign-in isn't set up", code="google_not_configured")
        nonce = new_refresh_token()
        self.s.add(
            AuthNonce(nonce_hash=hash_token(nonce), expires_at=self.c.clock.now() + NONCE_TTL)
        )
        await self.s.flush()
        return nonce

    async def _verify_google(self, id_token: str) -> GoogleIdentity:
        if self.c.google is None:
            raise NotFound("Google sign-in isn't set up", code="google_not_configured")
        identity = await self.c.google.verify(id_token)
        now = self.c.clock.now()
        record = (
            await self.s.scalar(
                select(AuthNonce).where(AuthNonce.nonce_hash == hash_token(identity.nonce))
            )
            if identity.nonce
            else None
        )
        if record is None or record.used_at is not None or record.expires_at <= now:
            raise Unauthorized("Google sign-in expired. Please try again.", code="bad_nonce")
        record.used_at = now
        return identity

    async def google_homeowner(
        self, id_token: str, *, ip: str | None = None
    ) -> tuple[Homeowner, SessionTokens, bool]:
        self.limit_ip(ip)
        identity = await self._verify_google(id_token)
        homeowner = await self.s.scalar(
            select(Homeowner).where(Homeowner.google_sub == identity.subject)
        )
        if homeowner is None:
            homeowner = await self.s.scalar(
                select(Homeowner).where(
                    Homeowner.email_hash == blind_index("email", identity.email)
                )
            )
            if homeowner is not None and homeowner.google_sub not in (None, identity.subject):
                raise Conflict("This email is linked to another Google account", code="email_taken")
        if homeowner is None:
            homeowner = Homeowner(name=identity.name)
            self.s.add(homeowner)
        homeowner.google_sub = identity.subject
        homeowner.email = identity.email
        if not homeowner.name and identity.name:
            homeowner.name = identity.name
        await self.s.flush()
        await CustomerService(self.s, self.c).link_homeowner(homeowner)
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner)

    async def google_shop(
        self, id_token: str, *, shop_name: str | None, ip: str | None = None
    ) -> ShopStep:
        """Google sign-in for shops. Still requires the authenticator-app code afterwards."""
        self.limit_ip(ip)
        identity = await self._verify_google(id_token)
        user = await self.s.scalar(select(ShopUser).where(ShopUser.google_sub == identity.subject))
        if user is None:
            user = await self.s.scalar(select(ShopUser).where(ShopUser.email == identity.email))
            if user is not None:
                if user.google_sub not in (None, identity.subject):
                    raise Conflict(
                        "This email is linked to another Google account", code="email_taken"
                    )
                user.google_sub = identity.subject
        if user is None:
            if not shop_name or not shop_name.strip():
                raise NotFound(
                    "No shop account uses this Google account yet. Create one first.",
                    code="no_shop_account",
                )
            shop = Shop(name=shop_name.strip()[:160])
            self.s.add(shop)
            await self.s.flush()
            user = ShopUser(
                shop_id=shop.id,
                email=identity.email,
                google_sub=identity.subject,
                name=identity.name,
            )
            self.s.add(user)
        # Google verified this email address.
        user.email_verified_at = user.email_verified_at or self.c.clock.now()
        await self.s.flush()
        return await self._shop_step(user)

    # --- Shop users: password + TOTP ------------------------------------------------
    async def shop_signup(
        self, *, email: str, password: str, shop_name: str, name: str | None
    ) -> ShopStep:
        email = await check_email(email, check_dns=self.settings.environment != Environment.TEST)
        await passwords.ensure_strong(
            password,
            http=self.c.http,
            check_breaches=self.settings.password_breach_check
            and self.settings.environment != Environment.TEST,
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
        return await self._shop_step(user)

    async def shop_login(self, *, email: str, password: str, ip: str | None = None) -> ShopStep:
        self.limit_ip(ip)
        user = await self.s.scalar(select(ShopUser).where(ShopUser.email == email.strip().lower()))
        # Verify against a dummy hash when the user doesn't exist, so response
        # timing doesn't reveal which emails have accounts.
        stored = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
        ok = verify_password(password, stored)
        if user is None or not user.password_hash or not ok:
            raise Unauthorized("Email or password is incorrect", code="bad_credentials")
        return await self._shop_step(user)

    async def _shop_step(self, user: ShopUser, *, send_email: bool = True) -> ShopStep:
        """Next step for a shop user who passed the first factor (password or Google)."""
        if user.email_verified_at is None:
            link = (
                await EmailProofService(self.s, self.c).start(
                    purpose="shop_email",
                    subject_id=user.id,
                    email=user.email,
                    page_url=f"{self.settings.public_web_url}/verify-email",
                )
                if send_email
                else None
            )
            return ShopStep("verify_email", self._limited_token(user, TokenType.MFA_SETUP), link)
        if user.mfa_enabled:
            return ShopStep("mfa", self._limited_token(user, TokenType.MFA))
        return ShopStep("mfa_setup", self._limited_token(user, TokenType.MFA_SETUP))

    async def resend_shop_email(self, user: ShopUser) -> ShopStep:
        self.c.rate_limiter.check("email_link", str(user.id), limit=5, window_seconds=3600)
        return await self._shop_step(user)

    async def shop_setup_status(self, user: ShopUser) -> ShopStep:
        """Polled by the sign-up tab while the person opens the email link elsewhere."""
        if user.email_verified_at is None and self._may_ask_firebase(user):
            proof = EmailProofService(self.s, self.c)
            challenge = await proof.verified_elsewhere(user.id, "shop_email")
            if challenge is not None and challenge.email == user.email:
                user.email_verified_at = self.c.clock.now()
        return await self._shop_step(user, send_email=False)

    def _may_ask_firebase(self, user: ShopUser) -> bool:
        """The waiting tab polls every few seconds; ask Firebase at most every 10 s."""
        try:
            self.c.rate_limiter.check("firebase_poll", str(user.id), limit=1, window_seconds=10)
        except RateLimited:
            return False
        return True

    async def verify_shop_email(self, token: str) -> ShopUser:
        proof = EmailProofService(self.s, self.c)
        claim = await proof.prove(token, "shop_email")
        challenge = await proof.consume(token, "shop_email", claim)
        user = await self.s.get(ShopUser, challenge.subject_id)
        if user is None or user.email != challenge.email:
            raise NotFound("This account no longer exists")
        user.email_verified_at = self.c.clock.now()
        return user

    def _limited_token(self, user: ShopUser, kind: TokenType) -> str:
        ttl = timedelta(
            minutes=self.settings.mfa_token_ttl_minutes if kind == TokenType.MFA else 30
        )
        return self.c.tokens.issue(
            TokenClaims(user.id, Role.SHOP_USER, kind, user.shop_id),
            now=self.c.clock.now(),
            ttl=ttl,
        )

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
        # Brute-force guard: the 6-digit space is small, so cap guesses per account.
        self.c.rate_limiter.check("totp", str(user.id), limit=10, window_seconds=900)
        secret = self.c.encryptor.decrypt(user.totp_secret_encrypted or "")
        if not verify_totp(secret, code, at=self.c.clock.now()):
            raise Unauthorized("That code isn't right", code="mfa_invalid")

    # --- Technicians ----------------------------------------------------------------------
    async def invite_info(self, token: str) -> tuple[Technician, Shop, str, bool]:
        challenge = await EmailProofService(self.s, self.c).get(token, "tech_invite")
        tech = await self.s.get(Technician, challenge.subject_id)
        if tech is None or tech.app_status not in ("invited", "active") or not tech.is_active:
            raise NotFound("This invite was canceled. Ask your company for a new one.")
        shop = await self.s.get(Shop, tech.shop_id)
        assert shop is not None
        return tech, shop, challenge.email, challenge.verified_at is not None

    async def verify_invite_email(self, token: str) -> str:
        await self.invite_info(token)
        return await EmailProofService(self.s, self.c).prove(token, "tech_invite")

    async def invite_authenticator(self, token: str, claim: str) -> authenticator.Setup:
        tech, *_ = await self.invite_info(token)
        proof = EmailProofService(self.s, self.c)
        proof.check_claim(await proof.get(token, "tech_invite"), claim)
        return authenticator.start(
            self.c, account=tech.phone or tech.name, subject=f"tech:{tech.id}"
        )

    async def accept_invite(
        self,
        token: str,
        claim: str,
        *,
        phone: str | None = None,
        setup_token: str | None = None,
        code: str | None = None,
        google_id_token: str | None = None,
        email_sign_in: bool = False,
        ip: str | None = None,
    ) -> tuple[SessionTokens, list[str]]:
        self.limit_ip(ip)
        tech, _shop, email, _ = await self.invite_info(token)
        proof = EmailProofService(self.s, self.c)
        proof.check_claim(await proof.get(token, "tech_invite"), claim)
        if google_id_token:
            identity = await self._verify_google(google_id_token)
            if identity.email != email.lower():
                raise Unauthorized(
                    f"Use the Google account for {email}, the address you were invited at.",
                    code="email_mismatch",
                )
            other = await self.s.scalar(
                select(Technician.id).where(Technician.google_sub == identity.subject)
            )
            if other is not None and other != tech.id:
                raise Conflict("This Google account is already used by another technician")
            tech.google_sub = identity.subject
        elif setup_token and code:
            secret = authenticator.finish(self.c, setup_token, code, subject=f"tech:{tech.id}")
            tech.totp_secret_encrypted = self.c.encryptor.encrypt(secret)
        elif not email_sign_in:
            raise AppError("Choose how you'll sign in", code="missing_sign_in")
        # email_sign_in: no authenticator; they sign in with a link sent to this address.
        if phone:
            normalized = self._normalize_allowed(phone)
            await self._ensure_tech_phone_free(tech, normalized)
            tech.phone = normalized
        codes: list[str] = []
        if tech.totp_secret_encrypted:
            codes, tech.backup_codes = authenticator.new_backup_codes()
        await proof.consume(token, "tech_invite", claim)
        tech.email = email
        tech.app_status = "active"
        tech.joined_at = self.c.clock.now()
        await self.s.flush()
        tokens = await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )
        return tokens, codes

    async def _ensure_tech_phone_free(self, tech: Technician, phone: str) -> None:
        other = await self.s.scalar(
            select(Technician.id).where(
                Technician.phone_hash == _phone_key(phone),
                Technician.app_status == "active",
                Technician.id != tech.id,
            )
        )
        if other is not None:
            raise Conflict("Another technician account uses this number", code="phone_taken")

    async def tech_login(self, login: str, code: str, *, ip: str | None) -> SessionTokens:
        """Phone number or email, plus the authenticator code (or a backup code)."""
        self.limit_ip(ip)
        login = login.strip()
        if "@" in login:
            condition = Technician.email_hash == blind_index("email", login.lower())
        else:
            condition = Technician.phone_hash == _phone_key(self._normalize_allowed(login))
        tech = await self.s.scalar(
            select(Technician).where(
                condition, Technician.app_status == "active", Technician.is_active.is_(True)
            )
        )
        if tech is None or not tech.totp_secret_encrypted:
            raise Unauthorized(
                "That code isn't right, or there's no technician account for this. Ask your "
                "company to invite you.",
                code="mfa_invalid",
            )
        updated = authenticator.check(
            self.c,
            secret_encrypted=tech.totp_secret_encrypted,
            backup_codes=tech.backup_codes,
            code=code,
            key=f"tech:{tech.id}",
        )
        if updated is not None:
            tech.backup_codes = updated
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )

    async def tech_email_start(self, login: str, *, ip: str | None) -> EmailLink | None:
        """A sign-in link for a technician who chose email instead of an authenticator.
        The answer doesn't say whether the account exists (None: nothing sent)."""
        self.limit_ip(ip, "otp")
        tech = await self._tech_by_login(login)
        if tech is None or tech.totp_secret_encrypted or not tech.email:
            return None
        self.c.rate_limiter.check(
            "email_link",
            f"tech:{tech.id}",
            limit=EMAIL_LINKS_PER_ACCOUNT_PER_HOUR,
            window_seconds=3600,
        )
        return await EmailProofService(self.s, self.c).start(
            purpose="tech_sign_in",
            subject_id=tech.id,
            email=tech.email,
            page_url=f"{self.settings.public_app_url.rstrip('/')}/tech/email-sign-in",
        )

    async def tech_email_finish(self, token: str, *, ip: str | None) -> SessionTokens:
        self.limit_ip(ip)
        challenge = await EmailProofService(self.s, self.c).redeem(token, "tech_sign_in")
        tech = await self.s.get(Technician, challenge.subject_id)
        if (
            tech is None
            or tech.app_status != "active"
            or not tech.is_active
            or tech.totp_secret_encrypted
        ):
            raise Forbidden("This technician account can't sign in. Ask your company.")
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )

    async def _tech_by_login(self, login: str) -> Technician | None:
        login = login.strip()
        if "@" in login:
            condition = Technician.email_hash == blind_index("email", login.lower())
        else:
            try:
                condition = Technician.phone_hash == _phone_key(self._normalize_allowed(login))
            except AppError:
                return None
        return await self.s.scalar(
            select(Technician).where(
                condition, Technician.app_status == "active", Technician.is_active.is_(True)
            )
        )

    async def google_tech(self, id_token: str, *, ip: str | None) -> SessionTokens:
        self.limit_ip(ip)
        identity = await self._verify_google(id_token)
        tech = await self.s.scalar(
            select(Technician).where(Technician.google_sub == identity.subject)
        )
        if tech is None or tech.app_status != "active" or not tech.is_active:
            raise Forbidden(
                "No technician account uses this Google account. Ask your company to invite you.",
                code="no_technician_account",
            )
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )


def _phone_key(phone: str) -> str:
    key = blind_index("phone", phone)
    assert key is not None
    return key


def needs_profile(homeowner: Homeowner) -> bool:
    return not (homeowner.name and homeowner.address and homeowner.phone)
