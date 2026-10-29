"""Best-effort notifications. A failed text must never fail the business operation."""

from __future__ import annotations

import logging

from app.container import Container
from app.models import Homeowner

log = logging.getLogger(__name__)


async def notify_homeowner(container: Container, homeowner: Homeowner, message: str) -> None:
    if not homeowner.sms_opt_in:
        return
    try:
        await container.sms.send(to=homeowner.phone, body=message)
    except Exception:
        log.exception("Failed to notify homeowner %s", homeowner.id)
