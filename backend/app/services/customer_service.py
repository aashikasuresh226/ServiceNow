"""A shop's existing customers: imported from Housecall Pro, invited to the app with a
personal link, and linked to their homeowner account when they join.

Nobody is signed up without their consent: the shop sends the invite from its own phone
or email (one tap in the portal), and the customer creates their own account. When they
do, we recognise them by the email (verified by Google) the shop has on file, or by their
personal invite link together with the same phone number, and:
- their account is linked to the shop's customer record (the shop sees "Using the app");
- the shop gets first look at their requests (see MatchingService._rank);
- the homeowner app suggests the address the shop has on file.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.container import Container
from app.core.errors import AppError, NotFound
from app.integrations.scheduling.housecall_pro import HcpCustomer
from app.models import Homeowner, ShopCustomer
from app.models.shop import Shop
from app.services.phone import normalize_phone

log = logging.getLogger(__name__)

HCP = "housecall_pro"
APP = "app"  # joined through the shop's invite link, not in the shop's software
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to type from a poster


def new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(8))


def _phone_or_none(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return normalize_phone(raw)
    except AppError:
        return None


def status_of(row: ShopCustomer) -> str:
    if row.homeowner_id:
        return "joined"
    return "invited" if row.invited_at else "not_invited"


@dataclass(frozen=True, slots=True)
class InviteInfo:
    shop_id: uuid.UUID
    shop_name: str
    shop_phone: str | None
    customer: ShopCustomer | None  # None: the shop-wide link


class CustomerService:
    def __init__(self, session: AsyncSession, container: Container) -> None:
        self.s = session
        self.c = container

    # --- Importing ------------------------------------------------------------------------
    async def upsert_hcp(self, shop: Shop, customer: HcpCustomer) -> ShopCustomer:
        row = await self.s.scalar(
            select(ShopCustomer).where(
                ShopCustomer.shop_id == shop.id,
                ShopCustomer.provider == HCP,
                ShopCustomer.external_id == customer.id,
            )
        )
        if row is None:
            row = ShopCustomer(
                shop_id=shop.id, provider=HCP, external_id=customer.id, invite_code=new_code()
            )
            self.s.add(row)
        phone = _phone_or_none(customer.phone)
        if row.name != customer.name:
            row.name = customer.name
        if phone != row.phone:
            row.phone = phone
        if (customer.email or None) != row.email:
            row.email = customer.email or None
        if customer.address and customer.address != row.address:
            row.address = customer.address
        if row.homeowner_id is None:
            await self._match_existing_homeowner(row)
        return row

    async def import_all(self, shop: Shop, customers: list[HcpCustomer]) -> int:
        for customer in customers:
            await self.upsert_hcp(shop, customer)
        shop.customers_imported_at = self.c.clock.now()
        await self.s.flush()
        return len(customers)

    async def _match_existing_homeowner(self, row: ShopCustomer) -> None:
        """A customer the shop just imported who already uses the app."""
        conditions: list[ColumnElement[bool]] = []
        if row.phone_hash:
            # Only a number proven to be theirs (not just typed in at sign-up).
            conditions.append(
                (Homeowner.phone_hash == row.phone_hash) & Homeowner.phone_verified.is_(True)
            )
        if row.email_hash:
            conditions.append(Homeowner.email_hash == row.email_hash)  # verified by Google
        if not conditions:
            return
        homeowner_id = await self.s.scalar(select(Homeowner.id).where(or_(*conditions)))
        if homeowner_id is not None:
            row.homeowner_id = homeowner_id
            row.joined_at = self.c.clock.now()

    # --- Joining --------------------------------------------------------------------------
    async def link_homeowner(self, homeowner: Homeowner) -> int:
        """After sign-in: link every shop's customer record with this verified phone/email.
        A number typed in at sign-up isn't proof (no code is texted), so it doesn't count."""
        conditions = []
        if homeowner.phone_hash and homeowner.phone_verified:
            conditions.append(ShopCustomer.phone_hash == homeowner.phone_hash)
        if homeowner.email_hash:
            conditions.append(ShopCustomer.email_hash == homeowner.email_hash)
        if not conditions:
            return 0
        result = await self.s.execute(
            update(ShopCustomer)
            .where(ShopCustomer.homeowner_id.is_(None), or_(*conditions))
            .values(homeowner_id=homeowner.id, joined_at=self.c.clock.now())
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def invite_info(self, code: str) -> InviteInfo:
        code = code.strip().upper()
        customer = await self.s.scalar(select(ShopCustomer).where(ShopCustomer.invite_code == code))
        shop = (
            await self.s.get(Shop, customer.shop_id)
            if customer is not None
            else await self.s.scalar(select(Shop).where(Shop.invite_code == code))
        )
        if shop is None:
            raise NotFound("This invite link isn't valid.", code="invite_not_found")
        return InviteInfo(shop.id, shop.name, shop.phone, customer)

    async def accept_invite(self, homeowner: Homeowner, code: str) -> InviteInfo:
        """The homeowner signed up from a shop's link: make them that shop's customer."""
        info = await self.invite_info(code)
        await self.link_homeowner(homeowner)
        record = info.customer
        if (
            record is not None
            and record.homeowner_id is None
            and record.phone_hash
            and record.phone_hash == homeowner.phone_hash
        ):
            # Their personal link (which the shop sent to this number) AND the same number:
            # together that's good evidence it's them, so connect the shop's record.
            record.homeowner_id = homeowner.id
            record.joined_at = self.c.clock.now()
        already = await self.s.scalar(
            select(ShopCustomer.id).where(
                ShopCustomer.shop_id == info.shop_id, ShopCustomer.homeowner_id == homeowner.id
            )
        )
        if already is None:
            # A forwarded link, or a new number: don't attach someone else's record (it
            # holds that person's address). Record this person as a new customer instead.
            self.s.add(
                ShopCustomer(
                    shop_id=info.shop_id,
                    provider=APP,
                    external_id=str(homeowner.id),
                    name=homeowner.name,
                    phone=homeowner.phone,
                    email=homeowner.email,
                    homeowner_id=homeowner.id,
                    invite_code=new_code(),
                    joined_at=self.c.clock.now(),
                )
            )
        await self.s.flush()
        return info

    async def on_file(self, homeowner: Homeowner) -> ShopCustomer | None:
        """What a shop has on file for this (verified) homeowner: name and address."""
        return await self.s.scalar(
            select(ShopCustomer)
            .where(ShopCustomer.homeowner_id == homeowner.id, ShopCustomer.provider != APP)
            .order_by(ShopCustomer.last_job_at.desc().nulls_last())
            .limit(1)
        )

    async def company_names(self, homeowner: Homeowner) -> list[str]:
        rows = await self.s.scalars(
            select(Shop.name)
            .join(ShopCustomer, ShopCustomer.shop_id == Shop.id)
            .where(ShopCustomer.homeowner_id == homeowner.id)
        )
        return list(dict.fromkeys(rows))

    async def home_shops(self, homeowner_id: uuid.UUID) -> list[uuid.UUID]:
        """Shops this homeowner is a customer of, most recent first."""
        rows = await self.s.scalars(
            select(ShopCustomer.shop_id)
            .where(ShopCustomer.homeowner_id == homeowner_id)
            .order_by(ShopCustomer.last_job_at.desc().nulls_last(), ShopCustomer.joined_at.desc())
        )
        return list(dict.fromkeys(rows))

    # --- The shop's side ----------------------------------------------------------------------
    async def ensure_shop_code(self, shop: Shop) -> str:
        if not shop.invite_code:
            shop.invite_code = new_code()
            await self.s.flush()
        return shop.invite_code

    def invite_url(self, code: str) -> str:
        return f"{self.c.settings.public_app_url.rstrip('/')}/join/{code}"

    async def list_for_shop(
        self, shop: Shop, *, query: str | None = None, status: str | None = None
    ) -> list[ShopCustomer]:
        rows = list(
            await self.s.scalars(
                select(ShopCustomer)
                .where(ShopCustomer.shop_id == shop.id)
                .order_by(ShopCustomer.last_job_at.desc().nulls_last(), ShopCustomer.created_at)
                .limit(5000)
            )
        )
        if status == "joined":
            rows = [r for r in rows if r.homeowner_id]
        elif status == "invited":
            rows = [r for r in rows if r.invited_at and not r.homeowner_id]
        elif status == "not_invited":
            rows = [r for r in rows if not r.invited_at and not r.homeowner_id]
        if query:
            # Names are encrypted, so search after decrypting (a shop has thousands at most).
            q = query.strip().lower()
            digits = "".join(ch for ch in q if ch.isdigit())
            rows = [
                r
                for r in rows
                if q in (r.name or "").lower()
                or q in (r.email or "").lower()
                or (digits and digits in (r.phone or ""))
            ]
        return rows

    async def get_for_shop(self, shop: Shop, customer_id: uuid.UUID) -> ShopCustomer:
        row = await self.s.get(ShopCustomer, customer_id)
        if row is None or row.shop_id != shop.id:
            raise NotFound("Customer not found")
        return row

    def invite_message(self, shop: Shop, url: str, name: str | None = None) -> str:
        hello = f"Hi {name.split()[0]}! " if name and name.split() else "Hi! "
        return (
            f"{hello}{shop.name} now books visits through the HVAC Connect app: request "
            "service in a minute, see when your technician is on the way, and message them. "
            f"Get it here: {url}"
        )

    def mark_invited(self, row: ShopCustomer, now: datetime | None = None) -> None:
        row.invited_at = now or self.c.clock.now()
