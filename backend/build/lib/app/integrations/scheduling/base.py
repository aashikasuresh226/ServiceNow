"""Interface to a shop's field-service software (ServiceTitan, Housecall Pro).

We only read: the technician roster, booked work (BUSY) and, where the provider
exposes it, shifts (SHIFT). Providers without shifts fall back to each tech's
working hours set in our portal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.enums import AvailabilityKind


@dataclass(frozen=True, slots=True)
class ExternalTechnician:
    external_id: str
    name: str
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class ExternalBlock:
    external_technician_id: str
    kind: AvailabilityKind
    starts_at: datetime
    ends_at: datetime
    label: str | None = None


class SchedulingClient(Protocol):
    provides_shifts: bool

    async def verify(self) -> None:
        """Raise ExternalServiceError if the credentials don't work."""

    async def list_technicians(self) -> list[ExternalTechnician]: ...

    async def fetch_blocks(self, *, start: datetime, end: datetime) -> list[ExternalBlock]: ...
