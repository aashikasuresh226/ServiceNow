"""Claude reads the unit photos (usually the data plate / rating label) and the
homeowner's description.

- Photos are auto-rotated and downscaled before sending (Claude works best at
  ≤1568 px on the long edge, and the API limits image size).
- A forced tool call makes Claude answer in our JSON schema; the answer is then
  validated against our enums, so a bad value degrades safely.
- Claude classifies the problem into a fixed category. Prices come from the
  price book (domain/pricing.py), never from the model.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Any, cast

import anthropic
from PIL import Image, ImageOps

from app.core.errors import ExternalServiceError
from app.domain.enums import Confidence, EquipmentType, IssueCategory
from app.integrations.ai.base import AnalysisResult, Diagnosis, PhotoInput, UnitInfo

log = logging.getLogger(__name__)

MAX_IMAGE_EDGE = 1568
FUELS = {"electric", "natural_gas", "propane", "oil"}

SYSTEM_PROMPT = """You are an experienced residential HVAC technician triaging a service \
request before a technician visits a home in the United States.

You get photos from the homeowner (often the unit's data plate / rating label, sometimes the \
whole indoor or outdoor unit) and their description of the problem.

1. Read brand, model number and serial number exactly as printed on the label. Use null if \
a value isn't legible; never guess characters.
2. Read any other label facts that are printed: refrigerant type (e.g. R-410A, R-22, R-454B, \
R-32), cooling capacity / tonnage, SEER or SEER2 rating, voltage, and fuel type.
3. Manufacture year: use a date printed on the label if there is one. Otherwise decode it \
from the serial number only when you are confident of that brand's serial format (for \
example Carrier/Bryant/Payne, Trane/American Standard, Lennox, Goodman/Amana/Daikin, \
Rheem/Ruud, York, and others have documented formats). If unsure, use null.
4. Identify the equipment type (central AC condenser, heat pump, furnace, boiler, mini-split, \
packaged unit). Model-number prefixes and label wording often reveal this.
5. Describe anything visibly wrong in the photos (ice on lines, oil stains, rust, bulging \
capacitor, burnt wiring, debris, standing water, bent fins). Empty list if nothing is visible.
6. Pick the single most likely issue category, plus up to two alternatives, and a confidence \
level. Use "general_diagnostic" when the evidence is thin.
7. Write a one-sentence, plain-language summary for the homeowner. No jargon, no prices.
8. If anything suggests a safety risk (gas smell, burning smell, sparking, scorched wiring, \
carbon monoxide symptoms), set safety_warning to a short instruction (e.g. turn the system \
off at the thermostat and breaker).
9. If the photos don't show HVAC equipment or the label can't be read, say how to retake \
them in photo_feedback (e.g. "Move closer to the silver label on the side of the outdoor \
unit"). Otherwise null.

Always respond by calling the record_analysis tool."""

_NULLABLE_STRING = {"type": ["string", "null"]}

ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_analysis",
    "description": "Record the structured analysis of the HVAC unit and problem.",
    "input_schema": {
        "type": "object",
        "properties": {
            "photos_show_hvac_equipment": {"type": "boolean"},
            "brand": _NULLABLE_STRING,
            "model_number": _NULLABLE_STRING,
            "serial_number": _NULLABLE_STRING,
            "equipment_type": {"type": "string", "enum": [e.value for e in EquipmentType]},
            "manufacture_year": {"type": ["integer", "null"], "minimum": 1960, "maximum": 2100},
            "approx_age_years": {"type": ["integer", "null"], "minimum": 0, "maximum": 60},
            "tonnage": {"type": ["number", "null"], "minimum": 0.5, "maximum": 25},
            "refrigerant": _NULLABLE_STRING,
            "seer_rating": {"type": ["number", "null"], "minimum": 5, "maximum": 40},
            "voltage": _NULLABLE_STRING,
            "fuel": {"type": ["string", "null"], "enum": [*sorted(FUELS), None]},
            "visible_issues": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "primary_issue": {"type": "string", "enum": [c.value for c in IssueCategory]},
            "alternatives": {
                "type": "array",
                "items": {"type": "string", "enum": [c.value for c in IssueCategory]},
                "maxItems": 2,
            },
            "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
            "summary": {"type": "string", "maxLength": 300},
            "safety_warning": _NULLABLE_STRING,
            "photo_feedback": _NULLABLE_STRING,
        },
        "required": [
            "photos_show_hvac_equipment",
            "equipment_type",
            "primary_issue",
            "confidence",
            "summary",
        ],
    },
}


def prepare_image(photo: PhotoInput) -> tuple[bytes, str] | None:
    """Rotate per EXIF, downscale to MAX_IMAGE_EDGE, re-encode as JPEG."""
    try:
        with Image.open(io.BytesIO(photo.data)) as opened:
            img: Image.Image = ImageOps.exif_transpose(opened)
            img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:  # unreadable image: skip it rather than fail the analysis
        log.warning("Skipping a photo that couldn't be decoded")
        return None


class AnthropicUnitAnalyzer:
    def __init__(self, api_key: str, model: str, *, timeout_seconds: float = 60.0) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model

    async def analyze(
        self,
        *,
        symptoms: list[str],
        description: str | None,
        photos: list[PhotoInput],
        current_year: int,
    ) -> AnalysisResult:
        content: list[dict[str, Any]] = []
        for index, photo in enumerate(photos, start=1):
            prepared = prepare_image(photo)
            if prepared is None:
                continue
            data, media_type = prepared
            content.append({"type": "text", "text": f"Photo {index}:"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(data).decode(),
                    },
                }
            )
        content.append(
            {
                "type": "text",
                "text": (
                    f"Current year: {current_year}\n"
                    f"Photos attached: {sum(1 for c in content if c['type'] == 'image')}\n"
                    f"Symptoms selected: {', '.join(symptoms) or 'none'}\n"
                    f"Homeowner description: {description or '(none)'}"
                ),
            }
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1500,
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
        return parse_tool_input(tool_input, current_year=current_year)


def parse_tool_input(data: dict[str, Any], *, current_year: int) -> AnalysisResult:
    """Validate model output against our enums and ranges, degrading safely on bad values."""

    def enum_or(enum_cls: type, value: Any, default: Any) -> Any:
        try:
            return enum_cls(value)
        except ValueError:
            return default

    def number(value: Any, low: float, high: float) -> float | None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value) if low <= value <= high else None

    year = data.get("manufacture_year")
    year = year if isinstance(year, int) and 1960 <= year <= current_year else None
    age = data.get("approx_age_years")
    if year is not None:
        age = current_year - year
    elif not (isinstance(age, int) and 0 <= age <= 60):
        age = None
    fuel = data.get("fuel")
    feedback = _clean(data.get("photo_feedback"), 200)
    if data.get("photos_show_hvac_equipment") is False and not feedback:
        feedback = "We couldn't see an HVAC unit in that photo. Try the label on the unit."
    return AnalysisResult(
        unit=UnitInfo(
            brand=_clean(data.get("brand")),
            model_number=_clean(data.get("model_number")),
            serial_number=_clean(data.get("serial_number")),
            equipment_type=enum_or(
                EquipmentType, data.get("equipment_type"), EquipmentType.UNKNOWN
            ),
            approx_age_years=age,
            tonnage=number(data.get("tonnage"), 0.5, 25),
            manufacture_year=year,
            refrigerant=_clean(data.get("refrigerant"), 20),
            fuel=fuel if fuel in FUELS else None,
            seer_rating=number(data.get("seer_rating"), 5, 40),
            voltage=_clean(data.get("voltage"), 30),
            photo_feedback=feedback,
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
                for a in (data.get("alternatives") or [])[:2]
                if a in IssueCategory._value2member_map_
            ],
            confidence=enum_or(Confidence, data.get("confidence"), Confidence.LOW),
            safety_warning=_clean(data.get("safety_warning"), 300),
            visible_issues=[
                text for v in (data.get("visible_issues") or [])[:5] if (text := _clean(v, 160))
            ],
        ),
    )


def _clean(value: Any, limit: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None
