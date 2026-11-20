"""Housecall Pro client (API key from the shop's account; API + webhooks need the MAX plan).

What we do with it:
- read the technician roster (employees) and booked jobs (busy time for matching);
- when the shop accepts one of our jobs: find or create the customer and address,
  create the job with its arrival window, our notes (problem, AI read of the data
  plate) and photo links, unassigned so the shop's dispatcher assigns a tech as usual
  (or with the tech the homeowner picked);
- read the job back to learn the assigned technician, schedule changes and status.

Endpoints and fields follow Housecall Pro's public API (https://docs.housecallpro.com):
GET /employees, GET /jobs, POST /jobs, GET /jobs/{id}, POST /jobs/{id}/notes,
POST /jobs/{id}/links, DELETE /jobs/{id}/schedule, GET/POST /customers,
GET/POST /customers/{id}/addresses. Integrations in the wild send the key as either
"Token <key>" or "Bearer <key>"; verify() tries both and remembers what works.
All field mapping is in this file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
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
LEAD_SOURCE = "HVAC Connect"


@dataclass(frozen=True, slots=True)
class HcpAddress:
    street: str
    city: str = ""
    state: str = ""
    zip: str = ""


@dataclass(frozen=True, slots=True)
class HcpJob:
    id: str
    work_status: str  # normalized: "scheduled", "in progress", "complete", "canceled", ...
    employee_ids: list[str] = field(default_factory=list)
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None

    @property
    def canceled(self) -> bool:
        return "cancel" in self.work_status

    @property
    def started(self) -> bool:
        return self.work_status in ("in progress", "started")

    @property
    def completed(self) -> bool:
        return self.work_status.startswith("complete")


@dataclass(frozen=True, slots=True)
class HcpCustomer:
    id: str
    name: str
    phone: str | None  # as typed in Housecall Pro (mobile, else home, else work)
    email: str | None
    address: str | None  # first address, one line


@dataclass(frozen=True, slots=True)
class HcpJobDetail:
    """A job as listed by GET /jobs, with what a technician needs to run it."""

    job: HcpJob
    customer: HcpCustomer | None
    address: str | None
    description: str | None
    invoice_number: str | None


class HousecallProClient:
    provides_shifts = False

    def __init__(
        self,
        *,
        api_key: str,
        http: httpx.AsyncClient,
        auth_scheme: str = "Token",
        api_base: str = API_BASE,
    ) -> None:
        self._key = api_key
        self._scheme = auth_scheme if auth_scheme in ("Token", "Bearer") else "Token"
        self._http = http
        self._base = api_base

    @property
    def learned_credentials(self) -> dict[str, str]:
        return {"auth_scheme": self._scheme}

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"{self._scheme} {self._key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # --- Connection ---------------------------------------------------------------------
    async def verify(self) -> None:
        """Check the key works, trying both header formats."""
        last: ExternalServiceError | None = None
        for scheme in (self._scheme, "Bearer" if self._scheme == "Token" else "Token"):
            self._scheme = scheme
            try:
                await self._request("GET", "/employees", params={"page": 1, "page_size": 1})
                return
            except ExternalServiceError as exc:
                last = exc
                if "rejected" not in exc.message:
                    raise
        assert last is not None
        raise last

    # --- Reading -------------------------------------------------------------------------
    async def list_technicians(self) -> list[ExternalTechnician]:
        rows = await self._get_all("/employees", "employees", {})
        return [
            ExternalTechnician(
                str(r["id"]),
                " ".join(p for p in (r.get("first_name"), r.get("last_name")) if p) or "Technician",
                r.get("mobile_number"),
            )
            for r in rows
            if r.get("id")
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

    async def fetch_jobs(self, *, start: datetime, end: datetime) -> list[HcpJobDetail]:
        """Jobs scheduled in [start, end), plus the newest jobs (which may be unscheduled)."""
        scheduled = await self._get_all(
            "/jobs",
            "jobs",
            {
                "scheduled_start_min": start.astimezone(UTC).isoformat(),
                "scheduled_start_max": end.astimezone(UTC).isoformat(),
            },
        )
        newest = await self._request(
            "GET",
            "/jobs",
            params={
                "page": 1,
                "page_size": 50,
                "sort_by": "created_at",
                "sort_direction": "desc",
            },
        )
        seen: dict[str, HcpJobDetail] = {}
        for row in [*scheduled, *newest.get("jobs", [])]:
            if isinstance(row, dict) and row.get("id"):
                seen.setdefault(str(row["id"]), parse_job_detail(row))
        return list(seen.values())

    async def list_customers(self) -> list[HcpCustomer]:
        rows = await self._get_all("/customers", "customers", {})
        return [parse_customer(r) for r in rows if isinstance(r, dict) and r.get("id")]

    async def get_job(self, job_id: str) -> HcpJob | None:
        """None if the job was deleted in Housecall Pro."""
        try:
            body = await self._request("GET", f"/jobs/{job_id}")
        except ExternalServiceError as exc:
            if "not found" in exc.message:
                return None
            raise
        return parse_job(body)

    # --- Writing -------------------------------------------------------------------------
    async def find_or_create_customer(
        self,
        *,
        first_name: str,
        last_name: str,
        mobile: str | None,
        email: str | None,
        address: HcpAddress,
    ) -> tuple[str, str]:
        """(customer id, address id), reusing the shop's existing customer if the phone
        number matches, so repeat customers aren't duplicated."""
        customer: dict[str, Any] | None = None
        digits = _digits(mobile)
        if digits:
            body = await self._request(
                "GET", "/customers", params={"q": digits[-10:], "page_size": 10}
            )
            for row in body.get("customers", []):
                numbers = (row.get("mobile_number"), row.get("home_number"), row.get("work_number"))
                if any(_digits(n)[-10:] == digits[-10:] for n in numbers if n):
                    customer = row
                    break
        if customer is None:
            customer = await self._request(
                "POST",
                "/customers",
                json={
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "mobile_number": mobile,
                    "notifications_enabled": False,
                    "lead_source": LEAD_SOURCE,
                    "addresses": [_address_json(address)],
                },
            )
        customer_id = str(customer["id"])
        address_id = _matching_address(customer.get("addresses") or [], address)
        if address_id is None:
            listed = await self._request("GET", f"/customers/{customer_id}/addresses")
            address_id = _matching_address(listed.get("addresses") or [], address)
        if address_id is None:
            created = await self._request(
                "POST", f"/customers/{customer_id}/addresses", json=_address_json(address)
            )
            address_id = str(created["id"])
        return customer_id, address_id

    async def create_job(
        self,
        *,
        customer_id: str,
        address_id: str,
        start: datetime,
        end: datetime,
        arrival_window_minutes: int,
        notes: str,
        employee_ids: list[str],
    ) -> str:
        payload: dict[str, Any] = {
            "customer_id": customer_id,
            "address_id": address_id,
            "schedule": {
                "scheduled_start": start.astimezone(UTC).isoformat(),
                "scheduled_end": end.astimezone(UTC).isoformat(),
                "arrival_window": arrival_window_minutes,
            },
            "notes": notes,
            "lead_source": LEAD_SOURCE,
        }
        if employee_ids:
            payload["assigned_employee_ids"] = employee_ids
        body = await self._request("POST", "/jobs", json=payload)
        return str(body["id"])

    async def add_note(self, job_id: str, content: str) -> None:
        await self._request("POST", f"/jobs/{job_id}/notes", json={"content": content})

    async def add_link(self, job_id: str, title: str, url: str) -> None:
        await self._request("POST", f"/jobs/{job_id}/links", json={"title": title, "url": url})

    async def add_line_item(
        self,
        job_id: str,
        *,
        name: str,
        quantity: float,
        unit_price_cents: int,
        kind: str = "labor",
        description: str | None = None,
    ) -> dict[str, Any]:
        """Money is integer cents in Housecall Pro ($250 -> 25000)."""
        body: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "quantity": quantity,
            "unit_price": unit_price_cents,
            "unit_cost": 0,
        }
        if description:
            body["description"] = description
        return await self._request("POST", f"/jobs/{job_id}/line_items", json=body)

    async def line_items(self, job_id: str) -> list[dict[str, Any]]:
        body = await self._request("GET", f"/jobs/{job_id}/line_items")
        rows = body.get("data") or body.get("line_items") or body.get("items") or []
        return [r for r in rows if isinstance(r, dict)]

    async def upload_attachment(
        self, job_id: str, *, filename: str, data: bytes, content_type: str
    ) -> None:
        """Multipart upload (field "file"). Not idempotent, so never retried after a send."""
        try:
            response = await self._http.post(
                f"{self._base}/jobs/{job_id}/attachments",
                files={"file": (filename, data, content_type)},
                headers={k: v for k, v in self._headers().items() if k != "Content-Type"},
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            log.warning("Housecall Pro attachment upload failed: %s", exc)
            raise ExternalServiceError("Couldn't reach Housecall Pro") from exc
        if response.status_code >= 400:
            log.warning(
                "Housecall Pro attachment -> %s: %.300s", response.status_code, response.text
            )
            raise ExternalServiceError(_reason(response.status_code))

    async def unschedule(self, job_id: str) -> None:
        await self._request("DELETE", f"/jobs/{job_id}/schedule")

    # --- HTTP ----------------------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._http.request(
                method, self._base + path, params=params, json=json, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            log.warning("Housecall Pro %s %s failed: %s", method, path, exc)
            raise ExternalServiceError("Couldn't reach Housecall Pro") from exc
        if response.status_code >= 400:
            log.warning(
                "Housecall Pro %s %s -> %s: %.300s",
                method,
                path,
                response.status_code,
                response.text,
            )
            raise ExternalServiceError(_reason(response.status_code))
        if response.status_code == 204 or not response.content:
            return {}
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {"items": body}

    async def _get_all(self, path: str, key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = await self._request(
                "GET", path, params={**params, "page": page, "page_size": PAGE_SIZE}
            )
            rows.extend(body.get(key, []))
            if page >= int(body.get("total_pages", 1) or 1):
                break
        return rows


def _reason(status: int) -> str:
    if status == 401:
        return "Housecall Pro rejected the API key"
    if status == 403:
        return "Housecall Pro refused access (the API needs the MAX plan and an API key from it)"
    if status == 404:
        return "Housecall Pro: not found"
    if status == 429:
        return "Housecall Pro is rate-limiting requests; we'll retry"
    if status >= 500:
        return "Housecall Pro is having problems; we'll retry"
    return f"Housecall Pro rejected the request ({status})"


def parse_job(body: dict[str, Any]) -> HcpJob:
    schedule = body.get("schedule") or {}
    employees = body.get("assigned_employees") or body.get("dispatched_employees") or []
    ids = [str(e.get("id") or e.get("employee_id")) for e in employees if isinstance(e, dict)]
    status = str(body.get("work_status") or "").lower().replace("_", " ").strip()
    return HcpJob(
        id=str(body.get("id")),
        work_status=status,
        employee_ids=[i for i in ids if i and i != "None"],
        scheduled_start=_parse(schedule.get("scheduled_start")),
        scheduled_end=_parse(schedule.get("scheduled_end")),
    )


def parse_customer(body: dict[str, Any]) -> HcpCustomer:
    name = " ".join(p for p in (body.get("first_name"), body.get("last_name")) if p)
    phone = body.get("mobile_number") or body.get("home_number") or body.get("work_number")
    addresses = body.get("addresses") or []
    return HcpCustomer(
        id=str(body["id"]),
        name=name.strip() or str(body.get("company") or "").strip() or "Customer",
        phone=str(phone) if phone else None,
        email=str(body["email"]).strip() if body.get("email") else None,
        address=format_address(addresses[0])
        if addresses and isinstance(addresses[0], dict)
        else None,
    )


def format_address(row: dict[str, Any]) -> str | None:
    street = " ".join(str(p) for p in (row.get("street"), row.get("street_line_2")) if p)
    tail = " ".join(str(p) for p in (row.get("state"), row.get("zip")) if p)
    text = ", ".join(p for p in (street, str(row.get("city") or ""), tail) if p)
    return text or None


def parse_job_detail(body: dict[str, Any]) -> HcpJobDetail:
    customer = body.get("customer")
    address = body.get("address")
    return HcpJobDetail(
        job=parse_job(body),
        customer=parse_customer(customer)
        if isinstance(customer, dict) and customer.get("id")
        else None,
        address=format_address(address) if isinstance(address, dict) else None,
        description=(str(body.get("description") or "").strip() or None),
        invoice_number=str(body["invoice_number"]) if body.get("invoice_number") else None,
    )


def parse_us_address(text: str) -> HcpAddress:
    """'191 Peachtree St NE, Atlanta, GA 30303' -> parts. Falls back to the whole text."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if parts and parts[-1].upper() in ("USA", "US", "UNITED STATES"):
        parts = parts[:-1]
    if len(parts) >= 3:
        match = re.match(r"^([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)?$", parts[-1])
        if match:
            return HcpAddress(
                street=", ".join(parts[:-2]),
                city=parts[-2],
                state=match.group(1).upper(),
                zip=match.group(2) or "",
            )
    return HcpAddress(street=text.strip())


def _address_json(address: HcpAddress) -> dict[str, str]:
    return {
        "street": address.street,
        "city": address.city,
        "state": address.state,
        "zip": address.zip,
        "country": "US",
    }


def _matching_address(rows: list[dict[str, Any]], address: HcpAddress) -> str | None:
    want = _norm(address.street)
    for row in rows:
        if row.get("id") and _norm(str(row.get("street") or "")) == want:
            return str(row["id"])
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def _job_to_blocks(job: dict[str, Any]) -> list[ExternalBlock]:
    parsed = parse_job(job)
    if not (parsed.scheduled_start and parsed.scheduled_end) or parsed.canceled or parsed.completed:
        return []
    return [
        ExternalBlock(
            emp, AvailabilityKind.BUSY, parsed.scheduled_start, parsed.scheduled_end, "Job"
        )
        for emp in parsed.employee_ids
    ]


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
