"""ServiceTitan client (client-credentials OAuth + ST-App-Key header).

Endpoints used (read-only):
  settings/v2/.../technicians              roster
  dispatch/v2/.../technician-shifts        SHIFT blocks
  jpm/v2/.../appointments                  appointment times
  dispatch/v2/.../appointment-assignments  which techs are on each appointment → BUSY
  dispatch/v2/.../non-job-appointments     meetings, training, etc. → BUSY

INTEGRATION NOTE: confirm field names and query parameters against the current
ServiceTitan API reference in your developer sandbox before going live; all
mapping is confined to the `_to_*` helpers below so changes stay local.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.errors import ExternalServiceError
from app.domain.enums import AvailabilityKind
from app.integrations.scheduling.base import ExternalBlock, ExternalTechnician

log = logging.getLogger(__name__)

AUTH_URL = "https://auth.servicetitan.io/connect/token"
API_BASE = "https://api.servicetitan.io"
PAGE_SIZE = 200
MAX_PAGES = 50


class ServiceTitanClient:
    provides_shifts = True

    def __init__(
        self,
        *,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        app_key: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._tenant = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._app_key = app_key
        self._http = http
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)

    async def verify(self) -> None:
        await self._get(
            f"/settings/v2/tenant/{self._tenant}/technicians", {"page": 1, "pageSize": 1}
        )

    async def list_technicians(self) -> list[ExternalTechnician]:
        rows = await self._get_all(
            f"/settings/v2/tenant/{self._tenant}/technicians", {"active": "True"}
        )
        return [
            ExternalTechnician(str(r["id"]), r.get("name") or "Technician", r.get("phoneNumber"))
            for r in rows
        ]

    async def fetch_blocks(self, *, start: datetime, end: datetime) -> list[ExternalBlock]:
        window = {"startsOnOrAfter": _iso(start - timedelta(hours=12)), "startsBefore": _iso(end)}
        shifts = await self._get_all(
            f"/dispatch/v2/tenant/{self._tenant}/technician-shifts",
            {
                "startsOnOrAfter": window["startsOnOrAfter"],
                "endsOnOrBefore": _iso(end + timedelta(hours=12)),
            },
        )
        appointments = await self._get_all(f"/jpm/v2/tenant/{self._tenant}/appointments", window)
        assignments: list[dict[str, Any]] = []
        if appointments:
            assignments = await self._get_all(
                f"/dispatch/v2/tenant/{self._tenant}/appointment-assignments",
                {"appointmentIds": ",".join(str(a["id"]) for a in appointments)},
            )
        non_job = await self._get_all(
            f"/dispatch/v2/tenant/{self._tenant}/non-job-appointments", window
        )

        blocks = [b for s in shifts if (b := _shift_to_block(s))]
        by_appointment = {a["id"]: a for a in appointments}
        for assignment in assignments:
            appt = by_appointment.get(assignment.get("appointmentId"))
            if appt and (b := _appointment_to_block(appt, assignment)):
                blocks.append(b)
        blocks.extend(b for n in non_job if (b := _non_job_to_block(n)))
        return blocks

    # --- HTTP ------------------------------------------------------------------
    async def _auth_header(self) -> dict[str, str]:
        now = datetime.now(UTC)
        if not self._token or now >= self._token_expires_at:
            try:
                response = await self._http.post(
                    AUTH_URL,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ExternalServiceError("ServiceTitan rejected the credentials") from exc
            body = response.json()
            self._token = body["access_token"]
            self._token_expires_at = now + timedelta(seconds=int(body.get("expires_in", 900)) - 60)
        return {"Authorization": f"Bearer {self._token}", "ST-App-Key": self._app_key}

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.get(
                API_BASE + path, params=params, headers=await self._auth_header()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("ServiceTitan GET %s failed: %s", path, exc)
            raise ExternalServiceError("Couldn't reach ServiceTitan") from exc
        return response.json()

    async def _get_all(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = await self._get(path, {**params, "page": page, "pageSize": PAGE_SIZE})
            rows.extend(body.get("data", []))
            if not body.get("hasMore"):
                break
        return rows


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _duration(value: str | None) -> timedelta:
    """ServiceTitan durations look like '01:30:00'."""
    match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})", value or "")
    if not match:
        return timedelta(hours=1)
    h, m, s = map(int, match.groups())
    return timedelta(hours=h, minutes=m, seconds=s)


def _shift_to_block(row: dict[str, Any]) -> ExternalBlock | None:
    start, end = _parse(row.get("start")), _parse(row.get("end"))
    if not (start and end and row.get("technicianId")) or row.get("active") is False:
        return None
    kind = (
        AvailabilityKind.BUSY
        if str(row.get("shiftType", "")).lower() == "timeoff"
        else AvailabilityKind.SHIFT
    )
    return ExternalBlock(str(row["technicianId"]), kind, start, end, row.get("title"))


def _appointment_to_block(appt: dict[str, Any], assignment: dict[str, Any]) -> ExternalBlock | None:
    start, end = _parse(appt.get("start")), _parse(appt.get("end"))
    if not (start and end) or str(appt.get("status", "")).lower() in {"canceled", "done"}:
        return None
    return ExternalBlock(str(assignment["technicianId"]), AvailabilityKind.BUSY, start, end, "Job")


def _non_job_to_block(row: dict[str, Any]) -> ExternalBlock | None:
    start = _parse(row.get("start"))
    if not (start and row.get("technicianId")) or row.get("active") is False:
        return None
    return ExternalBlock(
        str(row["technicianId"]),
        AvailabilityKind.BUSY,
        start,
        start + _duration(row.get("duration")),
        row.get("name"),
    )
