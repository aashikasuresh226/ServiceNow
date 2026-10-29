from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ContainerDep, SessionDep, ShopSetupDep
from app.core.errors import Forbidden, Unauthorized
from app.core.security import Role, TokenType
from app.models import ShopUser
from app.schemas.api import (
    HomeownerSessionOut,
    MfaCodeIn,
    MfaEnrollOut,
    MfaLoginIn,
    OtpStartIn,
    OtpStartOut,
    OtpVerifyIn,
    RefreshIn,
    ShopLoginIn,
    ShopLoginOut,
    ShopSignupIn,
    TokensOut,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Homeowners -----------------------------------------------------------------------------
@router.post("/homeowner/otp/start", response_model=OtpStartOut)
async def start_otp(body: OtpStartIn, session: SessionDep, c: ContainerDep) -> OtpStartOut:
    started = await AuthService(session, c).start_phone_otp(body.phone)
    return OtpStartOut(
        phone=started.phone,
        resend_after_seconds=started.resend_after_seconds,
        dev_code=started.dev_code,
    )


@router.post("/homeowner/otp/verify", response_model=HomeownerSessionOut)
async def verify_otp(
    body: OtpVerifyIn, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    _, tokens, needs_profile = await AuthService(session, c).verify_phone_otp(body.phone, body.code)
    return HomeownerSessionOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        needs_profile=needs_profile,
    )


# --- Sessions -----------------------------------------------------------------------------------
@router.post("/refresh", response_model=TokensOut)
async def refresh(body: RefreshIn, session: SessionDep, c: ContainerDep) -> TokensOut:
    tokens = await AuthService(session, c).refresh(body.refresh_token)
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshIn, session: SessionDep, c: ContainerDep) -> None:
    await AuthService(session, c).logout(body.refresh_token)


# --- Shops ----------------------------------------------------------------------------------------
@router.post("/shop/signup", response_model=ShopLoginOut, status_code=status.HTTP_201_CREATED)
async def shop_signup(body: ShopSignupIn, session: SessionDep, c: ContainerDep) -> ShopLoginOut:
    _, token = await AuthService(session, c).shop_signup(
        email=body.email, password=body.password, shop_name=body.shop_name, name=body.name
    )
    return ShopLoginOut(step="mfa_setup", token=token)


@router.post("/shop/login", response_model=ShopLoginOut)
async def shop_login(body: ShopLoginIn, session: SessionDep, c: ContainerDep) -> ShopLoginOut:
    service = AuthService(session, c)
    user, token, kind = await service.shop_login(email=body.email, password=body.password)
    step = "mfa" if kind == TokenType.MFA else "mfa_setup"
    return ShopLoginOut(
        step=step, token=token, dev_code=service.dev_totp_code(user) if step == "mfa" else None
    )


@router.post("/shop/mfa/enroll", response_model=MfaEnrollOut)
async def mfa_enroll(principal: ShopSetupDep, session: SessionDep, c: ContainerDep) -> MfaEnrollOut:
    service = AuthService(session, c)
    secret, uri = await service.enroll_mfa(principal.user)
    return MfaEnrollOut(
        secret=secret, otpauth_uri=uri, dev_code=service.dev_totp_code(principal.user)
    )


@router.post("/shop/mfa/activate", response_model=TokensOut)
async def mfa_activate(
    body: MfaCodeIn, principal: ShopSetupDep, session: SessionDep, c: ContainerDep
) -> TokensOut:
    tokens = await AuthService(session, c).activate_mfa(principal.user, body.code)
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post("/shop/login/mfa", response_model=TokensOut)
async def shop_login_mfa(body: MfaLoginIn, session: SessionDep, c: ContainerDep) -> TokensOut:
    claims = c.tokens.verify(body.token, expected_type=TokenType.MFA, now=c.clock.now())
    if claims.role != Role.SHOP_USER:
        raise Forbidden("Shop account required")
    user = await session.get(ShopUser, claims.subject_id)
    if user is None:
        raise Unauthorized("Account not found")
    tokens = await AuthService(session, c).complete_mfa_login(user, body.code)
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )
