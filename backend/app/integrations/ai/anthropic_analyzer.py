"""Claude-powered analyzer: reads the data-plate photo and symptoms.

Uses a forced tool call so the model must return JSON matching our schema;
the response is then validated against our enums. The model classifies the
issue into a fixed category; prices come from the price book, never the model.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, cast

import anthropic

from app.core.errors import ExternalServiceError
from app.domain.enums import Confidence, EquipmentType, IssueCategory
from app.integrations.ai.base import AnalysisResult, Diagnosis, PhotoInput, UnitInfo

log = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

SYSTEM_PROMPT = """You are an experienced residential HVAC technician helping triage a \
service request before a technician visits.

From the photos (often the unit's data plate) and the homeowner's description:
1. Read brand, model number and serial number exactly as printed. Use null if unreadable; \
never guess characters.
2. Identify the equipment type.
3. Estimate the unit's age. Many manufacturers encode the manufacture date in the serial \
number; use that when you recognize the brand's format, otherwise use null.
4. Pick the single most likely issue category, plus up to two alternatives, and a \
confidence level. Prefer "general_diagnostic" when the evidence is thin.
5. Write a one-sentence, plain-language summary for the homeowner. No jargon, no prices.
6. If anything suggests a safety risk (gas smell, burning smell, sparking, carbon \
monoxide), set safety_warning to a short instruction.

Always respond by calling the record_analysis tool."""

ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_analysis",
    "description": "Record the structured analysis of the HVAC unit and problem.",
    "input_schema": {
        "type": "object",
        "properties": {
            "brand": {"type": ["string", "null"]},
            "model_number": {"type": ["string", "null"]},
            "serial_number": {"type": ["string", "null"]},
            "equipment_type": {"type": "string", "enum": [e.value for e in EquipmentType]},
            "approx_age_years": {"type": ["integer", "null"], "minimum": 0, "maximum": 60},
            "tonnage": {"type": ["number", "null"]},
            "primary_issue": {"type": "string", "enum": [c.value for c in IssueCategory]},
            "alternatives": {
                "type": "array",
                "items": {"type": "string", "enum": [c.value for c in IssueCategory]},
                "maxItems": 2,
            },
            "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
            "summary": {"type": "string", "maxLength": 300},
            "safety_warning": {"type": ["string", "null"]},
        },
        "required": ["equipment_type", "primary_issue", "confidence", "summary"],
    },
}


class AnthropicUnitAnalyzer:
    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 45.0) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    async def analyze(
        self, *, symptoms: list[str], description: str | None, photos: list[PhotoInput]
    ) -> AnalysisResult:
        content: list[dict[str, Any]] = []
        for photo in photos:
            if photo.content_type not in SUPPORTED_IMAGE_TYPES:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": photo.content_type,
                        "data": base64.b64encode(photo.data).decode(),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    f"Symptoms selected: {', '.join(symptoms) or 'none'}\n"
                    f"Homeowner description: {description or '(none)'}"
                ),
            }
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=cast(Any, [ANALYSIS_TOOL]),
                tool_choice={"type": "tool", "name": "record_analysis"},
                messages=cast(Any, [{"role": "user", "content": content}]),
            )
        except anthropic.APIError as exc:
            log.warning("AI analysis failed: %s", exc)
            raise ExternalServiceError("Photo analysis is unavailable right now") from exc

        tool_input = next(
            (b.input for b in response.content if isinstance(b, anthropic.types.ToolUseBlock)),
            None,
        )
        if not isinstance(tool_input, dict):
            raise ExternalServiceError("Photo analysis returned an unexpected response")
        return parse_tool_input(tool_input)


def parse_tool_input(data: dict[str, Any]) -> AnalysisResult:
    """Validate model output against our enums, degrading safely on bad values."""

    def enum_or(enum_cls: type, value: Any, default: Any) -> Any:
        try:
            return enum_cls(value)
        except ValueError:
            return default

    age = data.get("approx_age_years")
    return AnalysisResult(
        unit=UnitInfo(
            brand=_clean(data.get("brand")),
            model_number=_clean(data.get("model_number")),
            serial_number=_clean(data.get("serial_number")),
            equipment_type=enum_or(
                EquipmentType, data.get("equipment_type"), EquipmentType.UNKNOWN
            ),
            approx_age_years=age if isinstance(age, int) and 0 <= age <= 60 else None,
            tonnage=data.get("tonnage") if isinstance(data.get("tonnage"), int | float) else None,
        ),
        diagnosis=Diagnosis(
            primary_issue=enum_or(
                IssueCategory, data.get("primary_issue"), IssueCategory.GENERAL_DIAGNOSTIC
            ),
            summary=str(data.get("summary") or "A technician will confirm the problem on site.")[
                :300
            ],
            alternatives=[
                IssueCategory(a)
                for a in data.get("alternatives", [])[:2]
                if a in IssueCategory._value2member_map_
            ],
            confidence=enum_or(Confidence, data.get("confidence"), Confidence.LOW),
            safety_warning=_clean(data.get("safety_warning")),
        ),
    )


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:120] or None
