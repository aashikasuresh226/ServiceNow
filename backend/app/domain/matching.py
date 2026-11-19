"""The matching engine: assign the technician who can reach the homeowner soonest.

Pure functions over plain data, so the rules are easy to read and test.

For one request (`plan_options` + `best_option`):
1. Hard filters: tech active (pre-filtered), shop live, homeowner inside the tech's
   service radius, qualified for the equipment type, EPA 608 certified when
   refrigerant work is likely, and hasn't declined this job before.
2. Availability: for each remaining tech, find the earliest time t they can leave
   such that driving there + the job fit inside their shift time without overlapping
   anything already on their calendar (jobs, reservations, time marked busy).
   That's `earliest_window` in domain/availability.py.
3. Choose the minimum arrival time (t + drive time). Ties go to the closer tech,
   then the tech with fewer jobs today (spreads work), then the higher rating.

This is exact for a single request: every feasible tech is evaluated, so the chosen
arrival time is the earliest possible given everyone's existing bookings. Cost is
O(T · B log B) for T nearby techs with B calendar blocks each.

For a backlog of waiting requests, `assign_batch` solves the min-cost assignment
problem with the Hungarian algorithm (see domain/assignment.py) instead of serving
them one by one, so one request can't grab the tech another request needed more.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.domain.assignment import min_cost_assignment
from app.domain.availability import Block, earliest_window
from app.domain.enums import Certification, EquipmentType
from app.domain.geo import LatLng, haversine_km, travel_minutes


@dataclass(frozen=True, slots=True)
class TechCandidate:
    technician_id: uuid.UUID
    shop_id: uuid.UUID
    location: LatLng
    service_radius_km: float
    equipment_types: frozenset[str]
    certifications: frozenset[str]
    blocks: tuple[Block, ...] = ()  # shifts + everything already booked
    jobs_today: int = 0
    rating: float | None = None


@dataclass(frozen=True, slots=True)
class MatchCriteria:
    location: LatLng
    equipment_type: str = EquipmentType.UNKNOWN.value
    requires_refrigerant_work: bool = False
    excluded_technician_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    # The homeowner's pick: only this company / only this technician.
    only_shop_id: uuid.UUID | None = None
    only_technician_id: uuid.UUID | None = None

    def allows(self, c: TechCandidate) -> bool:
        if self.only_technician_id and c.technician_id != self.only_technician_id:
            return False
        return not (self.only_shop_id and c.shop_id != self.only_shop_id)


@dataclass(frozen=True, slots=True)
class PlanSettings:
    job_duration: timedelta
    speed_kmh: float
    horizon: timedelta  # how far ahead we look for a slot


@dataclass(frozen=True, slots=True)
class Option:
    """One way to serve the request: this tech leaves at `start_at`, arrives at `arrival_at`."""

    candidate: TechCandidate
    distance_km: float
    travel_minutes: int
    start_at: datetime
    arrival_at: datetime


@dataclass
class NoMatchReport:
    """Why nobody was found, so the homeowner and the shop get a real explanation."""

    nearby: int = 0  # techs of live shops in the search area
    out_of_range: int = 0
    not_qualified: int = 0
    needs_epa: int = 0
    no_time: int = 0
    declined: int = 0
    chosen: bool = False  # the homeowner picked a company or technician

    def message(self) -> str:
        if self.chosen:
            if self.nearby == 0:
                return "The company or technician you picked isn't taking requests right now."
            if self.out_of_range == self.nearby:
                return "The company or technician you picked doesn't cover this address."
            if self.no_time:
                return (
                    "The company or technician you picked has no opening in the next 7 days. "
                    "Try another, or let us find the soonest available technician."
                )
            return (
                "The company or technician you picked isn't qualified for this equipment. "
                "Try another, or let us find the soonest available technician."
            )
        if self.nearby == 0:
            return (
                "No HVAC shops are taking requests near this address yet. We'll keep looking "
                "and text you when one is available."
            )
        if self.out_of_range == self.nearby:
            return (
                "The nearest technicians don't cover this address (it's outside their service "
                "area). We'll text you when one does."
            )
        if self.no_time and self.no_time + self.out_of_range + self.declined >= self.nearby:
            return (
                "Nearby technicians are fully booked for the next week. You're on the waitlist "
                "and we'll text you as soon as a slot opens."
            )
        if self.needs_epa:
            return (
                "Your repair likely needs an EPA 608 certified technician, and none nearby are "
                "available. You're on the waitlist."
            )
        return (
            "No nearby technician is qualified for this equipment type yet. You're on the "
            "waitlist and we'll text you when one is available."
        )


def is_qualified(c: TechCandidate, criteria: MatchCriteria) -> bool:
    unit = criteria.equipment_type
    if unit and unit != EquipmentType.UNKNOWN.value and unit not in c.equipment_types:
        return False
    return not (
        criteria.requires_refrigerant_work and Certification.EPA_608.value not in c.certifications
    )


def plan_option(
    c: TechCandidate, criteria: MatchCriteria, now: datetime, settings: PlanSettings
) -> Option | None:
    """The earliest way this tech can serve the request, or None."""
    if c.technician_id in criteria.excluded_technician_ids or not criteria.allows(c):
        return None
    if not is_qualified(c, criteria):
        return None
    distance = haversine_km(c.location, criteria.location)
    if distance > c.service_radius_km:
        return None
    drive = travel_minutes(distance, settings.speed_kmh)
    start = earliest_window(
        c.blocks,
        earliest=now,
        need=timedelta(minutes=drive) + settings.job_duration,
        latest_start=now + settings.horizon,
    )
    if start is None:
        return None
    return Option(c, distance, drive, start, start + timedelta(minutes=drive))


def rank_key(o: Option) -> tuple[datetime, float, int, float]:
    return (
        o.arrival_at,
        round(o.distance_km, 1),
        o.candidate.jobs_today,
        -(o.candidate.rating or 0),
    )


def plan_options(
    candidates: Sequence[TechCandidate],
    criteria: MatchCriteria,
    now: datetime,
    settings: PlanSettings,
) -> tuple[list[Option], NoMatchReport]:
    """All feasible options, best first, plus counts explaining who was filtered out."""
    candidates = [c for c in candidates if criteria.allows(c)]
    report = NoMatchReport(
        nearby=len(candidates), chosen=bool(criteria.only_shop_id or criteria.only_technician_id)
    )
    options: list[Option] = []
    for c in candidates:
        if c.technician_id in criteria.excluded_technician_ids:
            report.declined += 1
            continue
        if haversine_km(c.location, criteria.location) > c.service_radius_km:
            report.out_of_range += 1
            continue
        if not is_qualified(c, criteria):
            unit_ok = (
                criteria.equipment_type in (EquipmentType.UNKNOWN.value, "")
                or criteria.equipment_type in c.equipment_types
            )
            if unit_ok:
                report.needs_epa += 1
            else:
                report.not_qualified += 1
            continue
        option = plan_option(c, criteria, now, settings)
        if option is None:
            report.no_time += 1
            continue
        options.append(option)
    options.sort(key=rank_key)
    return options, report


def best_option(
    candidates: Sequence[TechCandidate],
    criteria: MatchCriteria,
    now: datetime,
    settings: PlanSettings,
) -> Option | None:
    options, _ = plan_options(candidates, criteria, now, settings)
    return options[0] if options else None


def assign_batch(
    requests: Sequence[tuple[MatchCriteria, float]],
    candidates: Sequence[TechCandidate],
    now: datetime,
    settings: PlanSettings,
    *,
    fairness_per_minute_waited: float = 1.0,
) -> dict[int, Option]:
    """Assign several waiting requests at once, at most one per tech, minimizing the
    total arrival time. Each request's cost is lowered by how long it has waited
    (`minutes_waited * fairness`), so people who waited longest are served first
    when there aren't enough techs.

    `requests` are (criteria, minutes_waited). Returns {request index: option}.
    """
    plans: list[list[Option | None]] = [
        [plan_option(c, criteria, now, settings) for c in candidates] for criteria, _ in requests
    ]
    cost: list[list[float | None]] = [
        [
            None
            if option is None
            else (option.arrival_at - now).total_seconds() / 60
            - waited * fairness_per_minute_waited
            for option in row
        ]
        for row, (_, waited) in zip(plans, requests, strict=True)
    ]
    pairs = min_cost_assignment(cost)
    result: dict[int, Option] = {}
    for row, col in pairs:
        option = plans[row][col]
        if option is not None:
            result[row] = option
    return result
