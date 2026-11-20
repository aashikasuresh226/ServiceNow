"""Address → coordinates.

Default: the US Census Bureau geocoder. It's free, needs no key and covers
every US street address (it needs the city and state, or the ZIP code).
Google or Mapbox can be used instead with an API key.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.errors import AppError, ExternalServiceError
from app.domain.geo import LatLng

log = logging.getLogger(__name__)

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
GOOGLE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
NOT_FOUND_MESSAGE = "We couldn't find that address. Include the street, city, state and ZIP code."


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    location: LatLng
    formatted_address: str


class Geocoder(Protocol):
    async def geocode(self, address: str) -> GeocodeResult: ...


def _clean(address: str) -> str:
    cleaned = " ".join(address.split())
    if len(cleaned) < 8 or not any(ch.isdigit() for ch in cleaned):
        raise AppError(
            "Please enter a full street address with house number, city, state and ZIP",
            code="invalid_address",
        )
    return cleaned


class CensusGeocoder:
    def __init__(self, *, http: httpx.AsyncClient, url: str = CENSUS_URL) -> None:
        self._http = http
        self._url = url

    async def geocode(self, address: str) -> GeocodeResult:
        cleaned = _clean(address)
        try:
            response = await self._http.get(
                self._url,
                params={"address": cleaned, "benchmark": "Public_AR_Current", "format": "json"},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Census geocoder failed: %s", exc)
            raise ExternalServiceError("Address lookup is unavailable. Please try again.") from exc
        matches = (data.get("result") or {}).get("addressMatches") or []
        if not matches:
            raise AppError(NOT_FOUND_MESSAGE, code="invalid_address")
        match = matches[0]
        coords = match["coordinates"]
        return GeocodeResult(
            LatLng(float(coords["y"]), float(coords["x"])),
            format_census_address(match.get("matchedAddress") or cleaned),
        )


def format_census_address(raw: str) -> str:
    """'675 PONCE DE LEON AVE NE, ATLANTA, GA, 30308'
    → '675 Ponce De Leon Ave NE, Atlanta, GA 30308'."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) >= 4:
        street, city, state, zip_code = parts[0], parts[1], parts[2], parts[3]
        return f"{_title(street)}, {_title(city)}, {state.upper()} {zip_code}"
    return _title(raw)


_KEEP_UPPER = {"NE", "NW", "SE", "SW", "N", "S", "E", "W", "US", "GA", "SR"}


def _title(text: str) -> str:
    return " ".join(w if w in _KEEP_UPPER else w.capitalize() for w in text.split())


class GoogleGeocoder:
    def __init__(self, *, api_key: str, http: httpx.AsyncClient) -> None:
        self._key = api_key
        self._http = http

    async def geocode(self, address: str) -> GeocodeResult:
        cleaned = _clean(address)
        try:
            response = await self._http.get(
                GOOGLE_URL,
                params={"address": cleaned, "components": "country:US", "key": self._key},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExternalServiceError("Address lookup is unavailable. Please try again.") from exc
        if data.get("status") == "ZERO_RESULTS" or not data.get("results"):
            raise AppError(NOT_FOUND_MESSAGE, code="invalid_address")
        if data.get("status") != "OK":
            log.warning("Google geocoding error: %s", data.get("status"))
            raise ExternalServiceError("Address lookup is unavailable. Please try again.")
        result = data["results"][0]
        if not {"street_address", "premise", "subpremise"} & set(result.get("types", [])):
            raise AppError(NOT_FOUND_MESSAGE, code="invalid_address")
        loc = result["geometry"]["location"]
        return GeocodeResult(LatLng(loc["lat"], loc["lng"]), result["formatted_address"])


class MapboxGeocoder:
    def __init__(self, *, token: str, http: httpx.AsyncClient) -> None:
        self._token = token
        self._http = http

    async def geocode(self, address: str) -> GeocodeResult:
        cleaned = _clean(address)
        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(cleaned)}.json"
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
            raise ExternalServiceError("Address lookup is unavailable. Please try again.") from exc
        features = response.json().get("features") or []
        if not features:
            raise AppError(NOT_FOUND_MESSAGE, code="invalid_address")
        lng, lat = features[0]["center"]
        return GeocodeResult(LatLng(lat, lng), features[0].get("place_name", cleaned))


# Automated tests only (never used by the running app): places any address near Atlanta.
TEST_CENTER = LatLng(33.7490, -84.3880)


class FakeGeocoder:
    async def geocode(self, address: str) -> GeocodeResult:
        cleaned = _clean(address)
        digest = hashlib.sha256(cleaned.lower().encode()).digest()
        dlat = (digest[0] / 255 - 0.5) * 0.2
        dlng = (digest[1] / 255 - 0.5) * 0.2
        return GeocodeResult(LatLng(TEST_CENTER.lat + dlat, TEST_CENTER.lng + dlng), cleaned)
