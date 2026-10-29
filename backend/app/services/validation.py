"""Validation helpers shared by services."""

from __future__ import annotations

from enum import Enum

from app.core.errors import AppError


def validate_options(values: list[str], enum_cls: type[Enum], field: str) -> list[str]:
    """Reject values outside the enum and de-duplicate while keeping order."""
    allowed = {e.value for e in enum_cls}
    bad = [v for v in values if v not in allowed]
    if bad:
        raise AppError(f"Unknown {field}: {', '.join(bad)}", code="invalid_option")
    return list(dict.fromkeys(values))
