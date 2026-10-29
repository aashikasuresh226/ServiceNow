"""The single place where a request's status changes (validated + audited)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import Actor, RequestStatus
from app.domain.state_machine import ensure_transition
from app.models import RequestEvent, ServiceRequest


def transition(
    session: AsyncSession,
    request: ServiceRequest,
    target: RequestStatus,
    actor: Actor,
    note: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    current = RequestStatus(request.status)
    ensure_transition(current, target)
    request.status = target.value
    session.add(
        RequestEvent(
            request_id=request.id,
            from_status=current.value,
            to_status=target.value,
            actor=actor.value,
            note=note,
            data=data,
        )
    )


def clear_assignment(request: ServiceRequest) -> None:
    request.technician_id = None
    request.shop_id = None
    request.distance_km = None
    request.proposal_expires_at = None
    request.offer_expires_at = None
    request.eta_at = None
