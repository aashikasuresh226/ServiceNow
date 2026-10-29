"""Geographic helpers.

Distances are straight-line (great-circle). That is enough for matching within a
service radius; swap in a routing API for drive times when needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class LatLng:
    lat: float
    lng: float

    def __post_init__(self) -> None:
        if not -90 <= self.lat <= 90 or not -180 <= self.lng <= 180:
            raise ValueError(f"Invalid coordinates: {self.lat}, {self.lng}")


def haversine_km(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    dlat, dlng = lat2 - lat1, lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def travel_minutes(distance_km: float, speed_kmh: float) -> int:
    """Rough drive time with a road-winding factor and a 5-minute floor."""
    road_factor = 1.3
    return max(5, round(distance_km * road_factor / speed_kmh * 60))
