"""Unit tests for pure business rules."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.errors import InvalidState
from app.domain.assignment import min_cost_assignment
from app.domain.availability import (
    Block,
    earliest_window,
    is_free_at,
    next_free_at,
    shifts_from_working_hours,
)
from app.domain.enums import AvailabilityKind, EquipmentType, IssueCategory
from app.domain.enums import RequestStatus as S
from app.domain.geo import LatLng, haversine_km
from app.domain.matching import (
    MatchCriteria,
    PlanSettings,
    TechCandidate,
    assign_batch,
    best_option,
    plan_options,
)
from app.domain.pricing import estimate_for, platform_fee
from app.domain.state_machine import ensure_transition

HOME = LatLng(33.749, -84.388)
NOW = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)


SHIFT = Block(AvailabilityKind.SHIFT, NOW - timedelta(hours=8), NOW + timedelta(hours=8))
PLAN = PlanSettings(job_duration=timedelta(minutes=90), speed_kmh=40, horizon=timedelta(days=7))


def tech(
    km_north: float,
    *,
    blocks: tuple[Block, ...] = (SHIFT,),
    equipment: tuple[str, ...] = ("central_ac",),
    certs: tuple[str, ...] = ("epa_608",),
    radius: float = 40,
    rating: float | None = None,
    jobs_today: int = 0,
) -> TechCandidate:
    return TechCandidate(
        technician_id=uuid.uuid4(),
        shop_id=uuid.uuid4(),
        location=LatLng(HOME.lat + km_north / 111.0, HOME.lng),
        service_radius_km=radius,
        equipment_types=frozenset(equipment),
        certifications=frozenset(certs),
        blocks=blocks,
        jobs_today=jobs_today,
        rating=rating,
    )


def busy(start_min: int, end_min: int) -> Block:
    return Block(
        AvailabilityKind.BUSY, NOW + timedelta(minutes=start_min), NOW + timedelta(minutes=end_min)
    )


def pick(cands: list[TechCandidate], **criteria: object) -> TechCandidate | None:
    result = best_option(cands, MatchCriteria(location=HOME, **criteria), NOW, PLAN)  # type: ignore[arg-type]
    return result.candidate if result else None


class TestMatching:
    def test_picks_closest_free_tech(self) -> None:
        near, far = tech(2), tech(8)
        assert pick([far, near]) is near

    def test_earliest_arrival_beats_distance(self) -> None:
        # The closest tech is on a job for the next 2 hours; a farther free tech arrives first.
        near_busy = tech(2, blocks=(SHIFT, busy(-30, 120)))
        far_free = tech(15)
        assert pick([near_busy, far_free]) is far_free

    def test_out_of_radius_excluded(self) -> None:
        assert pick([tech(50, radius=40)]) is None

    def test_requires_equipment_qualification(self) -> None:
        furnace_only = tech(1, equipment=("furnace",))
        ac = tech(5)
        assert pick([furnace_only, ac], equipment_type="central_ac") is ac

    def test_unknown_equipment_does_not_filter(self) -> None:
        furnace_only = tech(1, equipment=("furnace",))
        assert pick([furnace_only], equipment_type=EquipmentType.UNKNOWN.value) is furnace_only

    def test_refrigerant_work_requires_epa_608(self) -> None:
        uncertified = tech(1, certs=())
        certified = tech(5)
        assert pick([uncertified, certified], requires_refrigerant_work=True) is certified

    def test_excludes_declined_techs(self) -> None:
        a, b = tech(1), tech(3)
        assert pick([a, b], excluded_technician_ids=frozenset({a.technician_id})) is b

    def test_ties_go_to_fewer_jobs_then_rating(self) -> None:
        busy_day = tech(3, jobs_today=4, rating=5.0)
        light_day = tech(3, jobs_today=1, rating=4.0)
        assert pick([busy_day, light_day]) is light_day

    def test_after_hours_books_next_shift(self) -> None:
        # Off shift now; next shift starts in 10 hours: book the first slot of it.
        tomorrow = Block(
            AvailabilityKind.SHIFT, NOW + timedelta(hours=10), NOW + timedelta(hours=19)
        )
        result = best_option([tech(4, blocks=(tomorrow,))], MatchCriteria(location=HOME), NOW, PLAN)
        assert result is not None
        assert result.start_at == tomorrow.starts_at
        assert result.arrival_at == tomorrow.starts_at + timedelta(minutes=result.travel_minutes)

    def test_job_must_fit_before_shift_ends(self) -> None:
        # 20 minutes left in today's shift: not enough for travel + a 90-minute job.
        ending = Block(
            AvailabilityKind.SHIFT, NOW - timedelta(hours=8), NOW + timedelta(minutes=20)
        )
        tomorrow = Block(
            AvailabilityKind.SHIFT, NOW + timedelta(hours=16), NOW + timedelta(hours=24)
        )
        result = best_option(
            [tech(4, blocks=(ending, tomorrow))], MatchCriteria(location=HOME), NOW, PLAN
        )
        assert result is not None and result.start_at == tomorrow.starts_at

    def test_fits_in_gap_between_bookings(self) -> None:
        # Free 60-240 minutes from now: the job (≈6 min drive + 90) goes in that gap.
        t = tech(4, blocks=(SHIFT, busy(-60, 60), busy(240, 400)))
        result = best_option([t], MatchCriteria(location=HOME), NOW, PLAN)
        assert result is not None and result.start_at == NOW + timedelta(minutes=60)
        # ...but a gap too short for the job is skipped.
        t = tech(4, blocks=(SHIFT, busy(-60, 60), busy(100, 300)))
        result = best_option([t], MatchCriteria(location=HOME), NOW, PLAN)
        assert result is not None and result.start_at == NOW + timedelta(minutes=300)

    def test_report_explains_no_match(self) -> None:
        options, report = plan_options(
            [tech(1, equipment=("furnace",)), tech(80, radius=40), tech(2, blocks=())],
            MatchCriteria(location=HOME, equipment_type="central_ac"),
            NOW,
            PLAN,
        )
        assert options == []
        assert (report.nearby, report.not_qualified, report.out_of_range, report.no_time) == (
            3,
            1,
            1,
            1,
        )
        assert report.message()


class TestBatchAssignment:
    def test_hungarian_beats_first_come_greedy(self) -> None:
        # Request A (waited longest) is equally close to both techs; request B is only
        # reachable by tech X. Greedy would give X to A and leave B waiting; the
        # optimal assignment serves both.
        x = tech(0, radius=40)
        x_loc = x.location
        a_crit = MatchCriteria(location=LatLng(x_loc.lat, x_loc.lng))
        b_crit = MatchCriteria(location=LatLng(x_loc.lat + 0.3, x_loc.lng))  # ~33 km north
        y_tech = tech(0, radius=10)
        result = assign_batch([(a_crit, 30.0), (b_crit, 5.0)], [x, y_tech], NOW, PLAN)
        assert result[0].candidate is y_tech
        assert result[1].candidate is x

    def test_longest_waiting_wins_when_short_of_techs(self) -> None:
        only = tech(3)
        crit = MatchCriteria(location=HOME)
        result = assign_batch([(crit, 2.0), (crit, 40.0)], [only], NOW, PLAN)
        assert set(result) == {1}

    def test_assignment_matches_brute_force(self) -> None:
        import itertools
        import random

        rng = random.Random(7)
        for _ in range(200):
            rows, cols = rng.randint(1, 5), rng.randint(1, 5)
            cost = [
                [
                    None if rng.random() < 0.3 else round(rng.uniform(-20, 60), 1)
                    for _ in range(cols)
                ]
                for _ in range(rows)
            ]
            got = min_cost_assignment(cost)
            best = None
            for perm in itertools.permutations(range(max(rows, cols)), rows):
                pairs = [(i, j) for i, j in enumerate(perm) if j < cols and cost[i][j] is not None]
                key = (-len(pairs), round(sum(cost[i][j] or 0 for i, j in pairs), 6))
                best = key if best is None or key < best else best
            assert (-len(got), round(sum(cost[i][j] or 0 for i, j in got), 6)) == best


class TestAvailability:
    shift = Block(AvailabilityKind.SHIFT, NOW - timedelta(hours=4), NOW + timedelta(hours=4))

    def test_free_inside_shift(self) -> None:
        assert is_free_at([self.shift], NOW)

    def test_busy_block_overrides_shift(self) -> None:
        b = Block(AvailabilityKind.BUSY, NOW - timedelta(minutes=10), NOW + timedelta(hours=1))
        assert not is_free_at([self.shift, b], NOW)
        assert next_free_at([self.shift, b], NOW, timedelta(hours=24)) == b.ends_at

    def test_back_to_back_shifts_merge(self) -> None:
        # 24/7 written as two days: a job can run across midnight.
        day1 = Block(AvailabilityKind.SHIFT, NOW - timedelta(hours=23), NOW + timedelta(minutes=30))
        day2 = Block(AvailabilityKind.SHIFT, NOW + timedelta(minutes=30), NOW + timedelta(hours=24))
        start = earliest_window(
            [day1, day2],
            earliest=NOW,
            need=timedelta(minutes=100),
            latest_start=NOW + timedelta(days=1),
        )
        assert start == NOW

    def test_working_hours_respect_dst(self) -> None:
        # US DST began 2026-03-08: 9:00 New York is 14:00 UTC before, 13:00 UTC after.
        hours = {"sat": [["09:00", "17:00"]], "mon": [["09:00", "17:00"]]}
        blocks = shifts_from_working_hours(hours, "America/New_York", date(2026, 3, 7), 3)
        assert [b.starts_at.astimezone(UTC).hour for b in blocks] == [14, 13]


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
