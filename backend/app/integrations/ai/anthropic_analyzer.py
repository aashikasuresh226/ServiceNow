"""Claude reads the unit photos (usually the data plate / rating label) and the
homeowner's description, and returns everything printed on the plate plus a
likely problem.

- Photos are auto-rotated and downscaled before sending (Claude works best at
  ≤1568 px on the long edge, and smaller images cost fewer tokens).
- Structured outputs (`output_config.format` = JSON schema) make Claude answer
  in exactly our shape. (Sonnet 5.5 doesn't allow forced tool calls.)
- Every field is validated again here, so a bad value degrades safely.
- Prices come from the price book (domain/pricing.py), never from the model.
- Scaling: a per-process concurrency cap, SDK retries with backoff for rate
  limits/overload, and prompt caching of the (identical) instructions.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
from typing import Any, cast

import anthropic
from PIL import Image, ImageOps

from app.core.errors import ExternalServiceError
from app.domain.enums import Confidence, EquipmentType, IssueCategory
from app.integrations.ai.base import AnalysisResult, Diagnosis, PhotoInput, UnitInfo

log = logging.getLogger(__name__)

MAX_IMAGE_EDGE = 1568
MAX_PHOTOS = 5
FUELS = ("electric", "natural_gas", "propane", "oil")

# Data-plate fields we ask for, with the label shown to homeowners and techs.
SPEC_FIELDS: dict[str, str] = {
    "manufacture_date": "Manufactured",
    "cooling_capacity": "Cooling capacity",
    "heating_capacity": "Heating capacity",
    "heating_input": "Heating input",
    "heating_output": "Heating output",
    "voltage": "Voltage",
    "phase": "Phase",
    "frequency": "Frequency",
    "min_circuit_ampacity": "Min. circuit ampacity (MCA)",
    "max_overcurrent_protection": "Max. fuse / breaker (MOCP)",
    "compressor_rla": "Compressor RLA",
    "compressor_lra": "Compressor LRA",
    "fan_motor_fla": "Fan motor FLA",
    "refrigerant": "Refrigerant",
    "factory_charge": "Factory charge",
    "design_pressure": "Design pressure",
    "seer": "SEER",
    "seer2": "SEER2",
    "eer": "EER",
    "hspf": "HSPF",
    "afue": "AFUE",
    "gas_type": "Gas type",
    "other": "Other",
}

SYSTEM_PROMPT = """You are an experienced residential HVAC technician triaging a service \
request before a technician visits a home in the United States.

You get photos from the homeowner (usually the unit's data plate / rating label, sometimes the \
whole indoor or outdoor unit) and their description of the problem.

Reading the data plate:
- Copy brand, model number and serial number exactly as printed. Use null if a value isn't \
legible; never guess characters.
- Copy every other value printed on the plate exactly as printed, including units (for \
example "36,000 BTU/h", "208/230 V", "1", "60 Hz", "18.6", "R-410A", "7 lb 4 oz", "SEER2 \
14.3"). Use null for anything not printed or not legible.
- Manufacture year: use a date printed on the plate if there is one. Otherwise decode it from \
the serial number only when you are confident of that brand's serial format (Carrier, Bryant, \
Payne, Trane, American Standard, Lennox, Goodman, Amana, Daikin, Rheem, Ruud, York, Coleman \
and others have documented formats). If unsure, null.
- Tonnage: from the printed capacity (12,000 BTU/h = 1 ton) or the capacity digits in the \
model number (e.g. "36" = 3 tons) when you're confident.
- Equipment type: central AC condenser, heat pump, furnace, boiler, mini-split or packaged \
unit. Model-number prefixes and label wording usually reveal it.

The problem:
- List anything visibly wrong in the photos (ice on lines, oil stains, rust, a bulging \
capacitor, burnt wiring, debris, standing water, bent fins). Empty list if nothing is visible.
- Pick the single most likely issue category, up to two alternatives, and a confidence \
level. Use "general_diagnostic" when the evidence is thin.
- Write a one-sentence, plain-language summary for the homeowner. No jargon, no prices.
- If anything suggests a safety risk (gas smell, burning smell, sparking, scorched wiring, \
carbon monoxide symptoms), set safety_warning to a short instruction (e.g. "Turn the system \
off at the thermostat and the breaker").
- If the photos don't show HVAC equipment or the plate can't be read, say how to retake them \
in photo_feedback (e.g. "Move closer to the silver label on the side of the outdoor unit"). \
Otherwise null."""


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


_TEXT = _nullable({"type": "string"})

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "photos_show_hvac_equipment": {"type": "boolean"},
        "brand": _TEXT,
        "model_number": _TEXT,
        "serial_number": _TEXT,
        "equipment_type": {"type": "string", "enum": [e.value for e in EquipmentType]},
        "manufacture_year": _nullable({"type": "integer"}),
        "tonnage": _nullable({"type": "number"}),
        "fuel": _nullable({"type": "string", "enum": list(FUELS)}),
        "specs": {
            "type": "object",
            "properties": {key: _TEXT for key in SPEC_FIELDS},
            "required": list(SPEC_FIELDS),
            "additionalProperties": False,
        },
        "visible_issues": {"type": "array", "items": {"type": "string"}},
        "primary_issue": {"type": "string", "enum": [c.value for c in IssueCategory]},
        "alternatives": {
            "type": "array",
            "items": {"type": "string", "enum": [c.value for c in IssueCategory]},
        },
        "confidence": {"type": "string", "enum": [c.value for c in Confidence]},
        "summary": {"type": "string"},
        "safety_warning": _TEXT,
        "photo_feedback": _TEXT,
    },
    "required": [
        "photos_show_hvac_equipment",
        "brand",
        "model_number",
        "serial_number",
        "equipment_type",
        "manufacture_year",
        "tonnage",
        "fuel",
        "specs",
        "visible_issues",
        "primary_issue",
        "alternatives",
        "confidence",
        "summary",
        "safety_warning",
        "photo_feedback",
    ],
    "additionalProperties": False,
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
            img.save(out, format="JPEG", quality=88, optimize=True)
            return out.getvalue(), "image/jpeg"
    except Exception:  # unreadable image: skip it rather than fail the analysis
        log.warning("Skipping a photo that couldn't be decoded")
        return None


class AnthropicUnitAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        effort: str = "medium",
        max_concurrency: int = 8,
        timeout_seconds: float = 90.0,
    ) -> None:
        # The SDK retries 429 (rate limit), 529 (overloaded) and 5xx with backoff.
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=3
        )
        self._model = model
        self._effort = effort
        self._slots = asyncio.Semaphore(max_concurrency)

    async def analyze(
        self,
        *,
        symptoms: list[str],
        description: str | None,
        photos: list[PhotoInput],
        current_year: int,
    ) -> AnalysisResult:
        content: list[dict[str, Any]] = []
        images = 0
        for photo in photos[:MAX_PHOTOS]:
            prepared = prepare_image(photo)
            if prepared is None:
                continue
            data, media_type = prepared
            images += 1
            content.append({"type": "text", "text": f"Photo {images}:"})
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
                    f"Photos attached: {images}\n"
                    f"Symptoms selected: {', '.join(symptoms) or 'none'}\n"
                    f"Homeowner description: {description or '(none)'}"
                ),
            }
        )

        async with self._slots:
            try:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=8000,
                    # Same instructions every time: cached, so repeat calls are cheaper/faster.
                    system=cast(
                        Any,
                        [
                            {
                                "type": "text",
                                "text": SYSTEM_PROMPT,
                                "cache_control": {"type": "ephemeral"},
                            }
                        ],
                    ),
                    messages=cast(Any, [{"role": "user", "content": content}]),
                    output_config=cast(
                        Any,
                        {
                            "effort": self._effort,
                            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
                        },
                    ),
                )
            except anthropic.AuthenticationError as exc:
                log.error("Anthropic rejected the API key: %s", exc)
                raise ExternalServiceError("Photo analysis isn't available right now") from exc
            except anthropic.APIError as exc:
                log.warning("AI analysis failed: %s", exc)
                raise ExternalServiceError("Photo analysis is unavailable right now") from exc

        text = next(
            (b.text for b in response.content if isinstance(b, anthropic.types.TextBlock)), ""
        )
        try:
            data = json.loads(text)
        except ValueError as exc:
            log.warning("AI returned non-JSON (stop_reason=%s)", response.stop_reason)
            raise ExternalServiceError("Photo analysis returned an unexpected response") from exc
        usage = response.usage
        log.info(
            "AI analysis: %s photos, %s input + %s output tokens (cache read %s)",
            images,
            usage.input_tokens,
            usage.output_tokens,
            getattr(usage, "cache_read_input_tokens", 0),
        )
        return parse_analysis(data, current_year=current_year)


def parse_analysis(data: dict[str, Any], *, current_year: int) -> AnalysisResult:
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
    age = current_year - year if year is not None else None

    specs_value = data.get("specs")
    raw_specs: dict[str, Any] = specs_value if isinstance(specs_value, dict) else {}
    specs = {
        label: value
        for key, label in SPEC_FIELDS.items()
        if (value := _clean(raw_specs.get(key), 80))
    }
    refrigerant = _clean(raw_specs.get("refrigerant"), 20)
    seer = _first_number(raw_specs.get("seer2")) or _first_number(raw_specs.get("seer"))
    fuel = data.get("fuel")
    equipment = enum_or(EquipmentType, data.get("equipment_type"), EquipmentType.UNKNOWN)
    feedback = _clean(data.get("photo_feedback"), 200)
    if data.get("photos_show_hvac_equipment") is False and not feedback:
        feedback = "We couldn't see an HVAC unit in that photo. Try the label on the unit."

    unit = UnitInfo(
        brand=_clean(data.get("brand")),
        model_number=_clean(data.get("model_number")),
        serial_number=_clean(data.get("serial_number")),
        equipment_type=equipment,
        approx_age_years=age,
        tonnage=number(data.get("tonnage"), 0.5, 25),
        manufacture_year=year,
        refrigerant=refrigerant,
        fuel=fuel if fuel in FUELS else None,
        seer_rating=seer if seer and 5 <= seer <= 40 else None,
        voltage=specs.get(SPEC_FIELDS["voltage"]),
        photo_feedback=feedback,
        specs=specs,
        insights=unit_insights(age=age, refrigerant=refrigerant, equipment=equipment),
    )
    return AnalysisResult(
        unit=unit,
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


# Kept for older callers/tests.
parse_tool_input = parse_analysis


def unit_insights(
    *, age: int | None, refrigerant: str | None, equipment: EquipmentType
) -> list[str]:
    """Plain-language notes computed from the label (deterministic, not from the model)."""
    notes: list[str] = []
    if age is not None:
        life = 20 if equipment in (EquipmentType.FURNACE, EquipmentType.BOILER) else 15
        if age >= life:
            notes.append(
                f"About {age} years old: past the typical {life}-year lifespan, so ask about "
                "repair vs. replacement."
            )
        elif age >= life - 5:
            notes.append(
                f"About {age} years old: getting close to the typical {life}-year lifespan."
            )
    if refrigerant and refrigerant.upper().replace(" ", "") in ("R-22", "R22"):
        notes.append(
            "Uses R-22 refrigerant, which is no longer produced in the US, so refrigerant "
            "repairs can be expensive."
        )
    return notes


def _first_number(value: Any) -> float | None:
    """First rating-like number in text such as 'SEER2 14.3' → 14.3 (skips the '2' in SEER2)."""
    if not isinstance(value, str):
        return None
    for match in re.findall(r"\d+(?:\.\d+)?", value):
        number = float(match)
        if 5 <= number <= 40:
            return number
    return None


def _clean(value: Any, limit: int = 120) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None
