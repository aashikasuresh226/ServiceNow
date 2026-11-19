"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm.exc import StaleDataError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.routers import auth, calendar, homeowner, public, shop, technician
from app.container import Container, build_container
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.worker import run_forever

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container or build_container(settings)
        stop = asyncio.Event()
        worker_task = None
        if settings.run_worker_in_process:
            worker_task = asyncio.create_task(run_forever(app.state.container, stop))
        try:
            yield
        finally:
            stop.set()
            if worker_task:
                await worker_task
            await app.state.container.aclose()

    app = FastAPI(title="HVAC Connect API", version="0.1.0", lifespan=lifespan)
    if container is not None:
        app.state.container = container

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "code": "conflict",
                    "message": "This request just changed. Please refresh.",
                }
            },
        )

    prefix = settings.api_prefix
    for router in (
        public.router,
        auth.router,
        homeowner.router,
        shop.router,
        technician.router,
        calendar.router,
    ):
        app.include_router(router, prefix=prefix)
    return app


app = create_app()
