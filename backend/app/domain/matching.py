"""The matching engine: pick the best available, qualified technician.

Pure functions over plain data, so the ranking rules are easy to read and test.

Rules (in order):
1. Hard filters: active, shop can receive jobs, within the tech's service radius,
   qualified for the equipment, EPA 608 when refrigerant work is likely, not
   previously declined for this request.
2. Must be free *now* (on shift, not booked, no active marketplace job).
3. If the homeowner requires all soft skills, drop techs missing any.
4. Prefer the closest tech that has all requested soft skills, unless they are
   more than `skill_preference_max_extra_km` farther than the closest tech
   overall; then the closest tech wins. Ties break on number of skills matched,
   then rating.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.enums import Certification, EquipmentType
from app.domain.geo import LatLng, haversine_km


@dataclass(frozen=True, slots=True)
class TechCandidate:
    technician_id: uuid.UUID
    shop_id: uuid.UUID
    location: LatLng
    service_radius_km: float
    equipment_types: frozenset[str]
    certifications: frozenset[str]
    soft_skills: frozenset[str]
    is_free_now: bool
    rating: float | None = None


@dataclass(frozen=True, slots=True)
class MatchCriteria:
    location: LatLng
    equipment_type: str = EquipmentType.UNKNOWN.value
    requires_refrigerant_work: bool = False
    soft_skills: frozenset[str] = field(default_factory=frozenset)
    require_all_skills: bool = False
    excluded_technician_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate: TechCandidate
    distance_km: float
    skills_matched: int
    has_all_skills: bool


def is_qualified(c: TechCandidate, criteria: MatchCriteria) -> bool:
    unit = criteria.equipment_type
    if unit and unit != EquipmentType.UNKNOWN.value and unit not in c.equipment_types:
        return False
    return not (
        criteria.requires_refrigerant_work and Certification.EPA_608.value not in c.certifications
    )


def eligible_candidates(
    candidates: Sequence[TechCandidate], criteria: MatchCriteria, *, require_free_now: bool
) -> list[RankedCandidate]:
    """Apply the hard filters and attach distance + skill-match info."""
    ranked: list[RankedCandidate] = []
    for c in candidates:
        if c.technician_id in criteria.excluded_technician_ids:
            continue
        if require_free_now and not c.is_free_now:
            continue
        if not is_qualified(c, criteria):
            continue
        distance = haversine_km(c.location, criteria.location)
        if distance > c.service_radius_km:
            continue
        matched = len(criteria.soft_skills & c.soft_skills)
        has_all = matched == len(criteria.soft_skills)
        if criteria.require_all_skills and not has_all:
            continue
        ranked.append(RankedCandidate(c, distance, matched, has_all))
    return ranked


def pick_best(
    candidates: Sequence[TechCandidate],
    criteria: MatchCriteria,
    *,
    skill_preference_max_extra_km: float,
) -> RankedCandidate | None:
    """Return the best tech who is free right now, or None (→ waitlist)."""
    pool = eligible_candidates(candidates, criteria, require_free_now=True)
    if not pool:
        return None

    def tiebreak(r: RankedCandidate) -> tuple[float, int, float]:
        return (r.distance_km, -r.skills_matched, -(r.candidate.rating or 0.0))

    closest = min(pool, key=tiebreak)
    if criteria.soft_skills:
        full_matches = [r for r in pool if r.has_all_skills]
        if full_matches:
            best_full = min(full_matches, key=tiebreak)
            if best_full.distance_km - closest.distance_km <= skill_preference_max_extra_km:
                return best_full
    return closest
