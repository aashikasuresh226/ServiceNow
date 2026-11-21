from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.api.deps import ContainerDep, SessionDep, ShopSetupDep, client_ip
from app.core.errors import Forbidden, Unauthorized
from app.core.security import Role, TokenType
from app.models import ShopUser
from app.schemas.api import (
    AuthenticatorSetupOut,
    ClaimOut,
    EmailLinkOut,
    EmailLinkSentOut,
    EmailProofIn,
    EmailProofInfoOut,
    ForgotPasswordIn,
    GoogleHomeownerIn,
    GoogleShopIn,
    HomeownerEmailFinishIn,
    HomeownerEmailStartIn,
    HomeownerLoginIn,
    HomeownerSessionOut,
    HomeownerSignupIn,
    HomeownerStartOut,
    InviteAcceptIn,
    InviteAuthenticatorIn,
    InviteInfoOut,
    LoginCodeOut,
    MfaCodeIn,
    MfaEnrollOut,
    MfaLoginIn,
    NonceOut,
    PhoneIn,
    RefreshIn,
    ResetPasswordIn,
    ShopLoginIn,
    ShopLoginOut,
    ShopSignupIn,
    StepTokenIn,
    TechEmailStartIn,
    TechLoginIn,
    TechSessionOut,
    TokenIn,
    TokensOut,
)
from app.services import authenticator
from app.services.auth_service import AuthService, SessionTokens, ShopStep, mask_email
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
def _setup_out(setup: authenticator.Setup) -> AuthenticatorSetupOut:
    return AuthenticatorSetupOut(
        setup_token=setup.token, secret=setup.secret, otpauth_uri=setup.uri
    )


@router.post("/homeowner/start", response_model=HomeownerStartOut)
async def homeowner_start(
    body: PhoneIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerStartOut:
    """Phone number entered: existing accounts enter their authenticator code; new ones
    set up an authenticator app. No texts are sent."""
    start = await AuthService(session, c).homeowner_start(body.phone, ip=client_ip(request))
    return HomeownerStartOut(
        account=start.account,
        setup=_setup_out(start.setup) if start.setup else None,
        method=start.method,
        email_hint=start.email_hint,
    )


@router.post("/homeowner/email/start", response_model=EmailLinkSentOut)
async def homeowner_email_start(
    body: HomeownerEmailStartIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    """No authenticator app: email a single-use sign-in link (Firebase sends it)."""
    link = await AuthService(session, c).homeowner_email_start(
        body.phone, str(body.email) if body.email else None, ip=client_ip(request)
    )
    return EmailLinkSentOut(sent_to=mask_email(link.email), dev_link=link.dev_link)


@router.post("/homeowner/email/finish", response_model=HomeownerSessionOut)
async def homeowner_email_finish(
    body: HomeownerEmailFinishIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    """The emailed link was opened: signs in on the device that opened it."""
    _, tokens, needs_profile = await AuthService(session, c).homeowner_email_finish(
        body.token, body.phone, ip=client_ip(request)
    )
    return HomeownerSessionOut(**_tokens(tokens).model_dump(), needs_profile=needs_profile)


@router.post("/homeowner/signup", response_model=HomeownerSessionOut)
async def homeowner_signup(
    body: HomeownerSignupIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    _, tokens, needs_profile, codes = await AuthService(session, c).homeowner_signup(
        body.phone, body.setup_token, body.code, ip=client_ip(request)
    )
    return HomeownerSessionOut(
        **_tokens(tokens).model_dump(), needs_profile=needs_profile, backup_codes=codes
    )


@router.post("/homeowner/login", response_model=HomeownerSessionOut)
async def homeowner_login(
    body: HomeownerLoginIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    _, tokens, needs_profile = await AuthService(session, c).homeowner_login(
        body.phone, body.code, ip=client_ip(request)
    )
    return HomeownerSessionOut(**_tokens(tokens).model_dump(), needs_profile=needs_profile)


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
    await service.verify_shop_email(body.token)


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


@router.post("/shop/mfa/email", response_model=TokensOut)
async def mfa_email(principal: ShopSetupDep, session: SessionDep, c: ContainerDep) -> TokensOut:
    """2-step verification by email (a sign-in link each time) instead of an authenticator."""
    return _tokens(await AuthService(session, c).enable_email_mfa(principal.user))


async def _mfa_user(token: str, session: SessionDep, c: ContainerDep) -> ShopUser:
    claims = c.tokens.verify(token, expected_type=TokenType.MFA, now=c.clock.now())
    if claims.role != Role.SHOP_USER:
        raise Forbidden("Shop account required")
    user = await session.get(ShopUser, claims.subject_id)
    if user is None:
        raise Unauthorized("Account not found")
    return user


@router.post("/shop/login/email-resend", response_model=ShopLoginOut)
async def shop_login_email_resend(
    body: StepTokenIn, session: SessionDep, c: ContainerDep
) -> ShopLoginOut:
    """Send the 2-step sign-in link again (body.token: the sign-in step token)."""
    user = await _mfa_user(body.token, session, c)
    return _step(await AuthService(session, c).resend_shop_login_link(user))


@router.post("/shop/login/email-open", response_model=LoginCodeOut)
async def shop_login_email_open(
    body: EmailProofIn, request: Request, session: SessionDep, c: ContainerDep
) -> LoginCodeOut:
    """The emailed sign-in link was opened: a code to type on the computer signing in."""
    code = await AuthService(session, c).open_shop_login_link(body.token, ip=client_ip(request))
    return LoginCodeOut(code=code)


@router.post("/shop/login/email-finish", response_model=TokensOut)
async def shop_login_email_finish(
    body: EmailProofIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    """ "Continue on this device" from the emailed sign-in link."""
    return _tokens(
        await AuthService(session, c).finish_shop_login_link(body.token, ip=client_ip(request))
    )


@router.post("/shop/login/email-code", response_model=TokensOut)
async def shop_login_email_code(
    body: MfaLoginIn, session: SessionDep, c: ContainerDep
) -> TokensOut:
    user = await _mfa_user(body.token, session, c)
    return _tokens(await AuthService(session, c).shop_login_code(user, body.code))


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
    return ClaimOut(claim=await service.verify_invite_email(body.token))


@router.post("/technician/invite/authenticator", response_model=AuthenticatorSetupOut)
async def invite_authenticator(
    body: InviteAuthenticatorIn, request: Request, session: SessionDep, c: ContainerDep
) -> AuthenticatorSetupOut:
    service = AuthService(session, c)
    service.limit_ip(client_ip(request))
    return _setup_out(await service.invite_authenticator(body.token, body.claim))


@router.post("/technician/invite/accept", response_model=TechSessionOut)
async def invite_accept(
    body: InviteAcceptIn, request: Request, session: SessionDep, c: ContainerDep
) -> TechSessionOut:
    tokens, codes = await AuthService(session, c).accept_invite(
        body.token,
        body.claim,
        phone=body.phone,
        setup_token=body.setup_token,
        code=body.code,
        google_id_token=body.google_id_token,
        email_sign_in=body.email_sign_in,
        ip=client_ip(request),
    )
    return TechSessionOut(**_tokens(tokens).model_dump(), backup_codes=codes)


@router.post("/technician/login", response_model=TokensOut)
async def tech_login(
    body: TechLoginIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    """Phone number or email, plus the code from the authenticator app."""
    tokens = await AuthService(session, c).tech_login(body.login, body.code, ip=client_ip(request))
    return _tokens(tokens)


@router.post("/technician/email/start", response_model=EmailLinkSentOut)
async def tech_email_start(
    body: TechEmailStartIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    """Technicians who chose email: a sign-in link to the address on their account. The
    reply is the same whether or not the account exists."""
    link = await AuthService(session, c).tech_email_start(body.login, ip=client_ip(request))
    return EmailLinkSentOut(sent_to=None, dev_link=link.dev_link if link else None)


@router.post("/technician/email/finish", response_model=TokensOut)
async def tech_email_finish(
    body: TokenIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    return _tokens(
        await AuthService(session, c).tech_email_finish(body.token, ip=client_ip(request))
    )


@router.post("/homeowner/email/confirm", response_model=EmailLinkSentOut)
async def homeowner_confirm_email(
    body: TokenIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    """The link sent when a homeowner added a recovery email was opened: save the email."""
    email = await AuthService(session, c).homeowner_confirm_email(body.token, ip=client_ip(request))
    return EmailLinkSentOut(sent_to=mask_email(email))


# --- Recovery: lost authenticator (homeowners, technicians), forgotten password (shops) ---
@router.post("/homeowner/recover", response_model=EmailLinkSentOut)
async def homeowner_recover(
    body: PhoneIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    link = await AuthService(session, c).homeowner_recover_start(body.phone, ip=client_ip(request))
    return EmailLinkSentOut(sent_to=mask_email(link.email), dev_link=link.dev_link)


@router.post("/homeowner/recover/finish", response_model=HomeownerSessionOut)
async def homeowner_recover_finish(
    body: TokenIn, request: Request, session: SessionDep, c: ContainerDep
) -> HomeownerSessionOut:
    """Removes the lost authenticator: email links from now on. Signs out everywhere else."""
    _, tokens, needs_profile = await AuthService(session, c).homeowner_recover_finish(
        body.token, ip=client_ip(request)
    )
    return HomeownerSessionOut(**_tokens(tokens).model_dump(), needs_profile=needs_profile)


@router.post("/technician/recover", response_model=EmailLinkSentOut)
async def tech_recover(
    body: TechEmailStartIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    link = await AuthService(session, c).tech_recover_start(body.login, ip=client_ip(request))
    return EmailLinkSentOut(sent_to=None, dev_link=link.dev_link if link else None)


@router.post("/technician/recover/finish", response_model=TokensOut)
async def tech_recover_finish(
    body: TokenIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    return _tokens(
        await AuthService(session, c).tech_recover_finish(body.token, ip=client_ip(request))
    )


@router.post("/shop/forgot-password", response_model=EmailLinkSentOut)
async def shop_forgot_password(
    body: ForgotPasswordIn, request: Request, session: SessionDep, c: ContainerDep
) -> EmailLinkSentOut:
    """Emails a reset link if the account exists. The reply is the same either way."""
    link = await AuthService(session, c).shop_forgot_password(body.email, ip=client_ip(request))
    return EmailLinkSentOut(sent_to=None, dev_link=link.dev_link if link else None)


@router.post("/shop/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def shop_reset_password(
    body: ResetPasswordIn, request: Request, session: SessionDep, c: ContainerDep
) -> None:
    await AuthService(session, c).shop_reset_password(
        body.token, body.password, ip=client_ip(request)
    )


@router.post("/technician/google", response_model=TokensOut)
async def tech_google(
    body: GoogleHomeownerIn, request: Request, session: SessionDep, c: ContainerDep
) -> TokensOut:
    return _tokens(await AuthService(session, c).google_tech(body.id_token, ip=client_ip(request)))
