"""Domain errors and their mapping to HTTP responses.

Services raise these; the API layer turns them into consistent JSON errors:
{"error": {"code": "...", "message": "..."}}
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class InvalidState(AppError):
    status_code = 409
    code = "invalid_state"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"


class PaymentRequired(AppError):
    status_code = 402
    code = "payment_required"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = {
            ".".join(str(p) for p in err["loc"] if p != "body"): err["msg"] for err in exc.errors()
        }
        first = next(iter(fields.items()), ("", "Invalid input"))
        message = f"{first[0].replace('_', ' ')}: {first[1]}" if first[0] else first[1]
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": message, "fields": fields}},
        )
