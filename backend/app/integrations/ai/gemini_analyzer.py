"""Google Gemini reads the unit photos: same instructions, JSON schema and validation
as the Claude analyzer (anthropic_analyzer.py), so results look identical in the app.

Gemini has a free tier (key from https://aistudio.google.com/apikey) with daily
request limits; Google may use free-tier prompts to improve its products. Only the
photos, the selected symptoms and the homeowner's description are sent.

Several keys (HVAC_GEMINI_API_KEY=key1,key2,...) spread the load: each request starts
with the next key in turn, and a key that hits its limit (429) or is rejected is rested
for a while and the next key is tried. Google counts limits per Cloud *project*, so keys
only add capacity when each comes from a different project.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import logging
import time
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
    request_text,
)
from app.integrations.ai.base import AnalysisResult, PhotoInput, PriceContext

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
KEY_REST_SECONDS = {429: 60.0, 401: 3600.0, 403: 3600.0}


class GeminiUnitAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        max_concurrency: int = 8,
        timeout_seconds: float = 20.0,
        http: httpx.AsyncClient | None = None,
        api_base: str = API_BASE,
        fallback_models: list[str] | None = None,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self._keys = [k.strip() for k in api_key.split(",") if k.strip()]
        if not self._keys:
            raise ValueError("No Gemini API key")
        self._turn = itertools.count()
        self._resting: dict[str, float] = {}  # key -> monotonic time it may be used again
        self._models = list(dict.fromkeys([model, *(fallback_models or [])]))
        self._api_base = api_base
        self._delay = retry_delay_seconds
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))
        self._slots = asyncio.Semaphore(max_concurrency)

    async def analyze(
        self,
        *,
        symptoms: list[str],
        description: str | None,
        photos: list[PhotoInput],
        current_year: int,
        price_context: PriceContext | None = None,
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
                "text": request_text(
                    symptoms=symptoms,
                    description=description,
                    images=images,
                    current_year=current_year,
                    price_context=price_context,
                )
            }
        )

        async with self._slots:
            model, response = await self._call_models(parts)
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
            model,
            images,
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
        )
        return parse_analysis(parsed, current_year=current_year)

    def _key_order(self) -> list[str]:
        """Keys starting with the next one in turn; rested keys last (still tried if all are)."""
        start = next(self._turn) % len(self._keys)
        ordered = self._keys[start:] + self._keys[:start]
        now = time.monotonic()
        return sorted(ordered, key=lambda k: self._resting.get(k, 0.0) > now)

    async def _call_models(self, parts: list[dict[str, Any]]) -> tuple[str, httpx.Response]:
        """Try the main model, then the fallbacks while Google says a model is busy (503/500),
        missing (404) or over quota (429, after every key was tried: each model has its
        own quota). Within a model, a key over its limit or rejected moves on to the next key."""
        model = self._models[0]
        response: httpx.Response | None = None
        keys = self._key_order()
        for model in self._models:
            for key in keys:
                response = await self._post(model, parts, key=key, schema=True)
                if response.status_code == 400 and "schema" in response.text.lower():
                    # Older models/endpoints may not accept a JSON schema: ask for plain JSON.
                    log.warning("Gemini %s rejected the JSON schema; retrying as plain JSON", model)
                    response = await self._post(model, parts, key=key, schema=False)
                rest = KEY_REST_SECONDS.get(response.status_code)
                if rest is None:
                    break  # an answer, or a model problem another key won't fix
                self._resting[key] = time.monotonic() + rest
                if len(keys) > 1:
                    log.warning(
                        "Gemini key %s answered %s; trying the next key",
                        _label(key),
                        response.status_code,
                    )
            assert response is not None
            if response.status_code not in (401, 403, 404, 429, 500, 503, 504):
                return model, response
            if response.status_code in (401, 403):
                return model, response  # every key was rejected: no model will help
            log.warning("Gemini %s answered %s; trying the next model", model, response.status_code)
        assert response is not None
        return model, response

    async def _post(
        self, model: str, parts: list[dict[str, Any]], *, key: str, schema: bool
    ) -> httpx.Response:
        url = f"{self._api_base}/models/{model}:generateContent"
        config: dict[str, Any] = {"responseMimeType": "application/json", "temperature": 0.1}
        if schema:
            config["responseJsonSchema"] = RESPONSE_SCHEMA
        system = SYSTEM_PROMPT if schema else SYSTEM_PROMPT + PLAIN_JSON_RULES
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": config,
        }
        for attempt in range(2):  # one quick retry; then the next model is tried
            try:
                response = await self._http.post(url, json=payload, headers={"x-goog-api-key": key})
            except httpx.TimeoutException:
                log.warning("Gemini %s timed out", model)
                return httpx.Response(504, json={"error": {"status": "DEADLINE_EXCEEDED"}})
            except httpx.HTTPError as exc:
                log.warning("Gemini unreachable: %s", exc)
                raise AnalysisFailed("couldn't reach Google Gemini (check the internet)") from exc
            if response.status_code not in (500, 503) or attempt == 1:
                return response
            log.warning("Gemini %s is busy (%s); retrying", model, response.status_code)
            await asyncio.sleep(self._delay * (attempt + 1))  # overloaded: back off, retry
        return response


def _label(key: str) -> str:
    """Identify a key in logs without revealing it."""
    return f"...{key[-4:]}"


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
        return (
            "the free Gemini limit is used up for now on every key (it resets daily); "
            "try again later"
        )
    if "API key" in message or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return "the Gemini API key was rejected (check HVAC_GEMINI_API_KEY)"
    if response.status_code in (500, 503, 504) or status in ("UNAVAILABLE", "DEADLINE_EXCEEDED"):
        return "Google's free Gemini service is busy right now; try again in a minute"
    if response.status_code == 404 or status == "NOT_FOUND":
        return "that Gemini model isn't available (check HVAC_GEMINI_MODEL in AI Studio)"
    if "location" in message.lower() and "not supported" in message.lower():
        return "Gemini isn't available in this region"
    return (message or f"Gemini error {response.status_code}")[:160]
