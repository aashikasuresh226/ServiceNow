"""Local demo helpers. Only mounted when HVAC_ENVIRONMENT=dev."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.api.deps import ContainerDep, SessionDep
from app.core.errors import NotFound
from app.integrations.payments.fake import FakePaymentGateway
from app.integrations.sms import ConsoleSmsSender
from app.models import Shop

router = APIRouter(prefix="/dev", tags=["dev"])


@router.get("/fake-payout-onboarding/{account_id}")
async def fake_payout_onboarding(
    account_id: str, session: SessionDep, c: ContainerDep
) -> RedirectResponse:
    """Stands in for Stripe's hosted onboarding: marks the account done, returns to portal."""
    if not isinstance(c.payments, FakePaymentGateway):
        raise NotFound("Not available")
    c.payments.complete_onboarding(account_id)
    shop = await session.scalar(select(Shop).where(Shop.payout_account_id == account_id))
    if shop:
        shop.payouts_enabled = True
    return RedirectResponse(f"{c.settings.public_web_url}/onboarding/payouts?status=done")


@router.get("/sms-outbox")
async def sms_outbox(c: ContainerDep) -> list[dict[str, str]]:
    if not isinstance(c.sms, ConsoleSmsSender):
        raise NotFound("Not available")
    return [{"to": to, "body": body} for to, body in reversed(c.sms.outbox[-30:])]
