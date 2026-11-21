"""Companies and technicians as homeowners see them: choosing who to book, public
profile cards (for shared links), and ready-made messages for sharing a contact."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import InvalidState, NotFound
from app.domain.enums import RequestStatus
from app.domain.geo import LatLng
from app.domain.matching import Option, plan_option
from app.models import ServiceRequest, Shop, Technician
from app.services.availability_service import AvailabilityService
from app.services.matching_service import MatchingService


class ProviderService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    async def options_for(self, request: ServiceRequest) -> dict[str, list[dict[str, Any]]]:
        """Companies and technicians that could take this request, soonest first, each
        with their earliest arrival time."""
        if request.status not in (RequestStatus.ANALYZED.value, RequestStatus.WAITLISTED.value):
            raise InvalidState("Choose a company or technician before booking")
        now = self.c.clock.now()
        matching = MatchingService(self.s, self.c)
        criteria = matching.criteria_for(request)
        criteria = type(criteria)(
            location=criteria.location,
            equipment_type=criteria.equipment_type,
            requires_refrigerant_work=criteria.requires_refrigerant_work,
            excluded_technician_ids=criteria.excluded_technician_ids,
            windows=criteria.windows,  # only who can come while the homeowner is home
        )  # ignore any earlier pick: list everyone
        pool = await AvailabilityService(self.s, self.c).load_candidates(
            near=LatLng(request.lat, request.lng), now=now
        )
        options: list[Option] = []
        for a in pool:
            option = plan_option(a.candidate, criteria, now, matching.plan_settings)
            if option:
                options.append(option)
        options.sort(key=lambda o: (o.arrival_at, o.distance_km))
        techs = {
            t.id: t
            for t in [await self.s.get(Technician, o.candidate.technician_id) for o in options]
            if t is not None
        }
        shops = {
            s.id: s
            for s in [await self.s.get(Shop, sid) for sid in {o.candidate.shop_id for o in options}]
            if s is not None
        }
        tech_rows = []
        by_shop: dict[uuid.UUID, list[Option]] = defaultdict(list)
        for o in options:
            tech = techs.get(o.candidate.technician_id)
            shop = shops.get(o.candidate.shop_id)
            if tech is None or shop is None:
                continue
            by_shop[shop.id].append(o)
            tech_rows.append(
                {
                    "id": tech.id,
                    "name": tech.name,
                    "photo_url": tech.photo_url,
                    "shop_id": shop.id,
                    "shop_name": shop.name,
                    "rating": tech.rating,
                    "rating_count": tech.rating_count,
                    "certifications": tech.certifications,
                    "distance_km": round(o.distance_km, 1),
                    "arrival_at": o.arrival_at,
                }
            )
        from app.services.customer_service import CustomerService  # avoid import cycle

        home = set(await CustomerService(self.s, self.c).home_shops(request.homeowner_id))
        shop_rows = [
            {
                "your_company": shop.id in home,
                "id": shop.id,
                "name": shop.name,
                "rating": shop.rating,
                "rating_count": shop.rating_count,
                "technician_count": len(by_shop[shop.id]),
                "distance_km": round(min(o.distance_km for o in by_shop[shop.id]), 1),
                "arrival_at": min(o.arrival_at for o in by_shop[shop.id]),
            }
            for shop in shops.values()
            if by_shop[shop.id]
        ]
        # The homeowner's own company first, then soonest.
        shop_rows.sort(key=lambda r: (not r["your_company"], r["arrival_at"], r["distance_km"]))
        return {"shops": shop_rows, "technicians": tech_rows}

    async def set_choice(
        self,
        request: ServiceRequest,
        *,
        shop_id: uuid.UUID | None,
        technician_id: uuid.UUID | None,
    ) -> None:
        """Remember who the homeowner picked (None/None = soonest available)."""
        if technician_id is not None:
            tech = await self.s.get(Technician, technician_id)
            if tech is None or not tech.is_active:
                raise NotFound("That technician isn't available")
            request.preferred_technician_id = tech.id
            request.preferred_shop_id = tech.shop_id
        elif shop_id is not None:
            shop = await self.s.get(Shop, shop_id)
            if shop is None:
                raise NotFound("That company isn't available")
            request.preferred_shop_id = shop.id
            request.preferred_technician_id = None
        else:
            request.preferred_shop_id = None
            request.preferred_technician_id = None

    # --- Public cards (shared links) --------------------------------------------------
    async def public_technician(self, technician_id: uuid.UUID) -> dict[str, Any]:
        tech = await self.s.get(Technician, technician_id)
        if tech is None or not tech.is_active:
            raise NotFound("Technician not found")
        shop = await self.s.get(Shop, tech.shop_id)
        assert shop is not None
        return {
            "kind": "technician",
            "id": tech.id,
            "name": tech.name,
            "photo_url": tech.photo_url,
            "rating": tech.rating,
            "rating_count": tech.rating_count,
            "certifications": tech.certifications,
            "equipment_types": tech.equipment_types,
            "shop": self._shop_card(shop),
        }

    async def public_shop(self, shop_id: uuid.UUID) -> dict[str, Any]:
        shop = await self.s.get(Shop, shop_id)
        if shop is None:
            raise NotFound("Company not found")
        return {"kind": "shop", **self._shop_card(shop)}

    @staticmethod
    def _shop_card(shop: Shop) -> dict[str, Any]:
        city = ", ".join(p.strip() for p in (shop.address or "").split(",")[1:3]) or None
        return {
            "id": shop.id,
            "name": shop.name,
            "phone": _pretty_phone(shop.phone),
            "area": city,
            "rating": shop.rating,
            "rating_count": shop.rating_count,
            "taking_requests": shop.is_live,
        }

    # --- Sharing --------------------------------------------------------------------
    def tech_link(self, technician_id: uuid.UUID) -> str:
        return f"{self.c.settings.public_app_url.rstrip('/')}/p/technician/{technician_id}"

    def shop_link(self, shop_id: uuid.UUID) -> str:
        return f"{self.c.settings.public_app_url.rstrip('/')}/p/shop/{shop_id}"

    async def share_for(self, request: ServiceRequest) -> dict[str, Any]:
        """Ready-to-send messages recommending this job's technician and company."""
        if request.status != RequestStatus.COMPLETED.value or not request.technician_id:
            raise InvalidState("You can share a technician after the job is done")
        tech = await self.s.get(Technician, request.technician_id)
        shop = await self.s.get(Shop, request.shop_id) if request.shop_id else None
        if tech is None or shop is None:
            raise NotFound("This technician is no longer available")
        phone = _pretty_phone(shop.phone)
        call = f" Call {shop.name} at {phone} or" if phone else ""
        tech_stars = _stars(tech.rating, tech.rating_count)
        shop_stars = _stars(shop.rating, shop.rating_count)
        return {
            "technician": {
                "title": f"{tech.name} · {shop.name}",
                "url": self.tech_link(tech.id),
                "message": (
                    f"I used {tech.name} from {shop.name} for my HVAC and recommend them"
                    f"{tech_stars}.{call} book {tech.name.split()[0]} directly here: "
                    f"{self.tech_link(tech.id)}"
                ),
            },
            "shop": {
                "title": shop.name,
                "url": self.shop_link(shop.id),
                "phone": _pretty_phone(shop.phone),
                "message": (
                    f"Recommending {shop.name} for HVAC repairs{shop_stars}.{call} book them "
                    f"here: {self.shop_link(shop.id)}"
                ),
            },
        }


def _stars(rating: float | None, count: int) -> str:
    return f" (★ {rating:.1f} from {count} review{'s' if count != 1 else ''})" if rating else ""


def _pretty_phone(e164: str | None) -> str | None:
    if not e164:
        return None
    digits = "".join(ch for ch in e164 if ch.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return e164
