"""Import all models so SQLAlchemy metadata (and Alembic) see every table."""

from app.models.identity import Homeowner, PhoneOtp, RefreshToken, ShopUser
from app.models.service_request import ProcessedWebhook, RequestEvent, RequestPhoto, ServiceRequest
from app.models.shop import AvailabilityBlock, Shop, Technician

__all__ = [
    "AvailabilityBlock",
    "Homeowner",
    "PhoneOtp",
    "ProcessedWebhook",
    "RefreshToken",
    "RequestEvent",
    "RequestPhoto",
    "ServiceRequest",
    "Shop",
    "ShopUser",
    "Technician",
]
