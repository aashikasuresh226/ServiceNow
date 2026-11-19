"""Import all models so SQLAlchemy metadata (and Alembic) see every table."""

from app.models.identity import (
    AuthNonce,
    EmailChallenge,
    Homeowner,
    PhoneOtp,
    RefreshToken,
    ShopUser,
)
from app.models.service_request import (
    Message,
    ProcessedWebhook,
    RequestEvent,
    RequestPhoto,
    ServiceRequest,
    TechLocation,
)
from app.models.shop import AvailabilityBlock, Shop, Technician

__all__ = [
    "AuthNonce",
    "AvailabilityBlock",
    "EmailChallenge",
    "Homeowner",
    "Message",
    "PhoneOtp",
    "ProcessedWebhook",
    "RefreshToken",
    "RequestEvent",
    "RequestPhoto",
    "ServiceRequest",
    "Shop",
    "ShopUser",
    "TechLocation",
    "Technician",
]
