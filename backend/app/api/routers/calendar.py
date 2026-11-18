"""Technician calendar feeds (.ics). The secret token in the URL is the only credential,
the same model Google Calendar uses for "secret address in iCal format"."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import ContainerDep, SessionDep
from app.core.errors import NotFound
from app.services.calendar_service import CalendarService

router = APIRouter(tags=["calendar"])


@router.get("/calendar/{token}.ics", include_in_schema=False)
async def technician_feed(token: str, session: SessionDep, c: ContainerDep) -> Response:
    if len(token) < 20:
        raise NotFound("Calendar not found")
    body = await CalendarService(session, c).ics_for_token(token)
    if body is None:
        raise NotFound("Calendar not found")
    return Response(
        content=body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300"},
    )
