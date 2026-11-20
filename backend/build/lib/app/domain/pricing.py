"""Price book and estimate helpers. All amounts are integer cents.

The AI estimates the repair range from the photos and description, anchored on the final
prices of past jobs on the platform and on this price book (see PriceContext). When the
AI is off or fails, the price book alone gives the estimate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.enums import IssueCategory

DIAGNOSTIC_FEE_CENTS = 89_00


@dataclass(frozen=True, slots=True)
class PriceEntry:
    repair_low_cents: int
    label: str
    requires_refrigerant_work: bool = False


PRICE_BOOK: dict[IssueCategory, PriceEntry] = {
    IssueCategory.CAPACITOR: PriceEntry(150_00, "Failed capacitor"),
    IssueCategory.CONTACTOR: PriceEntry(150_00, "Worn contactor"),
    IssueCategory.REFRIGERANT_LEAK: PriceEntry(
        400_00, "Refrigerant leak / low charge", requires_refrigerant_work=True
    ),
    IssueCategory.CLOGGED_DRAIN: PriceEntry(100_00, "Clogged condensate drain"),
    IssueCategory.DIRTY_FILTER_OR_COIL: PriceEntry(80_00, "Dirty filter or coil"),
    IssueCategory.FAN_MOTOR: PriceEntry(350_00, "Condenser fan motor"),
    IssueCategory.THERMOSTAT: PriceEntry(120_00, "Thermostat fault"),
    IssueCategory.IGNITER_OR_FLAME_SENSOR: PriceEntry(150_00, "Igniter or flame sensor"),
    IssueCategory.BLOWER_MOTOR: PriceEntry(450_00, "Blower motor"),
    IssueCategory.COMPRESSOR: PriceEntry(
        1_500_00, "Compressor failure", requires_refrigerant_work=True
    ),
    IssueCategory.GENERAL_DIAGNOSTIC: PriceEntry(0, "Needs on-site diagnosis"),
}


@dataclass(frozen=True, slots=True)
class Estimate:
    diagnostic_fee_cents: int
    repair_low_cents: int

    @property
    def total_low_cents(self) -> int:
        return self.diagnostic_fee_cents + self.repair_low_cents


def market_from_address(address: str | None) -> str:
    """'191 Peachtree St NE, Atlanta, GA 30303' -> 'Atlanta, GA' (no street, no ZIP)."""
    if not address:
        return ""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if parts and parts[-1].upper() in ("USA", "US", "UNITED STATES"):
        parts = parts[:-1]
    if len(parts) >= 3:
        match = re.match(r"^([A-Za-z]{2})\b", parts[-1])
        if match:
            return f"{parts[-2]}, {match.group(1).upper()}"
    return ""


def estimate_for(category: IssueCategory) -> Estimate:
    entry = PRICE_BOOK[category]
    return Estimate(
        diagnostic_fee_cents=DIAGNOSTIC_FEE_CENTS, repair_low_cents=entry.repair_low_cents
    )


def platform_fee(amount_cents: int, fee_bps: int) -> int:
    """Platform fee in cents, rounded half-up, never more than the amount."""
    if amount_cents < 0 or fee_bps < 0:
        raise ValueError("amount and fee must be non-negative")
    return min(amount_cents, (amount_cents * fee_bps + 5_000) // 10_000)
