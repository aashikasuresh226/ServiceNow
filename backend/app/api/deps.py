"""FastAPI dependencies: container, DB session, and authenticated principals."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.db import session_scope
from app.core.errors import Forbidden, Unauthorized
from app.core.security import Role, TokenClaims, TokenType
from app.models import Homeowner, Shop, ShopUser

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


ContainerDep = Annotated[Container, Depends(get_container)]


async def get_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    async for session in session_scope(container.session_factory):
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _claims(
    container: Container, credentials: HTTPAuthorizationCredentials | None, *allowed: TokenType
) -> TokenClaims:
    if credentials is None:
        raise Unauthorized("Sign in required")
    last_error: Unauthorized | None = None
    for token_type in allowed:
        try:
            return container.tokens.verify(
                credentials.credentials, expected_type=token_type, now=container.clock.now()
            )
        except Unauthorized as exc:
            last_error = exc
            if exc.code == "token_expired":
                raise
    raise last_error or Unauthorized("Sign in required")


async def current_homeowner(
    container: ContainerDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Homeowner:
    claims = _claims(container, credentials, TokenType.ACCESS)
    if claims.role != Role.HOMEOWNER:
        raise Forbidden("Homeowner account required")
    homeowner = await session.get(Homeowner, claims.subject_id)
    if homeowner is None:
        raise Unauthorized("Account not found")
    return homeowner


@dataclass(frozen=True, slots=True)
class ShopPrincipal:
    user: ShopUser
    shop: Shop


async def _shop_principal(session: AsyncSession, claims: TokenClaims) -> ShopPrincipal:
    if claims.role != Role.SHOP_USER:
        raise Forbidden("Shop account required")
    user = await session.get(ShopUser, claims.subject_id)
    if user is None:
        raise Unauthorized("Account not found")
    shop = await session.get(Shop, user.shop_id)
    assert shop is not None
    return ShopPrincipal(user, shop)


async def current_shop(
    container: ContainerDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> ShopPrincipal:
    """Fully signed-in shop user (password + 2-step)."""
    claims = _claims(container, credentials, TokenType.ACCESS)
    principal = await _shop_principal(session, claims)
    if not principal.user.mfa_enabled:
        raise Forbidden("Set up 2-step verification first", code="mfa_required")
    return principal


async def shop_in_mfa_setup(
    container: ContainerDep,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> ShopPrincipal:
    """Shop user who passed the password check but hasn't enrolled 2-step yet."""
    claims = _claims(container, credentials, TokenType.MFA_SETUP)
    return await _shop_principal(session, claims)


HomeownerDep = Annotated[Homeowner, Depends(current_homeowner)]
ShopDep = Annotated[ShopPrincipal, Depends(current_shop)]
ShopSetupDep = Annotated[ShopPrincipal, Depends(shop_in_mfa_setup)]
