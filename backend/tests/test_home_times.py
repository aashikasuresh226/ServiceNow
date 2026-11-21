"""When the homeowner is home: validation, matching inside their times, and who sees them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.clock import FrozenClock
from app.core.errors import AppError
from app.domain.matching import MatchCriteria, best_option
from app.services import home_times
from tests.conftest import SeededShop, analyzed_request, homeowner_login, shop_login
from tests.test_domain import HOME, NOW, PLAN, busy, tech

H = timedelta(hours=1)


class TestNormalize:
    def test_merges_sorts_and_clips(self) -> None:
        got = home_times.normalize(
            [
                (NOW + 5 * H, NOW + 6 * H),
                (NOW - 2 * H, NOW + H),  # started earlier: clipped to now
                (NOW + 6 * H, NOW + 8 * H),  # touches the first: merged
                (NOW + 10 * 24 * H, NOW + 11 * 24 * H),  # beyond the week: dropped
            ],
            now=NOW,
            horizon=7 * 24 * H,
        )
        assert got == [(NOW, NOW + H), (NOW + 5 * H, NOW + 8 * H)]

    def test_rejects_bad_times(self) -> None:
        week = 7 * 24 * H
        with pytest.raises(AppError, match="after its start"):
            home_times.normalize([(NOW + 2 * H, NOW + H)], now=NOW, horizon=week)
        with pytest.raises(AppError, match="hasn't passed"):
            home_times.normalize([(NOW - 3 * H, NOW - H)], now=NOW, horizon=week)
        with pytest.raises(AppError, match="30 minutes"):
            short = (NOW + H, NOW + H + timedelta(minutes=10))
            home_times.normalize([short], now=NOW, horizon=week)
        with pytest.raises(AppError, match="time zone"):
            naive = datetime(2026, 7, 15, 18, 0)
            home_times.normalize([(naive, naive + H)], now=NOW, horizon=week)

    def test_describe_in_the_shop_time_zone(self) -> None:
        stored = home_times.dump([(NOW + H, NOW + 4 * H + timedelta(minutes=30))])
        # NOW is 16:00 UTC = noon in New York
        assert home_times.describe(stored, "America/New_York") == "Wed Jul 15 1:00 PM-4:30 PM"


class TestMatchingInsideHomeTimes:
    def test_arrives_and_finishes_inside_a_time(self) -> None:
        criteria = MatchCriteria(location=HOME, windows=((NOW + 5 * H, NOW + 9 * H),))
        result = best_option([tech(4)], criteria, NOW, PLAN)
        assert result is not None
        assert result.arrival_at == NOW + 5 * H  # free now, but waits until they're home
        assert result.arrival_at + PLAN.job_duration <= NOW + 9 * H

    def test_window_too_short_for_the_job_is_skipped(self) -> None:
        criteria = MatchCriteria(
            location=HOME, windows=((NOW + H, NOW + 2 * H), (NOW + 5 * H, NOW + 9 * H))
        )
        result = best_option([tech(4)], criteria, NOW, PLAN)
        assert result is not None and result.arrival_at == NOW + 5 * H

    def test_busy_tech_loses_to_one_free_in_their_time(self) -> None:
        criteria = MatchCriteria(location=HOME, windows=((NOW + 5 * H, NOW + 8 * H),))
        booked, free = tech(1, blocks=(busy(-60, 9 * 60),)), tech(10)
        result = best_option([booked, free], criteria, NOW, PLAN)
        assert result is not None and result.candidate is free

    def test_all_times_passed_means_no_match(self) -> None:
        assert best_option([tech(4)], MatchCriteria(location=HOME, windows=()), NOW, PLAN) is None


async def test_homeowner_sets_times_and_everyone_sees_them(
    client: httpx.AsyncClient, clock: FrozenClock, shops: dict[str, SeededShop]
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    now = clock.now()
    later = [
        {"start": (now + 5 * H).isoformat(), "end": (now + 8 * H).isoformat()},
        {"start": (now + 26 * H).isoformat(), "end": (now + 30 * H).isoformat()},
    ]
    r = await client.put(f"/requests/{rid}/availability", headers=home, json={"ranges": later})
    assert r.status_code == 200, r.text
    assert len(r.json()["availability"]) == 2

    body = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    assert body["status"] == "proposed"
    arrival = datetime.fromisoformat(body["technician"]["arrival_at"])
    assert now + 5 * H <= arrival <= now + 8 * H - timedelta(minutes=90)

    # Locked once booking has started.
    r = await client.put(f"/requests/{rid}/availability", headers=home, json={"ranges": []})
    assert r.json()["error"]["code"] == "times_locked"

    await client.post(f"/requests/{rid}/confirm", headers=home)
    shop = await shop_login(client, shops["near"], clock)
    job = (await client.get(f"/shop/jobs/{rid}", headers=shop)).json()
    assert job["customer_availability"][0]["start"].startswith(
        (now + 5 * H).astimezone(UTC).isoformat()[:16]
    )
    options = (await client.get(f"/shop/jobs/{rid}/technician-options", headers=shop)).json()
    assert options  # the shop's technicians, checked against the customer's times


async def test_clearing_times_means_any_time(client: httpx.AsyncClient) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    r = await client.put(f"/requests/{rid}/availability", headers=home, json={"ranges": []})
    assert r.status_code == 200 and r.json()["availability"] is None
