"""Price book: turns a diagnosis category into a low-end estimate.

The AI only classifies the problem; it never invents prices. Prices come from
this table so they are auditable and easy to tune per market. All amounts are
integer cents.
"""

from __future__ import annotations

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
