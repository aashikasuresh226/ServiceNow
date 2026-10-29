"""Address → coordinates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import AppError, ExternalServiceError
from app.domain.geo import LatLng


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    location: LatLng
    formatted_address: str


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult: ...


# Demo city: Atlanta, GA. Seed data places shops around here.
DEMO_CENTER = LatLng(33.7490, -84.3880)


class FakeGeocoder:
    """Deterministically places any address within ~12 km of the demo center."""

    async def geocode(self, address: str) -> GeocodeResult:
        cleaned = " ".join(address.split())
        if len(cleaned) < 5:
            raise AppError("Please enter a full street address", code="invalid_address")
        digest = hashlib.sha256(cleaned.lower().encode()).digest()
        dlat = (digest[0] / 255 - 0.5) * 0.2
        dlng = (digest[1] / 255 - 0.5) * 0.2
        return GeocodeResult(LatLng(DEMO_CENTER.lat + dlat, DEMO_CENTER.lng + dlng), cleaned)


class MapboxGeocoder:
    def __init__(self, *, token: str, http: httpx.AsyncClient) -> None:
        self._token = token
        self._http = http

    async def geocode(self, address: str) -> GeocodeResult:
        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(address)}.json"
        try:
            response = await self._http.get(
                url,
                params={
                    "access_token": self._token,
                    "country": "us",
                    "limit": 1,
                    "types": "address",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Address lookup is unavailable") from exc
        features = response.json().get("features") or []
        if not features:
            raise AppError("We couldn't find that address", code="invalid_address")
        lng, lat = features[0]["center"]
        return GeocodeResult(LatLng(lat, lng), features[0].get("place_name", address))
