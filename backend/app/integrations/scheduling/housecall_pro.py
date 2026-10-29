"""Housecall Pro client (API key auth; requires the shop's MAX plan).

Housecall Pro exposes employees and scheduled jobs but not shifts, so shifts
come from each technician's working hours in our portal and HCP jobs become
BUSY blocks.

INTEGRATION NOTE: confirm the auth header format, query parameters and JSON
field names against Housecall Pro's API reference (docs.housecallpro.com)
before going live; all mapping is confined to `_job_to_blocks` and
`list_technicians` so changes stay local.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.errors import ExternalServiceError
from app.domain.enums import AvailabilityKind
from app.integrations.scheduling.base import ExternalBlock, ExternalTechnician

log = logging.getLogger(__name__)

API_BASE = "https://api.housecallpro.com"
PAGE_SIZE = 100
MAX_PAGES = 50


class HousecallProClient:
    provides_shifts = False

    def __init__(self, *, api_key: str, http: httpx.AsyncClient) -> None:
        self._headers = {"Authorization": f"Token {api_key}", "Accept": "application/json"}
        self._http = http

    async def verify(self) -> None:
        await self._get("/employees", {"page": 1, "page_size": 1})

    async def list_technicians(self) -> list[ExternalTechnician]:
        rows = await self._get_all("/employees", "employees", {})
        return [
            ExternalTechnician(
                str(r["id"]),
                " ".join(p for p in (r.get("first_name"), r.get("last_name")) if p) or "Technician",
                r.get("mobile_number"),
            )
            for r in rows
        ]

    async def fetch_blocks(self, *, start: datetime, end: datetime) -> list[ExternalBlock]:
        jobs = await self._get_all(
            "/jobs",
            "jobs",
            {
                "scheduled_start_min": start.astimezone(UTC).isoformat(),
                "scheduled_start_max": end.astimezone(UTC).isoformat(),
            },
        )
        return [b for job in jobs for b in _job_to_blocks(job)]

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._http.get(API_BASE + path, params=params, headers=self._headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("Housecall Pro GET %s failed: %s", path, exc)
            raise ExternalServiceError("Couldn't reach Housecall Pro") from exc
        return response.json()

    async def _get_all(self, path: str, key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = await self._get(path, {**params, "page": page, "page_size": PAGE_SIZE})
            rows.extend(body.get(key, []))
            if page >= int(body.get("total_pages", 1)):
                break
        return rows


def _job_to_blocks(job: dict[str, Any]) -> list[ExternalBlock]:
    schedule = job.get("schedule") or {}
    start = _parse(schedule.get("scheduled_start"))
    end = _parse(schedule.get("scheduled_end"))
    status = str(job.get("work_status", "")).lower()
    if not (start and end) or status in {"canceled", "complete", "completed"}:
        return []
    return [
        ExternalBlock(str(emp["id"]), AvailabilityKind.BUSY, start, end, "Job")
        for emp in job.get("assigned_employees", [])
        if emp.get("id")
    ]


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
