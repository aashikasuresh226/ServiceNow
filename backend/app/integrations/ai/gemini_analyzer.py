"""Google Gemini reads the unit photos: same instructions, JSON schema and validation
as the Claude analyzer (anthropic_analyzer.py), so results look identical in the app.

Gemini has a free tier (key from https://aistudio.google.com/apikey) with daily
request limits; Google may use free-tier prompts to improve its products. Only the
photos, the selected symptoms and the homeowner's description are sent.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from app.integrations.ai.anthropic_analyzer import (
    MAX_PHOTOS,
    PLAIN_JSON_RULES,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    AnalysisFailed,
    _extract_json,
    parse_analysis,
    prepare_image,
)
from app.integrations.ai.base import AnalysisResult, PhotoInput

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiUnitAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_concurrency: int = 8,
        timeout_seconds: float = 90.0,
        http: httpx.AsyncClient | None = None,
        api_base: str = API_BASE,
    ) -> None:
        self._key = api_key
        self._model = model
        self._url = f"{api_base}/models/{model}:generateContent"
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._slots = asyncio.Semaphore(max_concurrency)

    async def analyze(
        self,
        *,
        symptoms: list[str],
        description: str | None,
        photos: list[PhotoInput],
        current_year: int,
    ) -> AnalysisResult:
        parts: list[dict[str, Any]] = []
        images = 0
        for photo in photos[:MAX_PHOTOS]:
            prepared = prepare_image(photo)
            if prepared is None:
                continue
            data, media_type = prepared
            images += 1
            parts.append({"text": f"Photo {images}:"})
            parts.append(
                {"inline_data": {"mime_type": media_type, "data": base64.b64encode(data).decode()}}
            )
        parts.append(
            {
                "text": (
                    f"Current year: {current_year}\n"
                    f"Photos attached: {images}\n"
                    f"Symptoms selected: {', '.join(symptoms) or 'none'}\n"
                    f"Homeowner description: {description or '(none)'}"
                )
            }
        )

        async with self._slots:
            response = await self._post(parts, schema=True)
            if response.status_code == 400 and "schema" in response.text.lower():
                # Older models/endpoints may not accept a JSON schema: ask for plain JSON.
                log.warning("Gemini rejected the JSON schema; retrying as plain JSON")
                response = await self._post(parts, schema=False)
        if response.status_code >= 400:
            raise AnalysisFailed(_reason(response))

        body = response.json()
        candidates = body.get("candidates") or []
        if not candidates:
            block = (body.get("promptFeedback") or {}).get("blockReason")
            raise AnalysisFailed(f"Gemini returned no answer{f' ({block})' if block else ''}")
        text = "".join(
            part.get("text", "") for part in (candidates[0].get("content") or {}).get("parts", [])
        )
        parsed = _extract_json(text)
        if parsed is None:
            log.warning("Gemini returned no usable JSON: %.300s", text)
            raise AnalysisFailed("the AI's answer couldn't be read")
        usage = body.get("usageMetadata") or {}
        log.info(
            "AI analysis (Gemini %s): %s photos, %s input + %s output tokens",
            self._model,
            images,
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
        )
        return parse_analysis(parsed, current_year=current_year)

    async def _post(self, parts: list[dict[str, Any]], *, schema: bool) -> httpx.Response:
        config: dict[str, Any] = {"responseMimeType": "application/json", "temperature": 0.1}
        if schema:
            config["responseJsonSchema"] = RESPONSE_SCHEMA
        system = SYSTEM_PROMPT if schema else SYSTEM_PROMPT + PLAIN_JSON_RULES
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": config,
        }
        for attempt in range(3):
            try:
                response = await self._http.post(
                    self._url, json=payload, headers={"x-goog-api-key": self._key}
                )
            except httpx.HTTPError as exc:
                log.warning("Gemini unreachable: %s", exc)
                raise AnalysisFailed("couldn't reach Google Gemini (check the internet)") from exc
            if response.status_code not in (500, 503) or attempt == 2:
                return response
            await asyncio.sleep(1.5 * (attempt + 1))  # overloaded: brief backoff, then retry
        return response


def _reason(response: httpx.Response) -> str:
    """Short, useful reason for the app (the full error goes to the log)."""
    log.error("Gemini API error %s: %.500s", response.status_code, response.text)
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    status = str(error.get("status") or "")
    message = str(error.get("message") or "")
    if response.status_code == 429 or status == "RESOURCE_EXHAUSTED":
        return "the free Gemini limit is used up for now (it resets daily); try again later"
    if "API key" in message or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return "the Gemini API key was rejected (check HVAC_GEMINI_API_KEY)"
    if response.status_code == 404 or status == "NOT_FOUND":
        return "that Gemini model isn't available (check HVAC_GEMINI_MODEL in AI Studio)"
    if "location" in message.lower() and "not supported" in message.lower():
        return "Gemini isn't available in this region"
    return (message or f"Gemini error {response.status_code}")[:160]
