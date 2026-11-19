from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.api.deps import ContainerDep, SessionDep, ShopSetupDep, client_ip
from app.core.errors import Forbidden, Unauthorized
from app.core.security import Role, TokenType
from app.models import ShopUser
from app.schemas.api import (
    ClaimOut,
    EmailLinkOut,
    EmailProofIn,
    EmailProofInfoOut,
    GoogleHomeownerIn,
    GoogleShopIn,
    HomeownerSessionOut,
    InviteAcceptIn,
    InviteInfoOut,
    InvitePhoneIn,
    MfaCodeIn,
    MfaEnrollOut,
    MfaLoginIn,
    NonceOut,
    OtpStartIn,
    OtpStartOut,
    OtpVerifyIn,
    RefreshIn,
    ShopLoginIn,
    ShopLoginOut,
    ShopSignupIn,
    TokensOut,
)
from app.services.auth_service import AuthService, SessionTokens, ShopStep
from app.services.email_proof import EmailProofService

router = APIRouter(prefix="/auth", tags=["auth"])


def _step(step: ShopStep) -> ShopLoginOut:
    link = step.email_link
    return ShopLoginOut(
        step=step.step,
        token=step.token,
        email_link=EmailLinkOut(
            email=link.email,
            continue_url=link.continue_url,
            delivery=link.delivery,
            dev_link=link.dev_link,
        )
        if link
        else None,
    )


def _tokens(tokens: SessionTokens) -> TokensOut:
    return TokensOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


# --- Homeowners -----------------------------------------------------------------------------
@router.post("/homeowner/otp/start", response_model=OtpStartOut)
async def start_otp(
    body: OtpStartIn, request: Request, session: SessionDep, c: ContainerDep
) -> OtpStartOut:
    started = await AuthService(session, c).start_phone_otp(body.phone, ip=client_ip(request))
    return OtpStartOut(
        phone=started.phone,
        resend_after_seconds=started.resend_after_seconds,
        dev_code=started.dev_code,
    )


@router.post("/homeowner/otp/verify", response_model=HomeownerSessionOut)
async def verify_otp(
    body: OtpVerifyIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    _, tokens, needs_profile = await AuthService(session, c).verify_phone_otp(
        body.phone, body.code, ip=client_ip(request)
    )
    return HomeownerSessionOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        needs_profile=needs_profile,
    )


# --- Sign in with Google ---------------------------------------------------------------------
@router.post("/google/nonce", response_model=NonceOut)
async def google_nonce(session: SessionDep, c: ContainerDep) -> NonceOut:
    """A single-use value the browser passes to Google; the ID token must carry it back."""
    return NonceOut(nonce=await AuthService(session, c).new_google_nonce())


@router.post("/homeowner/google", response_model=HomeownerSessionOut)
async def homeowner_google(
    body: GoogleHomeownerIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    _, tokens, needs_profile = await AuthService(session, c).google_homeowner(
        body.id_token, ip=client_ip(request)
    )
    return HomeownerSessionOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
        needs_profile=needs_profile,
    )


@router.post("/shop/google", response_model=ShopLoginOut)
async def shop_google(
    body: GoogleShopIn, request: Request, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    return _step(
        await AuthService(session, c).google_shop(
            body.id_token, shop_name=body.shop_name, ip=client_ip(request)
        )
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
async def shop_signup(
    body: ShopSignupIn, request: Request, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    service = AuthService(session, c)
    service.limit_ip(client_ip(request))
    return _step(
        await service.shop_signup(
            email=body.email, password=body.password, shop_name=body.shop_name, name=body.name
        )
    )


@router.post("/shop/login", response_model=ShopLoginOut)
async def shop_login(
    body: ShopLoginIn, request: Request, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    return _step(
        await AuthService(session, c).shop_login(
            email=body.email, password=body.password, ip=client_ip(request)
        )
    )


@router.get("/shop/setup-status", response_model=ShopLoginOut)
async def shop_setup_status(
    principal: ShopSetupDep, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    """The sign-up tab polls this while the email link is opened (maybe on another device)."""
    return _step(await AuthService(session, c).shop_setup_status(principal.user))


@router.post("/shop/resend-email", response_model=ShopLoginOut)
async def shop_resend_email(
    principal: ShopSetupDep, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    return _step(await AuthService(session, c).resend_shop_email(principal.user))


@router.get("/email-proof/{token}", response_model=EmailProofInfoOut)
async def email_proof_info(token: str, session: SessionDep, c: ContainerDep) -> EmailProofInfoOut:
    """The page opened from an emailed link needs the address to finish Firebase sign-in."""
    challenge = await EmailProofService(session, c).get(token)
    return EmailProofInfoOut(email=challenge.email, purpose=challenge.purpose)


@router.post("/shop/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def shop_verify_email(
    body: EmailProofIn, request: Request, session: SessionDep, c: ContainerDep
) -> None:
    service = AuthService(session, c)
    service.limit_ip(client_ip(request))
    await service.verify_shop_email(body.token, body.firebase_id_token)


@router.post("/shop/mfa/enroll", response_model=MfaEnrollOut)
async def mfa_enroll(principal: ShopSetupDep, session: SessionDep, c: ContainerDep) -> MfaEnrollOut:
    secret, uri = await AuthService(session, c).enroll_mfa(principal.user)
    return MfaEnrollOut(secret=secret, otpauth_uri=uri)


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


# --- Technicians ----------------------------------------------------------------------------------
@router.get("/technician/invite/{token}", response_model=InviteInfoOut)
async def invite_info(token: str, session: SessionDep, c: ContainerDep) -> InviteInfoOut:
    tech, shop, email, verified = await AuthService(session, c).invite_info(token)
    return InviteInfoOut(
        shop_name=shop.name,
        technician_name=tech.name,
        email=email,
        email_verified=verified,
        can_respond_offers=tech.can_respond_offers,
        can_contact_customers=tech.can_contact_customers,
        schedule_view=tech.schedule_view,
    )


@router.post("/technician/invite/verify-email", response_model=ClaimOut)
async def invite_verify_email(
    body: EmailProofIn, request: Request, session: SessionDep, c: ContainerDep
) -> ClaimOut:
    service = AuthService(session, c)
    service.limit_ip(client_ip(request))
    return ClaimOut(claim=await service.verify_invite_email(body.token, body.firebase_id_token))


@router.post("/technician/invite/phone", response_model=OtpStartOut)
async def invite_phone(
    body: InvitePhoneIn, request: Request, session: SessionDep, c: ContainerDep
) -> OtpStartOut:
    started = await AuthService(session, c).start_invite_phone(
        body.token, body.claim, body.phone, ip=client_ip(request)
    )
    return OtpStartOut(
        phone=started.phone,
        resend_after_seconds=started.resend_after_seconds,
        dev_code=started.dev_code,
    )


@router.post("/technician/invite/accept", response_model=TokensOut)
async def invite_accept(
    body: InviteAcceptIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    tokens = await AuthService(session, c).accept_invite(
        body.token,
        body.claim,
        phone=body.phone,
        code=body.code,
        google_id_token=body.google_id_token,
        ip=client_ip(request),
    )
    return _tokens(tokens)


@router.post("/technician/otp/start", response_model=OtpStartOut)
async def tech_otp_start(
    body: OtpStartIn, request: Request, session: SessionDep, c: ContainerDep
) -> OtpStartOut:
    started = await AuthService(session, c).start_tech_otp(body.phone, ip=client_ip(request))
    return OtpStartOut(
        phone=started.phone,
        resend_after_seconds=started.resend_after_seconds,
        dev_code=started.dev_code,
    )


@router.post("/technician/otp/verify", response_model=TokensOut)
async def tech_otp_verify(
    body: OtpVerifyIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    tokens = await AuthService(session, c).verify_tech_otp(
        body.phone, body.code, ip=client_ip(request)
    )
    return _tokens(tokens)


@router.post("/technician/google", response_model=TokensOut)
async def tech_google(
    body: GoogleHomeownerIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    return _tokens(await AuthService(session, c).google_tech(body.id_token, ip=client_ip(request)))
