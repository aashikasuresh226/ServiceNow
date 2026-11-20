"""Allowed request status transitions. Every status change goes through here."""

from __future__ import annotations

from app.core.errors import InvalidState
from app.domain.enums import RequestStatus as S

TRANSITIONS: dict[S, frozenset[S]] = {
    S.DRAFT: frozenset({S.ANALYZED, S.CANCELED}),
    S.ANALYZED: frozenset({S.ANALYZED, S.PROPOSED, S.WAITLISTED, S.CANCELED}),
    S.PROPOSED: frozenset({S.OFFERED, S.ANALYZED, S.CANCELED}),
    # Waitlisted requests are matched by the worker: to PROPOSED if the homeowner has
    # not confirmed yet, straight to OFFERED if they already confirmed (re-match).
    S.WAITLISTED: frozenset({S.PROPOSED, S.OFFERED, S.WAITLISTED, S.CANCELED}),
    S.OFFERED: frozenset({S.DISPATCHED, S.OFFERED, S.WAITLISTED, S.CANCELED}),
    S.DISPATCHED: frozenset({S.EN_ROUTE, S.ON_SITE, S.CANCELED}),
    S.EN_ROUTE: frozenset({S.ON_SITE, S.CANCELED}),
    S.ON_SITE: frozenset({S.QUOTED, S.CANCELED}),
    S.QUOTED: frozenset({S.IN_PROGRESS, S.QUOTED, S.CANCELED}),
    S.IN_PROGRESS: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.CANCELED: frozenset(),
}


def can_transition(current: S, target: S) -> bool:
    return target in TRANSITIONS[current]


def ensure_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidState(f"Cannot move a request from '{current}' to '{target}'")


HOMEOWNER_CANCELABLE: frozenset[S] = frozenset(
    {S.DRAFT, S.ANALYZED, S.PROPOSED, S.WAITLISTED, S.OFFERED, S.DISPATCHED, S.EN_ROUTE}
)
"""After the tech is on site, cancellation goes through support (fees may apply)."""
