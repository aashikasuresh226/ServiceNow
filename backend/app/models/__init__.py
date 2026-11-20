"""Import all models so SQLAlchemy metadata (and Alembic) see every table."""

from app.models.customers import ExternalJob, ExternalJobEvent, IntegrationLog, ShopCustomer
from app.models.identity import (
    AuthNonce,
    EmailChallenge,
    Homeowner,
    PhoneOtp,
    RefreshToken,
    ShopUser,
)
from app.models.service_request import (
    Complaint,
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
    "Complaint",
    "EmailChallenge",
    "ExternalJob",
    "ExternalJobEvent",
    "Homeowner",
    "IntegrationLog",
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
