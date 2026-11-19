"""Job calendar entries, the app with payments/AI switched off, address lookup and
the photo-analysis parser."""

from __future__ import annotations

import io
import json
from dataclasses import replace

import anthropic
import httpx
import httpx2  # the HTTP library the Anthropic SDK uses
import pyotp
from PIL import Image

from app.container import Container
from app.core.clock import FrozenClock
from app.domain.enums import EquipmentType
from app.integrations.ai.anthropic_analyzer import (
    RESPONSE_SCHEMA,
    SPEC_FIELDS,
    AnalysisFailed,
    AnthropicUnitAnalyzer,
    parse_analysis,
    prepare_image,
)
from app.integrations.ai.base import PhotoInput
from app.integrations.geocoding import CensusGeocoder, format_census_address
from app.main import create_app
from tests.conftest import SeededShop, analyzed_request, homeowner_login, shop_login


async def test_booking_goes_on_the_technicians_calendar(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    proposed = (await client.post(f"/requests/{rid}/match", headers=home)).json()
    tech_id = proposed["technician"]["id"]
    await client.post(f"/requests/{rid}/confirm", headers=home)

    shop = await shop_login(client, shops["near"], clock)
    board = (await client.get("/shop/availability", headers=shop)).json()
    jobs = [b for d in board for b in d["blocks"] if b["source"] == "job"]
    assert len(jobs) == 1 and jobs[0]["label"].startswith("Pending")

    await client.post(f"/shop/jobs/{rid}/accept", headers=shop, json={})
    board = (await client.get("/shop/availability", headers=shop)).json()
    entry = next(
        b
        for d in board
        if d["technician"]["id"] == tech_id
        for b in d["blocks"]
        if b["source"] == "job"
    )
    assert entry["label"] == "Jordan Lee · 191 Peachtree St NE"

    # The tech's private calendar feed (.ics) has the job with the customer's details.
    link = (await client.get(f"/shop/technicians/{tech_id}/calendar", headers=shop)).json()
    assert link["webcal_url"].startswith("webcal://")
    feed = await client.get(link["url"].split("/v1", 1)[1])
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    text = feed.text.replace("\r\n ", "")
    assert "SUMMARY:Jordan Lee · 191 Peachtree St NE" in text
    assert "LOCATION:191 Peachtree St NE\\, Atlanta\\, GA 30303" in text
    assert "Phone: +14045550199" in text

    # Rotating the link revokes the old one.
    rotated = (
        await client.get(f"/shop/technicians/{tech_id}/calendar?rotate=true", headers=shop)
    ).json()
    assert (await client.get(link["url"].split("/v1", 1)[1])).status_code == 404
    assert (await client.get(rotated["url"].split("/v1", 1)[1])).status_code == 200


async def test_decline_and_cancel_remove_the_calendar_entry(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    rid = (await analyzed_request(client, home))["id"]
    await client.post(f"/requests/{rid}/match", headers=home)
    await client.post(f"/requests/{rid}/confirm", headers=home)
    near = await shop_login(client, shops["near"], clock)
    await client.post(f"/shop/jobs/{rid}/decline", headers=near)
    board = (await client.get("/shop/availability", headers=near)).json()
    assert not [b for d in board for b in d["blocks"] if b["source"] == "job"]

    # Re-offered to the far shop: the entry moves to their tech, then goes on cancel.
    far = await shop_login(client, shops["far"], clock)
    board = (await client.get("/shop/availability", headers=far)).json()
    assert [b for d in board for b in d["blocks"] if b["source"] == "job"]
    await client.post(f"/requests/{rid}/cancel", headers=home)
    board = (await client.get("/shop/availability", headers=far)).json()
    assert not [b for d in board for b in d["blocks"] if b["source"] == "job"]


async def test_full_job_with_payments_and_ai_switched_off(
    container: Container, clock: FrozenClock
) -> None:
    """What runs before Stripe and Anthropic keys are added: no card, no charge, no guessing."""
    built = replace(container, payments=None, analyzer=None)
    app = create_app(built.settings, built)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1"
    ) as client:
        features = (await client.get("/meta/options")).json()["features"]
        assert features["payments"] is False and features["photo_analysis"] is False

        # A brand-new shop can go live with just an address and a technician.
        r = await client.post(
            "/auth/shop/signup",
            json={
                "email": "owner@realshop.example.com",
                "password": "a-very-long-password",
                "shop_name": "Real Shop",
            },
        )
        setup = {"Authorization": f"Bearer {r.json()['token']}"}
        secret = (await client.post("/auth/shop/mfa/enroll", headers=setup)).json()["secret"]
        tokens = (
            await client.post(
                "/auth/shop/mfa/activate",
                headers=setup,
                json={"code": pyotp.TOTP(secret).at(clock.now())},
            )
        ).json()
        shop = {"Authorization": f"Bearer {tokens['access_token']}"}
        r = await client.patch(
            "/shop/me", headers=shop, json={"address": "@33.755,-84.39 1 Main St, Atlanta, GA"}
        )
        assert r.status_code == 200
        r = await client.post(
            "/shop/technicians",
            headers=shop,
            json={
                "name": "Sam Rivera",
                "equipment_types": ["central_ac", "unknown"],
                "certifications": ["epa_608"],
                "working_hours": {
                    d: [["00:00", "24:00"]] for d in ("mon", "tue", "wed", "thu", "fri")
                },
            },
        )
        assert r.status_code == 201, r.text
        r = await client.put("/shop/live", headers=shop, json={"is_live": True})
        assert r.status_code == 200, r.text

        home = await homeowner_login(client, "4045550160", with_card=False)
        rid = (await analyzed_request(client, home))["id"]
        req = (await client.get(f"/requests/{rid}", headers=home)).json()
        assert req["diagnosis"]["ai_used"] is False
        assert req["diagnosis"]["primary_issue"] == "general_diagnostic"
        assert req["unit"]["brand"] is None

        r = await client.post(f"/requests/{rid}/match", headers=home)
        assert r.json()["status"] == "proposed", r.text
        r = await client.post(f"/requests/{rid}/confirm", headers=home)
        assert r.status_code == 200 and r.json()["status"] == "offered", r.text
        for step in ("accept", "en-route", "on-site"):
            r = await client.post(f"/shop/jobs/{rid}/{step}", headers=shop, json={})
            assert r.status_code == 200, r.text
        await client.post(
            f"/shop/jobs/{rid}/quote", headers=shop, json={"final_price_cents": 24_900}
        )
        r = await client.post(f"/requests/{rid}/approve-quote", headers=home)
        assert r.status_code == 200, r.text
        done = (await client.post(f"/shop/jobs/{rid}/complete", headers=shop)).json()
        assert done["status"] == "completed"
        assert done["payment"]["captured_cents"] is None  # nothing charged in the app

        r = await client.post("/me/payment-methods/setup", headers=home)
        assert r.status_code == 400 and r.json()["error"]["code"] == "payments_not_configured"


async def test_scheduling_connect_is_coming_soon(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    r = await client.put(
        "/shop/scheduling",
        headers=shop,
        json={"provider": "housecall_pro", "credentials": {"api_key": "x"}},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "coming_soon"


async def test_census_geocoder() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "Nowhere" in request.url.params["address"]:
            return httpx.Response(200, json={"result": {"addressMatches": []}})
        return httpx.Response(
            200,
            json={
                "result": {
                    "addressMatches": [
                        {
                            "matchedAddress": "675 PONCE DE LEON AVE NE, ATLANTA, GA, 30308",
                            "coordinates": {"x": -84.36536, "y": 33.77245},
                        }
                    ]
                }
            },
        )

    geocoder = CensusGeocoder(http=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await geocoder.geocode("675 Ponce de Leon Ave NE, Atlanta, GA 30308")
    assert result.formatted_address == "675 Ponce De Leon Ave NE, Atlanta, GA 30308"
    assert (round(result.location.lat, 3), round(result.location.lng, 3)) == (33.772, -84.365)
    try:
        await geocoder.geocode("12 Nowhere Lane, Atlantis")
        raise AssertionError("expected a not-found error")
    except Exception as exc:
        assert getattr(exc, "code", "") == "invalid_address"
    assert format_census_address("1 MAIN ST, DECATUR, GA, 30030") == "1 Main St, Decatur, GA 30030"


def _plate_response(**overrides: object) -> dict[str, object]:
    specs = dict.fromkeys(SPEC_FIELDS)
    specs.update(
        {
            "cooling_capacity": "36,000 BTU/h",
            "voltage": "208/230 V",
            "phase": "1",
            "min_circuit_ampacity": "18.6",
            "max_overcurrent_protection": "30",
            "refrigerant": "R-22",
            "factory_charge": "7 lb 4 oz",
            "seer2": "SEER2 14.3",
        }
    )
    data: dict[str, object] = {
        "photos_show_hvac_equipment": True,
        "brand": "Carrier",
        "model_number": "24ACC636A003",
        "serial_number": "0807E12345",
        "equipment_type": "central_ac",
        "manufacture_year": 2007,
        "tonnage": 3,
        "fuel": "electric",
        "specs": specs,
        "visible_issues": ["Oil stain at the base of the service valve"],
        "primary_issue": "refrigerant_leak",
        "alternatives": ["capacitor", "not_a_category"],
        "confidence": "medium",
        "summary": "Your AC may be low on refrigerant.",
        "safety_warning": None,
        "photo_feedback": None,
    }
    data.update(overrides)
    return data


def test_analysis_parser_reads_the_whole_plate() -> None:
    result = parse_analysis(_plate_response(), current_year=2026)
    unit = result.unit
    assert unit.approx_age_years == 19 and unit.manufacture_year == 2007
    assert unit.refrigerant == "R-22" and unit.tonnage == 3.0 and unit.seer_rating == 14.3
    assert unit.voltage == "208/230 V"
    assert unit.specs["Min. circuit ampacity (MCA)"] == "18.6"
    assert unit.specs["Factory charge"] == "7 lb 4 oz"
    assert "Manufactured" not in unit.specs  # nulls are dropped
    assert any("lifespan" in note for note in unit.insights)
    assert any("R-22" in note for note in unit.insights)
    assert unit.equipment_type == EquipmentType.CENTRAL_AC
    assert [a.value for a in result.diagnosis.alternatives] == ["capacitor"]
    assert result.diagnosis.visible_issues == ["Oil stain at the base of the service valve"]

    junk = parse_analysis(
        _plate_response(
            photos_show_hvac_equipment=False,
            equipment_type="spaceship",
            manufacture_year=2099,
            tonnage=500,
            fuel="plutonium",
            specs="not an object",
            primary_issue="?",
            confidence="?",
            summary="",
        ),
        current_year=2026,
    )
    assert junk.unit.equipment_type == EquipmentType.UNKNOWN
    assert junk.unit.manufacture_year is None and junk.unit.tonnage is None
    assert junk.unit.fuel is None and junk.unit.specs == {}
    assert junk.unit.photo_feedback  # tells the homeowner to retake the photo


async def test_analyzer_sends_structured_output_request() -> None:
    """The request shape Sonnet 5.5 accepts: JSON-schema output, no forced tool call."""
    captured: dict[str, object] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": json.dumps(_plate_response())}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1500, "output_tokens": 300},
            },
        )

    analyzer = AnthropicUnitAnalyzer("sk-ant-test", "claude-sonnet-5-5")
    analyzer._client = anthropic.AsyncAnthropic(
        api_key="sk-ant-test",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buffer, format="JPEG")
    result = await analyzer.analyze(
        symptoms=["no_cooling"],
        description="warm air",
        photos=[PhotoInput(buffer.getvalue(), "image/jpeg")],
        current_year=2026,
    )
    assert result.unit.brand == "Carrier"
    assert "tool_choice" not in captured and "tools" not in captured
    output_config = captured["output_config"]
    assert isinstance(output_config, dict)
    assert output_config["format"]["type"] == "json_schema"
    assert output_config["effort"] == "medium"
    content = captured["messages"][0]["content"]  # type: ignore[index]
    assert [c["type"] for c in content] == ["text", "image", "text"]


def test_photos_are_downscaled_for_claude() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4000, 3000), "white").save(buffer, format="PNG")
    prepared = prepare_image(PhotoInput(buffer.getvalue(), "image/png"))
    assert prepared is not None
    data, media_type = prepared
    assert media_type == "image/jpeg"
    assert max(Image.open(io.BytesIO(data)).size) == 1568
    assert prepare_image(PhotoInput(b"garbage", "image/jpeg")) is None


async def test_shop_readiness_explains_problems(
    client: httpx.AsyncClient, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    shop = await shop_login(client, shops["near"], clock)
    body = (await client.get("/shop/readiness", headers=shop)).json()
    assert body["ready"] is True
    assert body["technicians"][0]["next_opening_label"] == "Free now"

    await client.put("/shop/live", headers=shop, json={"is_live": False})
    await client.patch(
        f"/shop/technicians/{shops['near'].tech_ids[0]}",
        headers=shop,
        json={"equipment_types": []},
    )
    body = (await client.get("/shop/readiness", headers=shop)).json()
    assert body["ready"] is False
    failing = {c["label"] for c in body["checks"] if not c["ok"]}
    assert "Accepting requests" in failing
    assert body["technicians"][0]["problems"] == ["Not qualified for any equipment type"]


def _count_schema(schema: object) -> tuple[int, int]:
    """(union-typed fields, optional fields) across a JSON schema, as the API counts them."""
    unions = optional = 0
    if isinstance(schema, dict):
        if "anyOf" in schema or isinstance(schema.get("type"), list):
            unions += 1
        props = schema.get("properties")
        if isinstance(props, dict):
            optional += len(set(props) - set(schema.get("required", [])))
        for value in schema.values():
            u, o = _count_schema(value)
            unions, optional = unions + u, optional + o
    elif isinstance(schema, list):
        for value in schema:
            u, o = _count_schema(value)
            unions, optional = unions + u, optional + o
    return unions, optional


def test_response_schema_within_structured_output_limits() -> None:
    # API limits: 16 union-typed parameters, 24 optional parameters (we use neither).
    assert _count_schema(RESPONSE_SCHEMA) == (0, 0)


def _anthropic_reply(text: str) -> dict[str, object]:
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


async def test_analyzer_falls_back_to_plain_json_and_reports_errors() -> None:
    calls: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        calls.append(body)
        if "output_config" in body:
            return httpx2.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "Schema too complex"},
                },
            )
        return httpx2.Response(
            200, json=_anthropic_reply("```json\n" + json.dumps(_plate_response()) + "\n```")
        )

    analyzer = AnthropicUnitAnalyzer("sk-ant-test", "claude-sonnet-5-5")
    analyzer._client = anthropic.AsyncAnthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    result = await analyzer.analyze(symptoms=[], description=None, photos=[], current_year=2026)
    assert result.unit.brand == "Carrier"
    assert len(calls) == 2 and "output_config" not in calls[1]

    def no_credits(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your credit balance is too low to access the Anthropic API.",
                },
            },
        )

    analyzer._client = anthropic.AsyncAnthropic(
        api_key="sk-ant-test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(no_credits)),
    )
    try:
        await analyzer.analyze(symptoms=[], description=None, photos=[], current_year=2026)
        raise AssertionError("expected a failure")
    except AnalysisFailed as exc:
        assert "out of credits" in exc.reason


async def test_failed_analysis_still_lets_the_homeowner_book(
    container: Container, shops: dict[str, SeededShop], clock: FrozenClock
) -> None:
    class Broken:
        async def analyze(self, **_: object) -> object:
            raise AnalysisFailed("the Anthropic API key was rejected")

    built = replace(container, analyzer=Broken())
    app = create_app(built.settings, built)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1"
    ) as client:
        home = await homeowner_login(client)
        req = await analyzed_request(client, home)
        assert req["status"] == "analyzed"
        assert req["diagnosis"]["ai_used"] is False
        assert "key was rejected" in req["diagnosis"]["ai_error"]
        r = await client.post(f"/requests/{req['id']}/match", headers=home)
        assert r.json()["status"] == "proposed"


async def test_gemini_analyzer_request_and_errors() -> None:
    from app.integrations.ai.gemini_analyzer import GeminiUnitAnalyzer

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if "responseJsonSchema" in body["generationConfig"]:
            return httpx.Response(
                400, json={"error": {"code": 400, "message": "Unknown field responseJsonSchema"}}
            )
        reply = "```json\n" + json.dumps(_plate_response()) + "\n```"
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": reply}], "role": "model"}}],
                "usageMetadata": {"promptTokenCount": 900, "candidatesTokenCount": 300},
            },
        )

    analyzer = GeminiUnitAnalyzer(
        "AIza-test",
        "gemini-flash-lite-latest",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buffer, format="JPEG")
    result = await analyzer.analyze(
        symptoms=["no_cooling"],
        description="warm air",
        photos=[PhotoInput(buffer.getvalue(), "image/jpeg")],
        current_year=2026,
    )
    assert result.unit.brand == "Carrier" and result.unit.approx_age_years == 19
    first = seen[0]
    assert first.url.path == "/v1beta/models/gemini-flash-lite-latest:generateContent"
    assert first.headers["x-goog-api-key"] == "AIza-test"
    parts = json.loads(first.content)["contents"][0]["parts"]
    assert parts[1]["inline_data"]["mime_type"] == "image/jpeg"
    assert len(seen) == 2  # schema rejected → plain JSON retry

    def quota(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota"}}
        )

    analyzer = GeminiUnitAnalyzer(
        "AIza-test",
        "gemini-flash-lite-latest",
        http=httpx.AsyncClient(transport=httpx.MockTransport(quota)),
    )
    try:
        await analyzer.analyze(symptoms=[], description=None, photos=[], current_year=2026)
        raise AssertionError("expected a failure")
    except AnalysisFailed as exc:
        assert "free Gemini limit" in exc.reason


def test_auto_provider_prefers_claude_then_gemini() -> None:
    from pydantic import SecretStr

    from app.core.config import Settings

    assert Settings(ai_provider="auto").resolved_ai_provider == "off"
    gemini = Settings(ai_provider="auto", gemini_api_key=SecretStr("AIza"))
    assert gemini.resolved_ai_provider == "gemini" and gemini.ai_enabled
    both = Settings(
        ai_provider="auto", gemini_api_key=SecretStr("AIza"), anthropic_api_key=SecretStr("sk")
    )
    assert both.resolved_ai_provider == "anthropic"
