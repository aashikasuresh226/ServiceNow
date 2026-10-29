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


@dataclass(frozen=True, slots=True)
class Diagnosis:
    primary_issue: IssueCategory
    summary: str  # one plain-language sentence for the homeowner
    alternatives: list[IssueCategory] = field(default_factory=list)
    confidence: Confidence = Confidence.LOW
    safety_warning: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    unit: UnitInfo
    diagnosis: Diagnosis


class UnitAnalyzer(Protocol):
    async def analyze(
        self, *, symptoms: list[str], description: str | None, photos: list[PhotoInput]
    ) -> AnalysisResult: ...
