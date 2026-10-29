"""Request bodies and response models for the public API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.domain.enums import SchedulingProvider


class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth ---------------------------------------------------------------------------------
class OtpStartIn(Model):
    phone: str = Field(min_length=7, max_length=20)


class OtpStartOut(Model):
    phone: str
    resend_after_seconds: int
    dev_code: str | None = Field(None, description="Local demo only: the code that was texted")


class OtpVerifyIn(Model):
    phone: str = Field(min_length=7, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class TokensOut(Model):
    access_token: str
    refresh_token: str
    expires_in: int


class HomeownerSessionOut(TokensOut):
    needs_profile: bool


class RefreshIn(Model):
    refresh_token: str


class ShopSignupIn(Model):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    shop_name: str = Field(min_length=2, max_length=160)
    name: str | None = Field(None, max_length=120)


class ShopLoginIn(Model):
    email: str = Field(max_length=254)  # lookup only; format is validated at sign-up
    password: str = Field(max_length=200)


class ShopLoginOut(Model):
    step: str  # "mfa" (enter code) | "mfa_setup" (enroll 2-step first)
    token: str
    dev_code: str | None = None


class MfaEnrollOut(Model):
    secret: str
    otpauth_uri: str
    dev_code: str | None = None


class MfaCodeIn(Model):
    code: str = Field(min_length=6, max_length=8)


class MfaLoginIn(MfaCodeIn):
    token: str


# --- Homeowner ------------------------------------------------------------------------------
class HomeownerOut(Model):
    id: uuid.UUID
    phone: str
    name: str | None
    address: str | None
    lat: float | None
    lng: float | None
    sms_opt_in: bool
    payment_method_label: str | None


class HomeownerUpdateIn(Model):
    name: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=300)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    sms_opt_in: bool | None = None


class CardSetupOut(Model):
    provider: str  # "stripe" | "demo"
    publishable_key: str | None
    customer_id: str
    setup_intent_id: str
    client_secret: str
    ephemeral_key_secret: str | None


class CardSetupFinishIn(Model):
    setup_intent_id: str = Field(max_length=100)


class DemoCardIn(Model):
    setup_intent_id: str = Field(max_length=100)
    card_number: str = Field(min_length=12, max_length=23)


# --- Requests -------------------------------------------------------------------------------
class RequestCreateIn(Model):
    symptoms: list[str] = Field(default_factory=list, max_length=6)
    description: str | None = Field(None, max_length=2000)
    urgency: str = "asap"
    address: str | None = Field(None, max_length=300)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)


class UnitUpdateIn(Model):
    brand: str | None = Field(None, max_length=60)
    model_number: str | None = Field(None, max_length=60)
    equipment_type: str | None = None
    approx_age_years: int | None = None


class PreferencesIn(Model):
    soft_skills: list[str] = Field(default_factory=list, max_length=10)
    require_all: bool = False


class RatingIn(Model):
    rating: int = Field(ge=1, le=5)


class PhotoOut(Model):
    id: uuid.UUID
    url: str


class TechnicianSummary(Model):
    id: uuid.UUID
    name: str
    first_name: str
    photo_url: str | None
    rating: float | None
    rating_count: int
    certifications: list[str]
    soft_skills_matched: list[str]
    shop_name: str
    shop_phone: str | None
    distance_km: float | None
    eta_minutes: int | None
    location: dict[str, float] | None


class WaitlistInfo(Model):
    position: int | None
    eta_minutes: int | None
    since: datetime | None


class EstimateInfo(Model):
    diagnostic_fee_cents: int | None
    low_cents: int | None


class QuoteInfo(Model):
    final_price_cents: int
    notes: str | None


class PaymentInfo(Model):
    authorized_cents: int | None
    captured_cents: int | None


class RequestOut(Model):
    id: uuid.UUID
    status: str
    created_at: datetime
    symptoms: list[str]
    description: str | None
    urgency: str
    address: str | None
    lat: float
    lng: float
    photos: list[PhotoOut]
    unit: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    estimate: EstimateInfo
    soft_skills: list[str]
    require_all_skills: bool
    technician: TechnicianSummary | None
    proposal_expires_at: datetime | None
    offer_expires_at: datetime | None
    waitlist: WaitlistInfo | None
    quote: QuoteInfo | None
    payment: PaymentInfo
    rating: int | None
    canceled_reason: str | None
    completed_at: datetime | None


# --- Shop -----------------------------------------------------------------------------------
class ShopOut(Model):
    id: uuid.UUID
    name: str
    phone: str | None
    address: str | None
    lat: float | None
    lng: float | None
    timezone: str
    is_live: bool
    payouts_enabled: bool
    payout_schedule: str
    scheduling_provider: str
    scheduling_last_synced_at: datetime | None
    scheduling_last_error: str | None
    write_back_jobs: bool


class ShopMeOut(Model):
    user_email: str
    user_name: str | None
    shop: ShopOut


class ShopUpdateIn(Model):
    name: str | None = Field(None, max_length=160)
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=300)
    timezone: str | None = Field(None, max_length=64)


class LiveIn(Model):
    is_live: bool


class PayoutScheduleIn(Model):
    schedule: str


class LinkOut(Model):
    url: str


class SchedulingConnectIn(Model):
    provider: SchedulingProvider
    credentials: dict[str, str]
    write_back_jobs: bool = True


class CountOut(Model):
    count: int


class TechnicianIn(Model):
    name: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=20)
    photo_url: str | None = Field(None, max_length=500)
    equipment_types: list[str] | None = None
    certifications: list[str] | None = None
    soft_skills: list[str] | None = None
    service_radius_km: float | None = None
    working_hours: dict[str, list[list[str]]] | None = None
    is_active: bool | None = None


class TechnicianOut(Model):
    id: uuid.UUID
    name: str
    phone: str | None
    photo_url: str | None
    external_id: str | None
    equipment_types: list[str]
    certifications: list[str]
    soft_skills: list[str]
    service_radius_km: float
    working_hours: dict[str, Any]
    is_active: bool
    rating: float | None
    rating_count: int


class BlockOut(Model):
    kind: str
    starts_at: datetime
    ends_at: datetime


class BusyIn(Model):
    minutes: int = Field(ge=5, le=720)


class TechDayOut(Model):
    technician: TechnicianOut
    blocks: list[BlockOut]
    free_now: bool
    on_job: bool


class DashboardOut(Model):
    techs_free_now: int
    techs_on_job: int
    open_offers: int
    active_jobs: int
    waitlisted_nearby: int


class AcceptIn(Model):
    technician_id: uuid.UUID | None = None


class QuoteIn(Model):
    final_price_cents: int = Field(gt=0, le=50_000_00)
    notes: str | None = Field(None, max_length=1000)


class ShopJobOut(Model):
    id: uuid.UUID
    status: str
    created_at: datetime
    customer_first_name: str | None
    customer_phone: str | None  # only after dispatch
    address: str | None  # only after dispatch
    area_label: str
    distance_km: float | None
    symptoms: list[str]
    description: str | None
    photos: list[PhotoOut]
    unit: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    estimate: EstimateInfo
    soft_skills: list[str]
    technician_id: uuid.UUID | None
    technician_name: str | None
    offer_expires_at: datetime | None
    quote: QuoteInfo | None
    payment: PaymentInfo
    payout_cents: int | None  # what the shop receives after the platform fee
