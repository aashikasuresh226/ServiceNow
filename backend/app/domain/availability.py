"""Availability math over SHIFT and BUSY blocks.

A tech is *free* at time t when t is inside a SHIFT block and not inside any
BUSY block, and they have no active job in our marketplace.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.domain.enums import AvailabilityKind

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True, slots=True)
class Block:
    kind: AvailabilityKind
    starts_at: datetime
    ends_at: datetime
    label: str | None = None
    source: str | None = None

    def contains(self, t: datetime) -> bool:
        return self.starts_at <= t < self.ends_at


def is_free_at(blocks: Iterable[Block], t: datetime) -> bool:
    blocks = list(blocks)
    on_shift = any(b.kind == AvailabilityKind.SHIFT and b.contains(t) for b in blocks)
    busy = any(b.kind == AvailabilityKind.BUSY and b.contains(t) for b in blocks)
    return on_shift and not busy


def next_free_at(blocks: Sequence[Block], now: datetime, horizon: timedelta) -> datetime | None:
    """Earliest moment in [now, now + horizon) when the tech is free, or None.

    Freedom can only begin at `now`, at a shift start or at a busy end, so it is
    enough to test those candidate instants in order.
    """
    end = now + horizon
    candidates = {now}
    for b in blocks:
        if b.kind == AvailabilityKind.SHIFT and now <= b.starts_at < end:
            candidates.add(b.starts_at)
        if b.kind == AvailabilityKind.BUSY and now <= b.ends_at < end:
            candidates.add(b.ends_at)
    for t in sorted(candidates):
        if is_free_at(blocks, t):
            return t
    return None


def merged_shifts(blocks: Iterable[Block]) -> list[tuple[datetime, datetime]]:
    """Shift time as sorted, non-overlapping ranges (back-to-back shifts are joined, so
    an overnight 24/7 schedule is one long range)."""
    ranges = sorted((b.starts_at, b.ends_at) for b in blocks if b.kind == AvailabilityKind.SHIFT)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def earliest_window(
    blocks: Sequence[Block], *, earliest: datetime, need: timedelta, latest_start: datetime
) -> datetime | None:
    """Earliest start t in [earliest, latest_start] such that [t, t + need) lies inside
    shift time and overlaps no busy time. None if there's no such window.

    The answer is always `earliest`, a shift start, or the end of a busy block, so only
    those instants need checking: O(B log B) for B blocks.
    """
    shifts = merged_shifts(blocks)
    busy = sorted((b.starts_at, b.ends_at) for b in blocks if b.kind == AvailabilityKind.BUSY)
    candidates = {earliest}
    candidates.update(start for start, _ in shifts if start > earliest)
    candidates.update(end for _, end in busy if end > earliest)
    for t in sorted(candidates):
        if t > latest_start:
            return None
        finish = t + need
        if not any(start <= t and finish <= end for start, end in shifts):
            continue
        if any(b_start < finish and b_end > t for b_start, b_end in busy):
            continue
        return t
    return None


def shifts_from_working_hours(
    hours: dict[str, list[list[str]]], tz_name: str, start_day: date, days: int
) -> list[Block]:
    """Expand a weekly schedule ({"mon": [["08:00","17:00"]]}) into SHIFT blocks.

    Times are local to the shop's timezone, so DST is handled by zoneinfo.
    "00:00"-"24:00" means the whole day.
    """
    tz = ZoneInfo(tz_name)
    blocks: list[Block] = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        for start_s, end_s in hours.get(WEEKDAYS[day.weekday()], []):
            start = datetime.combine(day, _parse_time(start_s), tzinfo=tz)
            if end_s == "24:00":
                end = datetime.combine(day + timedelta(days=1), time(0, 0), tzinfo=tz)
            else:
                end = datetime.combine(day, _parse_time(end_s), tzinfo=tz)
            if end <= start:
                raise ValueError(f"Shift must end after it starts: {start_s}-{end_s}")
            blocks.append(Block(AvailabilityKind.SHIFT, start, end))
    return blocks


def _parse_time(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def validate_working_hours(hours: dict[str, list[list[str]]]) -> None:
    for day, ranges in hours.items():
        if day not in WEEKDAYS:
            raise ValueError(f"Unknown weekday '{day}'")
        for pair in ranges:
            if len(pair) != 2:
                raise ValueError("Each range must be [start, end]")
            start, end = pair
            _parse_time(start)
            if end != "24:00":
                _parse_time(end)
                if _parse_time(end) <= _parse_time(start):
                    raise ValueError(f"Range {start}-{end} on {day} ends before it starts")
