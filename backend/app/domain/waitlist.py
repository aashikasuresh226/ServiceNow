"""Live waitlist estimate: how long until this homeowner reaches a technician.

Model: each eligible tech becomes reachable at (next free time + travel time).
Homeowners ahead of you in the queue take the earliest slots first; after a
tech serves someone they free up again one average job later. So your ETA is
the start of the k-th slot (k = your position) in that merged timeline.
"""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, slots=True)
class TechSlot:
    available_at: datetime  # when the tech is next free
    travel_minutes: int  # drive time to this homeowner


def estimate_wait_minutes(
    slots: Sequence[TechSlot],
    *,
    position: int,
    now: datetime,
    job_duration: timedelta,
) -> int | None:
    """Minutes until a tech can arrive for the homeowner at `position` (1-based).

    Returns None when no eligible tech will be free in the planning horizon.
    """
    if position < 1:
        raise ValueError("position is 1-based")
    if not slots:
        return None

    # Heap of (time the tech can start driving to the next customer, travel minutes)
    heap = [(max(s.available_at, now), s.travel_minutes) for s in slots]
    heapq.heapify(heap)
    arrival = now
    for _ in range(position):
        free_at, travel = heapq.heappop(heap)
        arrival = free_at + timedelta(minutes=travel)
        heapq.heappush(heap, (arrival + job_duration, travel))
    return max(1, round((arrival - now).total_seconds() / 60))
