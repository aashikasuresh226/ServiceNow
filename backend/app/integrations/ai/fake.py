"""Deterministic analyzer for demos and tests: infers a likely issue from symptoms."""

from __future__ import annotations

from app.domain.enums import Confidence, EquipmentType, IssueCategory, Symptom
from app.integrations.ai.base import AnalysisResult, Diagnosis, PhotoInput, UnitInfo

_RULES: list[tuple[Symptom, EquipmentType, IssueCategory, list[IssueCategory], str]] = [
    (
        Symptom.NO_COOLING,
        EquipmentType.CENTRAL_AC,
        IssueCategory.CAPACITOR,
        [IssueCategory.CONTACTOR, IssueCategory.REFRIGERANT_LEAK],
        "The outdoor unit likely isn't starting its fan or compressor; a failed capacitor "
        "is the most common cause.",
    ),
    (
        Symptom.NO_HEAT,
        EquipmentType.FURNACE,
        IssueCategory.IGNITER_OR_FLAME_SENSOR,
        [IssueCategory.THERMOSTAT, IssueCategory.BLOWER_MOTOR],
        "The furnace probably isn't lighting; a dirty flame sensor or worn igniter is typical.",
    ),
    (
        Symptom.LEAKING,
        EquipmentType.CENTRAL_AC,
        IssueCategory.CLOGGED_DRAIN,
        [IssueCategory.DIRTY_FILTER_OR_COIL],
        "Water around the indoor unit usually means a clogged condensate drain line.",
    ),
    (
        Symptom.NOISY,
        EquipmentType.CENTRAL_AC,
        IssueCategory.FAN_MOTOR,
        [IssueCategory.CAPACITOR, IssueCategory.BLOWER_MOTOR],
        "Grinding or squealing points to a fan or blower motor bearing wearing out.",
    ),
    (
        Symptom.WONT_START,
        EquipmentType.CENTRAL_AC,
        IssueCategory.THERMOSTAT,
        [IssueCategory.CONTACTOR, IssueCategory.CAPACITOR],
        "When nothing turns on, the thermostat or a control part is the usual suspect.",
    ),
    (
        Symptom.ODD_SMELL,
        EquipmentType.FURNACE,
        IssueCategory.DIRTY_FILTER_OR_COIL,
        [IssueCategory.BLOWER_MOTOR],
        "Musty or dusty smells often come from a dirty filter or coil.",
    ),
]


class FakeUnitAnalyzer:
    async def analyze(
        self, *, symptoms: list[str], description: str | None, photos: list[PhotoInput]
    ) -> AnalysisResult:
        rule = next((r for r in _RULES if r[0].value in symptoms), None)
        if rule:
            _, unit_type, issue, alternatives, summary = rule
        else:
            unit_type, issue, alternatives = (
                EquipmentType.CENTRAL_AC,
                IssueCategory.GENERAL_DIAGNOSTIC,
                [],
            )
            summary = "We need a technician to take a look to pinpoint the problem."

        safety = None
        if Symptom.ODD_SMELL.value in symptoms and description and "gas" in description.lower():
            safety = "If you smell gas, leave the house and call your gas utility's emergency line."

        return AnalysisResult(
            unit=UnitInfo(
                brand="Carrier" if photos else None,
                model_number="24ACC636A003" if photos else None,
                serial_number="1214E12345" if photos else None,
                equipment_type=unit_type,
                approx_age_years=12 if photos else None,
                tonnage=3.0 if photos else None,
            ),
            diagnosis=Diagnosis(
                primary_issue=issue,
                summary=summary,
                alternatives=alternatives,
                confidence=Confidence.MEDIUM if photos else Confidence.LOW,
                safety_warning=safety,
            ),
        )
