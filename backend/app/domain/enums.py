"""Shared vocabularies. Clients fetch these from GET /v1/meta/options so the
apps never hard-code lists that the backend matches against."""

from __future__ import annotations

from enum import StrEnum


class Symptom(StrEnum):
    NO_COOLING = "no_cooling"
    NO_HEAT = "no_heat"
    NOISY = "noisy"
    LEAKING = "leaking"
    WONT_START = "wont_start"
    ODD_SMELL = "odd_smell"


class Urgency(StrEnum):
    ASAP = "asap"
    THIS_WEEK = "this_week"
    FLEXIBLE = "flexible"


class EquipmentType(StrEnum):
    CENTRAL_AC = "central_ac"
    HEAT_PUMP = "heat_pump"
    FURNACE = "furnace"
    BOILER = "boiler"
    MINI_SPLIT = "mini_split"
    PACKAGED_UNIT = "packaged_unit"
    UNKNOWN = "unknown"


class Certification(StrEnum):
    EPA_608 = "epa_608"
    NATE = "nate"
    STATE_LICENSE = "state_license"


class SoftSkill(StrEnum):
    EXPLAINS_CLEARLY = "explains_clearly"
    PUNCTUAL = "punctual"
    PATIENT = "patient"
    TIDY = "tidy"
    SPANISH_SPEAKING = "spanish_speaking"
    SHOWS_WORK = "shows_work"


class IssueCategory(StrEnum):
    """Diagnosis buckets. Each maps to a price-book entry (see domain.pricing)."""

    CAPACITOR = "capacitor"
    CONTACTOR = "contactor"
    REFRIGERANT_LEAK = "refrigerant_leak"
    CLOGGED_DRAIN = "clogged_drain"
    DIRTY_FILTER_OR_COIL = "dirty_filter_or_coil"
    FAN_MOTOR = "fan_motor"
    THERMOSTAT = "thermostat"
    IGNITER_OR_FLAME_SENSOR = "igniter_or_flame_sensor"
    BLOWER_MOTOR = "blower_motor"
    COMPRESSOR = "compressor"
    GENERAL_DIAGNOSTIC = "general_diagnostic"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RequestStatus(StrEnum):
    DRAFT = "draft"  # created, gathering description/photos
    ANALYZED = "analyzed"  # AI analysis + estimate available
    PROPOSED = "proposed"  # a technician is reserved; homeowner must confirm
    WAITLISTED = "waitlisted"  # nobody free; waiting in the live queue
    OFFERED = "offered"  # homeowner confirmed + card held; shop must accept
    DISPATCHED = "dispatched"  # shop accepted; tech assigned
    EN_ROUTE = "en_route"
    ON_SITE = "on_site"
    QUOTED = "quoted"  # tech submitted the final price
    IN_PROGRESS = "in_progress"  # homeowner approved the quote
    COMPLETED = "completed"
    CANCELED = "canceled"


ACTIVE_JOB_STATUSES: frozenset[RequestStatus] = frozenset(
    {
        RequestStatus.PROPOSED,
        RequestStatus.OFFERED,
        RequestStatus.DISPATCHED,
        RequestStatus.EN_ROUTE,
        RequestStatus.ON_SITE,
        RequestStatus.QUOTED,
        RequestStatus.IN_PROGRESS,
    }
)
"""Statuses in which a technician is occupied by a request."""


class AvailabilityKind(StrEnum):
    SHIFT = "shift"  # the tech is working
    BUSY = "busy"  # the tech is booked (job, meeting, time off inside a shift)


class SchedulingProvider(StrEnum):
    NONE = "none"
    SERVICETITAN = "servicetitan"
    HOUSECALL_PRO = "housecall_pro"


class Actor(StrEnum):
    HOMEOWNER = "homeowner"
    SHOP = "shop"
    SYSTEM = "system"
