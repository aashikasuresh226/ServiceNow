"""Operational commands.

python -m app.cli migrate      apply database migrations
python -m app.cli seed         add demo shops, technicians and a demo homeowner
python -m app.cli reset-demo   wipe the database, migrate and seed (demo only)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pyotp
from sqlalchemy import select

from app.container import build_container
from app.core.config import Environment, get_settings
from app.core.security import hash_password
from app.domain.enums import Certification, EquipmentType, SoftSkill
from app.integrations.geocoding import DEMO_CENTER
from app.models import Homeowner, Shop, ShopUser, Technician

log = logging.getLogger("app.cli")
ALL_DAY = {d: [["00:00", "24:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

DEMO_SHOP_EMAIL = "demo@coolbreeze.example.com"
DEMO_SHOP_PASSWORD = "DemoPassword123!"
DEMO_HOMEOWNER_PHONE = "+15555550100"

E, C, K = EquipmentType, Certification, SoftSkill


@dataclass(frozen=True)
class DemoTech:
    name: str
    equipment: list[EquipmentType]
    certifications: list[Certification]
    skills: list[SoftSkill]
    rating: float


@dataclass(frozen=True)
class DemoShop:
    name: str
    address: str
    offset: tuple[float, float]  # degrees from the demo city center
    phone: str
    email: str
    techs: list[DemoTech]
    # Only the shop you present is live, so every demo job lands in its portal.
    is_live: bool = True


DEMO_SHOPS = [
    DemoShop(
        name="Cool Breeze HVAC",
        address="675 Ponce De Leon Ave NE, Atlanta, GA 30308",
        offset=(0.012, 0.010),
        phone="+14045550123",
        email=DEMO_SHOP_EMAIL,
        techs=[
            DemoTech(
                "Marcus Johnson",
                [E.CENTRAL_AC, E.HEAT_PUMP, E.MINI_SPLIT],
                [C.EPA_608, C.NATE, C.STATE_LICENSE],
                [K.EXPLAINS_CLEARLY, K.PUNCTUAL],
                4.9,
            ),
            DemoTech(
                "Elena Ruiz",
                [E.CENTRAL_AC, E.FURNACE, E.HEAT_PUMP],
                [C.EPA_608, C.STATE_LICENSE],
                [K.PATIENT, K.SPANISH_SPEAKING, K.SHOWS_WORK],
                4.8,
            ),
            DemoTech(
                "Dave Kim", [E.FURNACE, E.BOILER], [C.STATE_LICENSE], [K.TIDY, K.PUNCTUAL], 4.6
            ),
        ],
    ),
    DemoShop(
        name="Peach State Air",
        address="1000 Northside Dr NW, Atlanta, GA 30318",
        offset=(0.030, -0.035),
        phone="+14045550188",
        email="demo@peachstate.example.com",
        techs=[
            DemoTech(
                "Tasha Green",
                [E.CENTRAL_AC, E.PACKAGED_UNIT, E.FURNACE],
                [C.EPA_608, C.NATE],
                [K.EXPLAINS_CLEARLY, K.TIDY],
                4.9,
            ),
            DemoTech("Ray Patel", [E.MINI_SPLIT, E.HEAT_PUMP], [C.EPA_608], [K.SHOWS_WORK], 4.5),
        ],
        is_live=False,
    ),
]


def _run_alembic(*args: str) -> None:
    root = Path(__file__).resolve().parent.parent
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, check=True)


async def seed() -> None:
    settings = get_settings()
    container = build_container(settings)
    try:
        async with container.session_factory() as session:
            if await session.scalar(select(ShopUser).where(ShopUser.email == DEMO_SHOP_EMAIL)):
                print("Demo data already present; nothing to do.")
                return
            for i, spec in enumerate(DEMO_SHOPS, start=1):
                shop = Shop(
                    name=spec.name,
                    phone=spec.phone,
                    address=spec.address,
                    lat=DEMO_CENTER.lat + spec.offset[0],
                    lng=DEMO_CENTER.lng + spec.offset[1],
                    is_live=spec.is_live,
                    payouts_enabled=True,
                    payout_account_id=f"acct_fake_seed{i:04d}",
                )
                session.add(shop)
                await session.flush()
                session.add(
                    ShopUser(
                        shop_id=shop.id,
                        email=spec.email,
                        name="Demo Dispatcher",
                        password_hash=hash_password(DEMO_SHOP_PASSWORD),
                        totp_secret_encrypted=container.encryptor.encrypt(pyotp.random_base32()),
                        mfa_enabled=True,
                    )
                )
                for demo_tech in spec.techs:
                    count = 20
                    session.add(
                        Technician(
                            shop_id=shop.id,
                            name=demo_tech.name,
                            equipment_types=[e.value for e in demo_tech.equipment],
                            certifications=[c.value for c in demo_tech.certifications],
                            soft_skills=[s.value for s in demo_tech.skills],
                            service_radius_km=40.0,
                            working_hours=ALL_DAY,
                            rating_sum=round(demo_tech.rating * count),
                            rating_count=count,
                        )
                    )
            session.add(
                Homeowner(
                    phone=DEMO_HOMEOWNER_PHONE,
                    name="Jordan Lee",
                    address="191 Peachtree St NE, Atlanta, GA 30303",
                    lat=DEMO_CENTER.lat + 0.008,
                    lng=DEMO_CENTER.lng + 0.002,
                )
            )
            await session.commit()
        print("Seeded demo data:")
        print(f"  Shop portal login: {DEMO_SHOP_EMAIL} / {DEMO_SHOP_PASSWORD}")
        print("  Homeowner phone:   (555) 555-0100 (the code is shown on screen in demo mode)")
    finally:
        await container.aclose()


def reset_demo() -> None:
    settings = get_settings()
    if settings.environment == Environment.PROD:
        raise SystemExit("Refusing to reset a production database.")
    _run_alembic("downgrade", "base")
    _run_alembic("upgrade", "head")
    asyncio.run(seed())


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=["migrate", "seed", "reset-demo"])
    args = parser.parse_args()
    Path("var").mkdir(exist_ok=True)
    if args.command == "migrate":
        _run_alembic("upgrade", "head")
    elif args.command == "seed":
        asyncio.run(seed())
    else:
        reset_demo()


if __name__ == "__main__":
    main()
