"""When the homeowner is home: the time ranges they entered for a visit.

Stored on the request as [[start, end], ...] in UTC (ISO 8601). Matching only picks a
technician who can arrive and finish the job inside one range (domain/matching.py);
no ranges means any time.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from app.core.errors import AppError

MAX_RANGES = 20
MIN_RANGE = timedelta(minutes=30)


def normalize(
    ranges: Iterable[tuple[datetime, datetime]], *, now: datetime, horizon: timedelta
) -> list[tuple[datetime, datetime]]:
    """Validated, clipped to [now, now + horizon], sorted, and merged where they touch."""
    items = []
    for start, end in ranges:
        if start.tzinfo is None or end.tzinfo is None:
            raise AppError("Times need a time zone", code="time_zone_missing")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if end <= start:
            raise AppError("Each end time must be after its start time", code="time_order")
        if end <= now:
            continue  # already over
        start = max(start, now)
        end = min(end, now + horizon)
        if start < end:
            items.append((start, end))
    if len(items) > MAX_RANGES:
        raise AppError(f"Add at most {MAX_RANGES} times", code="too_many_times")
    items.sort()
    merged: list[tuple[datetime, datetime]] = []
    for start, end in items:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    if not merged:
        raise AppError("Add at least one time that hasn't passed", code="times_passed")
    if all(end - start < MIN_RANGE for start, end in merged):
        raise AppError(
            "Add a time of at least 30 minutes so a technician can fit the visit",
            code="times_too_short",
        )
    return merged


def dump(ranges: list[tuple[datetime, datetime]]) -> list[list[str]]:
    return [[start.isoformat(), end.isoformat()] for start, end in ranges]


def load(stored: list[list[str]] | None) -> list[tuple[datetime, datetime]] | None:
    if stored is None:
        return None
    return [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in stored]


def upcoming(
    stored: list[list[str]] | None, now: datetime
) -> tuple[tuple[datetime, datetime], ...] | None:
    """The parts that haven't passed yet (None: any time; empty: all have passed)."""
    ranges = load(stored)
    if ranges is None:
        return None
    return tuple((max(s, now), e) for s, e in ranges if e > now)


def describe(stored: list[list[str]] | None, timezone: str) -> str | None:
    """ "Sat Nov 21 5:00-8:30 PM; Sun Nov 22 9:00 AM-1:00 PM" in the shop's time zone."""
    from zoneinfo import ZoneInfo

    ranges = load(stored)
    if not ranges:
        return None
    zone = ZoneInfo(timezone)

    def clock(t: datetime) -> str:
        return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"

    parts = []
    for start, end in ranges:
        a, b = start.astimezone(zone), end.astimezone(zone)
        day = f"{a:%a %b} {a.day}"
        parts.append(f"{day} {clock(a)}-{clock(b)}")
    return "; ".join(parts)
