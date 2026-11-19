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

from sqlalchemy import func, select, update
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
from app.integrations.google_auth import GoogleIdentity
from app.models import AuthNonce, Homeowner, PhoneOtp, RefreshToken, Shop, ShopUser, Technician
from app.services.email_check import check_email
from app.services.email_proof import EmailLink, EmailProofService
from app.services.phone import normalize_phone

APP_NAME = "HVAC Connect"
NONCE_TTL = timedelta(minutes=10)
# Per-IP ceilings (on top of the per-number limits stored in the database).
OTP_STARTS_PER_IP_PER_HOUR = 20
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

    # --- Phone one-time codes -----------------------------------------------------------
    def _normalize_allowed(self, raw_phone: str) -> str:
        phone = normalize_phone(raw_phone)
        allowed = self.settings.sms_allowed_country_codes
        if allowed and not any(phone.startswith(code) for code in allowed):
            raise AppError("We can only text US numbers right now", code="phone_not_supported")
        return phone

    async def start_phone_otp(self, raw_phone: str, *, ip: str | None = None) -> OtpStarted:
        phone = self._normalize_allowed(raw_phone)
        self.limit_ip(ip, "otp")
        now = self.c.clock.now()
        key = _phone_key(phone)
        latest = await self.s.scalar(
            select(PhoneOtp).where(PhoneOtp.phone == key).order_by(PhoneOtp.created_at.desc())
        )
        cooldown = self.settings.otp_resend_cooldown_seconds
        if latest and (wait := cooldown - (now - latest.created_at).total_seconds()) > 0:
            raise RateLimited(f"Please wait {int(wait) + 1} seconds before requesting a new code")
        sent_last_hour = await self.s.scalar(
            select(func.count())
            .select_from(PhoneOtp)
            .where(PhoneOtp.phone == key, PhoneOtp.created_at > now - timedelta(hours=1))
        )
        if (sent_last_hour or 0) >= self.settings.otp_max_per_hour:
            raise RateLimited("Too many codes requested. Please try again later.")

        record = PhoneOtp(
            phone=key,
            expires_at=now + timedelta(minutes=self.settings.otp_ttl_minutes),
            created_at=now,  # rate limits compare against the injected clock
        )
        dev_code: str | None = None
        if self.c.phone_verify is not None:
            await self.c.phone_verify.start(phone)  # Twilio generates and texts the code
        else:
            # Development without Twilio: generate locally, store only a keyed hash.
            dev_code = generate_otp_code()
            record.code_hash = hash_otp(
                dev_code, phone, self.settings.jwt_secret.get_secret_value()
            )
            if self.c.sms is not None:
                await self.c.sms.send(
                    to=phone, body=f"{dev_code} is your {APP_NAME} code. It expires in 10 minutes."
                )
        self.s.add(record)
        await self.s.flush()
        return OtpStarted(phone, cooldown, dev_code)

    async def _check_phone_code(self, phone: str, code: str) -> None:
        """Raises unless `code` is the current code for `phone`."""
        now = self.c.clock.now()
        code = code.strip()
        otp = await self.s.scalar(
            select(PhoneOtp)
            .where(
                PhoneOtp.phone == _phone_key(phone),
                PhoneOtp.consumed_at.is_(None),
                PhoneOtp.expires_at > now,
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
        if not code.isdigit() or len(code) != 6:
            await self.s.commit()
            raise Unauthorized("That code isn't right", code="otp_invalid")
        if self.c.phone_verify is not None and otp.code_hash is None:
            try:
                approved = await self.c.phone_verify.check(phone, code)
            except AppError as exc:
                if exc.code == "otp_expired":
                    otp.consumed_at = now
                    await self.s.commit()
                    raise Unauthorized(exc.message, code="otp_expired") from exc
                raise
        else:
            expected = hash_otp(code, phone, self.settings.jwt_secret.get_secret_value())
            approved = otp.code_hash is not None and constant_time_equals(expected, otp.code_hash)
        if not approved:
            await self.s.commit()  # persist the failed attempt before raising
            raise Unauthorized("That code isn't right", code="otp_invalid")
        otp.consumed_at = now

    async def verify_phone_otp(
        self, raw_phone: str, code: str, *, ip: str | None = None
    ) -> tuple[Homeowner, SessionTokens, bool]:
        self.limit_ip(ip)
        phone = self._normalize_allowed(raw_phone)
        await self._check_phone_code(phone, code)
        homeowner = await self.s.scalar(
            select(Homeowner).where(Homeowner.phone_hash == _phone_key(phone))
        )
        if homeowner is None:
            homeowner = Homeowner(phone=phone)
            self.s.add(homeowner)
            await self.s.flush()
        tokens = await self.issue_session(
            TokenClaims(homeowner.id, Role.HOMEOWNER, TokenType.ACCESS)
        )
        return homeowner, tokens, needs_profile(homeowner)

    async def start_add_phone(
        self, homeowner: Homeowner, raw_phone: str, *, ip: str | None = None
    ) -> OtpStarted:
        """Signed-in homeowner (e.g. via Google) adds a mobile number."""
        phone = self._normalize_allowed(raw_phone)
        await self._ensure_phone_free(homeowner, phone)
        return await self.start_phone_otp(phone, ip=ip)

    async def finish_add_phone(self, homeowner: Homeowner, raw_phone: str, code: str) -> Homeowner:
        phone = self._normalize_allowed(raw_phone)
        await self._ensure_phone_free(homeowner, phone)
        await self._check_phone_code(phone, code)
        homeowner.phone = phone
        await self.s.flush()
        return homeowner

    async def _ensure_phone_free(self, homeowner: Homeowner, phone: str) -> None:
        owner = await self.s.scalar(
            select(Homeowner.id).where(Homeowner.phone_hash == _phone_key(phone))
        )
        if owner is not None and owner != homeowner.id:
            raise Conflict(
                "This number belongs to another account. Sign out and continue with your "
                "phone number instead.",
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
        return await self._shop_step(user, send_email=False)

    async def verify_shop_email(self, token: str, firebase_id_token: str | None) -> ShopUser:
        proof = EmailProofService(self.s, self.c)
        claim = await proof.prove(token, "shop_email", firebase_id_token)
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

    async def verify_invite_email(self, token: str, firebase_id_token: str | None) -> str:
        await self.invite_info(token)
        return await EmailProofService(self.s, self.c).prove(
            token, "tech_invite", firebase_id_token
        )

    async def start_invite_phone(
        self, token: str, claim: str, raw_phone: str, *, ip: str | None
    ) -> OtpStarted:
        tech, *_ = await self.invite_info(token)
        proof = EmailProofService(self.s, self.c)
        proof.check_claim(await proof.get(token, "tech_invite"), claim)
        phone = self._normalize_allowed(raw_phone)
        await self._ensure_tech_phone_free(tech, phone)
        return await self.start_phone_otp(phone, ip=ip)

    async def accept_invite(
        self,
        token: str,
        claim: str,
        *,
        phone: str | None = None,
        code: str | None = None,
        google_id_token: str | None = None,
        ip: str | None = None,
    ) -> SessionTokens:
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
        elif phone and code:
            normalized = self._normalize_allowed(phone)
            await self._ensure_tech_phone_free(tech, normalized)
            await self._check_phone_code(normalized, code)
            tech.phone = normalized
        else:
            raise AppError("Choose how you'll sign in", code="missing_sign_in")
        await proof.consume(token, "tech_invite", claim)
        tech.email = email
        tech.app_status = "active"
        tech.joined_at = self.c.clock.now()
        await self.s.flush()
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
        )

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

    async def _active_tech_by_phone(self, phone: str) -> Technician:
        tech = await self.s.scalar(
            select(Technician).where(
                Technician.phone_hash == _phone_key(phone),
                Technician.app_status == "active",
                Technician.is_active.is_(True),
            )
        )
        if tech is None:
            raise NotFound(
                "No technician account uses this number. Ask your company to invite you.",
                code="no_technician_account",
            )
        return tech

    async def start_tech_otp(self, raw_phone: str, *, ip: str | None) -> OtpStarted:
        phone = self._normalize_allowed(raw_phone)
        self.limit_ip(ip, "otp")
        await self._active_tech_by_phone(phone)
        return await self.start_phone_otp(phone, ip=ip)

    async def verify_tech_otp(self, raw_phone: str, code: str, *, ip: str | None) -> SessionTokens:
        self.limit_ip(ip)
        phone = self._normalize_allowed(raw_phone)
        tech = await self._active_tech_by_phone(phone)
        await self._check_phone_code(phone, code)
        return await self.issue_session(
            TokenClaims(tech.id, Role.TECHNICIAN, TokenType.ACCESS, tech.shop_id)
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
