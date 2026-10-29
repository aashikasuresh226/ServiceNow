"""Unit tests for pure business rules."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import InvalidState
from app.domain.availability import Block, is_free_at, next_free_at, shifts_from_working_hours
from app.domain.enums import AvailabilityKind, EquipmentType, IssueCategory
from app.domain.enums import RequestStatus as S
from app.domain.geo import LatLng, haversine_km
from app.domain.matching import MatchCriteria, TechCandidate, pick_best
from app.domain.pricing import estimate_for, platform_fee
from app.domain.state_machine import ensure_transition
from app.domain.waitlist import TechSlot, estimate_wait_minutes

HOME = LatLng(33.749, -84.388)
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


def tech(
    km_north: float,
    *,
    skills: tuple[str, ...] = (),
    free: bool = True,
    equipment: tuple[str, ...] = ("central_ac",),
    certs: tuple[str, ...] = ("epa_608",),
    radius: float = 40,
    rating: float | None = None,
) -> TechCandidate:
    return TechCandidate(
        technician_id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        location=LatLng(HOME.lat + km_north / 111.0, HOME.lng),
        service_radius_km=radius,
        equipment_types=frozenset(equipment),
        certifications=frozenset(certs),
        soft_skills=frozenset(skills),
        is_free_now=free,
        rating=rating,
    )


def pick(cands: list[TechCandidate], **criteria: object) -> TechCandidate | None:
    result = pick_best(
        cands,
        MatchCriteria(location=HOME, **criteria),  # type: ignore[arg-type]
        skill_preference_max_extra_km=10,
    )
    return result.candidate if result else None


class TestMatching:
    def test_picks_closest_free_tech(self) -> None:
        near, far = tech(2), tech(8)
        assert pick([far, near]) is near

    def test_skips_busy_and_out_of_radius(self) -> None:
        busy, out_of_range, ok = tech(1, free=False), tech(3, radius=2), tech(9)
        assert pick([busy, out_of_range, ok]) is ok

    def test_requires_equipment_qualification(self) -> None:
        furnace_only = tech(1, equipment=("furnace",))
        ac = tech(5)
        assert pick([furnace_only, ac], equipment_type="central_ac") is ac

    def test_unknown_equipment_does_not_filter(self) -> None:
        furnace_only = tech(1, equipment=("furnace",))
        assert pick([furnace_only], equipment_type=EquipmentType.UNKNOWN.value) is furnace_only

    def test_refrigerant_work_requires_epa_608(self) -> None:
        no_cert, certified = tech(1, certs=()), tech(4)
        assert pick([no_cert, certified], requires_refrigerant_work=True) is certified

    def test_prefers_full_skill_match_within_detour(self) -> None:
        closest, skilled = tech(1), tech(6, skills=("patient",))
        assert pick([closest, skilled], soft_skills=frozenset({"patient"})) is skilled

    def test_closest_wins_when_skilled_tech_is_too_far(self) -> None:
        closest, skilled = tech(1), tech(20, skills=("patient",))
        assert pick([closest, skilled], soft_skills=frozenset({"patient"})) is closest

    def test_require_all_skills_filters(self) -> None:
        partial = tech(1, skills=("patient",))
        assert (
            pick([partial], soft_skills=frozenset({"patient", "tidy"}), require_all_skills=True)
            is None
        )

    def test_excludes_declined_techs(self) -> None:
        declined, other = tech(1), tech(3)
        assert (
            pick([declined, other], excluded_technician_ids=frozenset({declined.technician_id}))
            is other
        )

    def test_none_when_nobody_free(self) -> None:
        assert pick([tech(1, free=False)]) is None


class TestAvailability:
    shift = Block(AvailabilityKind.SHIFT, NOW - timedelta(hours=4), NOW + timedelta(hours=4))

    def test_free_inside_shift(self) -> None:
        assert is_free_at([self.shift], NOW)

    def test_busy_block_overrides_shift(self) -> None:
        busy = Block(AvailabilityKind.BUSY, NOW - timedelta(minutes=10), NOW + timedelta(hours=1))
        assert not is_free_at([self.shift, busy], NOW)
        assert next_free_at([self.shift, busy], NOW, timedelta(hours=24)) == busy.ends_at

    def test_not_free_outside_shift(self) -> None:
        later = Block(AvailabilityKind.SHIFT, NOW + timedelta(hours=2), NOW + timedelta(hours=6))
        assert not is_free_at([later], NOW)
        assert next_free_at([later], NOW, timedelta(hours=24)) == later.starts_at

    def test_working_hours_respect_dst(self) -> None:
        # US DST began 2026-03-08: 9:00 New York is 14:00 UTC before, 13:00 UTC after.
        hours = {"sat": [["09:00", "17:00"]], "mon": [["09:00", "17:00"]]}
        blocks = shifts_from_working_hours(hours, "America/New_York", date(2026, 3, 7), 3)
        assert [b.starts_at.astimezone(UTC).hour for b in blocks] == [14, 13]


class TestWaitlist:
    def test_first_in_line_gets_earliest_tech(self) -> None:
        slots = [TechSlot(NOW + timedelta(minutes=30), 15), TechSlot(NOW + timedelta(hours=2), 5)]
        assert (
            estimate_wait_minutes(slots, position=1, now=NOW, job_duration=timedelta(minutes=90))
            == 45
        )

    def test_later_positions_wait_longer(self) -> None:
        slots = [TechSlot(NOW, 10)]
        first = estimate_wait_minutes(slots, position=1, now=NOW, job_duration=timedelta(hours=1))
        second = estimate_wait_minutes(slots, position=2, now=NOW, job_duration=timedelta(hours=1))
        assert (first, second) == (10, 80)

    def test_no_slots(self) -> None:
        assert (
            estimate_wait_minutes([], position=1, now=NOW, job_duration=timedelta(hours=1)) is None
        )


class TestPricingAndStates:
    def test_estimate_includes_diagnostic_fee(self) -> None:
        est = estimate_for(IssueCategory.CAPACITOR)
        assert est.total_low_cents == est.diagnostic_fee_cents + est.repair_low_cents

    @pytest.mark.parametrize(
        ("amount", "bps", "fee"), [(10000, 1500, 1500), (333, 1500, 50), (0, 1500, 0)]
    )
    def test_platform_fee_rounding(self, amount: int, bps: int, fee: int) -> None:
        assert platform_fee(amount, bps) == fee

    def test_illegal_transition_rejected(self) -> None:
        with pytest.raises(InvalidState):
            ensure_transition(S.DRAFT, S.COMPLETED)

    def test_haversine_sanity(self) -> None:
        assert 1.0 < haversine_km(HOME, LatLng(HOME.lat + 0.01, HOME.lng)) < 1.2
