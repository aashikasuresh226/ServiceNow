"""Price estimates: the AI's range, anchored on past final prices, with safe fallbacks."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.container import Container
from app.core.clock import FrozenClock
from app.domain.pricing import market_from_address
from app.integrations.ai.anthropic_analyzer import parse_estimate, request_text
from app.integrations.ai.base import PastPrice, PriceContext
from app.integrations.ai.fake import FakeUnitAnalyzer
from app.models import Homeowner, ServiceRequest
from tests.conftest import analyzed_request, homeowner_login


async def _completed_jobs(
    container: Container, clock: FrozenClock, category: str, prices: list[int]
) -> None:
    async with container.session_factory() as s:
        owner = (await s.scalars(select(Homeowner))).first()
        assert owner is not None
        for price in prices:
            s.add(
                ServiceRequest(
                    id=uuid.uuid4(),
                    homeowner_id=owner.id,
                    status="completed",
                    symptoms=["no_cooling"],
                    lat=33.76,
                    lng=-84.39,
                    issue_category=category,
                    final_price_cents=price,
                    completed_at=clock.now() - timedelta(days=30),
                )
            )
        await s.commit()


async def test_estimate_uses_past_final_prices(
    client: httpx.AsyncClient, container: Container, clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    await _completed_jobs(container, clock, "capacitor", [260_00, 300_00, 340_00])
    await _completed_jobs(container, clock, "clogged_drain", [180_00])

    req = await analyzed_request(client, home)
    analyzer = container.analyzer
    assert isinstance(analyzer, FakeUnitAnalyzer)
    ctx = analyzer.last_price_context
    assert ctx is not None
    assert ctx.market == "Atlanta, GA"  # city and state only: never the street
    assert ctx.past_overall == PastPrice("All issues", 4, 270_00, 180_00, 340_00)
    assert PastPrice("Failed capacitor", 3, 300_00, 260_00, 340_00) in ctx.past_by_issue
    assert ctx.price_book["Failed capacitor"] == 150_00
    text = request_text(
        symptoms=["no_cooling"], description="x", images=1, current_year=2026, price_context=ctx
    )
    assert "Failed capacitor: 3 jobs, average $300 (range $260-$340)" in text
    assert "Peachtree" not in text

    est = req["estimate"]
    # The fake AI prices from past capacitor jobs (repair = final price - visit fee).
    assert est["low_cents"] == 260_00 and est["high_cents"] == 340_00
    assert est["source"] == "ai" and "3 past jobs" in est["basis"]


async def test_estimate_without_ai_falls_back(
    client: httpx.AsyncClient, container: Container, clock: FrozenClock
) -> None:
    home = await homeowner_login(client)
    await _completed_jobs(container, clock, "general_diagnostic", [150_00, 210_00])
    off = replace(container, analyzer=None)
    from app.main import create_app

    app = create_app(off.settings, off)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1"
    ) as plain:
        req = await analyzed_request(plain, home)
    est = req["estimate"]
    assert est["source"] == "past_jobs"
    assert (est["low_cents"], est["high_cents"]) == (150_00, 210_00)


def test_parse_estimate_sanity() -> None:
    ok = parse_estimate({"low_usd": 180, "high_usd": 320, "basis": "Similar jobs."})
    assert ok is not None and (ok.repair_low_cents, ok.repair_high_cents) == (180_00, 320_00)
    swapped = parse_estimate({"low_usd": 500, "high_usd": 200, "basis": ""})
    assert swapped is not None and swapped.repair_low_cents == 200_00
    wide = parse_estimate({"low_usd": 100, "high_usd": 5000, "basis": "x"})
    assert wide is not None and wide.repair_high_cents == 600_00
    assert parse_estimate({"low_usd": 0, "high_usd": 0, "basis": ""}) is None  # unknown
    assert parse_estimate({"low_usd": 100, "high_usd": 90_000, "basis": ""}) is None
    assert parse_estimate({"low_usd": "a", "high_usd": 5, "basis": ""}) is None
    assert parse_estimate(None) is None


def test_market_from_address() -> None:
    assert market_from_address("191 Peachtree St NE, Atlanta, GA 30303") == "Atlanta, GA"
    assert market_from_address("12 Main St, Decatur, GA, USA") == "Decatur, GA"
    assert market_from_address("somewhere") == ""
    assert market_from_address(None) == ""


def test_no_context_lines_without_history() -> None:
    ctx = PriceContext(market="", diagnostic_fee_cents=89_00, price_book={"Failed capacitor": 1})
    text = request_text(
        symptoms=[], description=None, images=0, current_year=2026, price_context=ctx
    )
    assert "No completed jobs on this platform yet." in text
    assert "Market: United States" in text
