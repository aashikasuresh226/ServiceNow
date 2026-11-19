"""Interface for the AI that reads unit photos + the homeowner's description."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.domain.enums import Confidence, EquipmentType, IssueCategory


@dataclass(frozen=True, slots=True)
class PhotoInput:
    data: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class UnitInfo:
    brand: str | None
    model_number: str | None
    serial_number: str | None
    equipment_type: EquipmentType
    approx_age_years: int | None
    tonnage: float | None = None
    manufacture_year: int | None = None
    refrigerant: str | None = None  # e.g. R-410A, R-22 (phased out), R-454B
    fuel: str | None = None  # electric | natural_gas | propane | oil
    seer_rating: float | None = None
    voltage: str | None = None
    photo_feedback: str | None = None  # e.g. "Label is blurry: retake closer"
    # Everything else printed on the data plate, as printed (with units), e.g.
    # {"Cooling capacity": "36,000 BTU/h", "Min. circuit ampacity": "18.6 A"}.
    specs: dict[str, str] = field(default_factory=dict)
    # Plain-language notes derived from the label (age, phased-out refrigerant...).
    insights: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Diagnosis:
    primary_issue: IssueCategory
    summary: str  # one plain-language sentence for the homeowner
    alternatives: list[IssueCategory] = field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    safety_warning: str | None = None
    visible_issues: list[str] = field(default_factory=list)  # what the photo shows


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    unit: UnitInfo
    diagnosis: Diagnosis


class UnitAnalyzer(Protocol):
    async def analyze(
        self,
        *,
        symptoms: list[str],
        description: str | None,
        photos: list[PhotoInput],
        current_year: int,
    ) -> AnalysisResult: ...
