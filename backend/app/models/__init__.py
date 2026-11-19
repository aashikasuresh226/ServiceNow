"""Import all models so SQLAlchemy metadata (and Alembic) see every table."""

from app.models.customers import ExternalJob, ShopCustomer
from app.models.identity import (
    AuthNonce,
    EmailChallenge,
    Homeowner,
    PhoneOtp,
    RefreshToken,
    ShopUser,
)
from app.models.service_request import (
    JobOffer,
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
    "ExternalJob",
    "Homeowner",
    "JobOffer",
    "Message",
    "PhoneOtp",
    "ProcessedWebhook",
    "RefreshToken",
    "RequestEvent",
    "RequestPhoto",
    "ServiceRequest",
    "Shop",
    "ShopCustomer",
    "ShopUser",
    "TechLocation",
    "Technician",
]
