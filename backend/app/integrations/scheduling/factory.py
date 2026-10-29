"""Build the right scheduling client from a shop's provider + decrypted credentials."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.core.errors import AppError
from app.domain.enums import SchedulingProvider
from app.integrations.scheduling.base import SchedulingClient
from app.integrations.scheduling.housecall_pro import HousecallProClient
from app.integrations.scheduling.servicetitan import ServiceTitanClient

REQUIRED_FIELDS: dict[SchedulingProvider, tuple[str, ...]] = {
    SchedulingProvider.SERVICETITAN: ("tenant_id", "client_id", "client_secret", "app_key"),
    SchedulingProvider.HOUSECALL_PRO: ("api_key",),
}

SchedulingClientFactory = Callable[[SchedulingProvider, dict[str, Any]], SchedulingClient]


def validate_credentials(provider: SchedulingProvider, credentials: dict[str, Any]) -> None:
    required = REQUIRED_FIELDS.get(provider)
    if required is None:
        raise AppError(f"Unsupported scheduling provider '{provider}'")
    missing = [f for f in required if not str(credentials.get(f, "")).strip()]
    if missing:
        raise AppError(f"Missing credentials: {', '.join(missing)}", code="missing_credentials")


def make_factory(http: httpx.AsyncClient) -> SchedulingClientFactory:
    def build(provider: SchedulingProvider, credentials: dict[str, Any]) -> SchedulingClient:
        validate_credentials(provider, credentials)
        if provider == SchedulingProvider.SERVICETITAN:
            return ServiceTitanClient(
                tenant_id=credentials["tenant_id"],
                client_id=credentials["client_id"],
                client_secret=credentials["client_secret"],
                app_key=credentials["app_key"],
                http=http,
            )
        return HousecallProClient(api_key=credentials["api_key"], http=http)

    return build
