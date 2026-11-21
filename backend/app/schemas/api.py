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
    dev_code: str | None = Field(
        None, description="Development without Twilio only: the code, shown on screen"
    )


class OtpVerifyIn(Model):
    phone: str = Field(min_length=7, max_length=20)
    code: str = Field(min_length=4, max_length=8)


class TokensOut(Model):
    access_token: str
    refresh_token: str
    expires_in: int


class HomeownerSessionOut(TokensOut):
    needs_profile: bool
    backup_codes: list[str] = []  # only right after setting up the authenticator


class TechSessionOut(TokensOut):
    backup_codes: list[str] = []


class AuthenticatorSetupOut(Model):
    setup_token: str
    secret: str  # to type into the authenticator app
    otpauth_uri: str  # QR code / "add to authenticator" link


class PhoneIn(Model):
    phone: str = Field(min_length=7, max_length=20)


class HomeownerStartOut(Model):
    account: str  # existing: sign in | new: set up an authenticator (or choose email)
    setup: AuthenticatorSetupOut | None
    method: str | None = None  # existing: authenticator | email
    email_hint: str | None = None  # existing email accounts: j***@gmail.com


class HomeownerEmailStartIn(PhoneIn):
    email: EmailStr | None = None  # new accounts only; existing ones use the email on file


class EmailLinkSentOut(Model):
    sent_to: str | None  # j***@gmail.com (None: not said, for technicians)
    dev_link: str | None = None  # development only (no Firebase): open it to "click" the email


class HomeownerEmailFinishIn(Model):
    token: str = Field(min_length=10, max_length=200)
    phone: str | None = Field(None, max_length=20)  # from the link (new accounts)


class TechEmailStartIn(Model):
    login: str = Field(min_length=5, max_length=254)  # phone number or email


class TokenIn(Model):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(Model):
    email: EmailStr


class ForgotPasswordIn(Model):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordIn(Model):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)  # rules: core.passwords


class HomeownerSignupIn(PhoneIn):
    setup_token: str = Field(min_length=20, max_length=1000)
    code: str = Field(min_length=6, max_length=8)


class HomeownerLoginIn(PhoneIn):
    code: str = Field(min_length=6, max_length=12)  # authenticator or backup code


class TechLoginIn(Model):
    login: str = Field(min_length=5, max_length=254)  # phone number or email
    code: str = Field(min_length=6, max_length=12)


class InviteAuthenticatorIn(Model):
    token: str = Field(min_length=10, max_length=200)
    claim: str = Field(min_length=10, max_length=200)


class RefreshIn(Model):
    refresh_token: str


class ShopSignupIn(Model):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)  # rules: core.passwords
    shop_name: str = Field(min_length=2, max_length=160)
    name: str | None = Field(None, max_length=120)


class ShopLoginIn(Model):
    email: str = Field(max_length=254)  # lookup only; format is validated at sign-up
    password: str = Field(max_length=200)


class EmailLinkOut(Model):
    """Send `continue_url` to `email` with Firebase (delivery=firebase), or, in development
    without Firebase, open `dev_link` to stand in for clicking the email."""

    email: str
    continue_url: str
    delivery: str
    dev_link: str | None = None


class StepTokenIn(Model):
    token: str = Field(min_length=10, max_length=4000)  # a sign-in step token (JWT)


class LoginCodeOut(Model):
    code: str  # shown by the emailed sign-in link, typed on the computer that's signing in


class ShopLoginOut(Model):
    # verify_email (open the emailed link) | mfa (authenticator code) | mfa_email (a sign-in
    # link was emailed) | mfa_setup (choose authenticator or email first)
    step: str
    token: str
    email_link: EmailLinkOut | None = None


class EmailProofIn(Model):
    token: str = Field(min_length=10, max_length=200)


class EmailProofInfoOut(Model):
    email: str
    purpose: str


class InviteInfoOut(Model):
    shop_name: str
    technician_name: str
    email: str
    email_verified: bool
    can_respond_offers: bool
    can_contact_customers: bool
    schedule_view: str


class ClaimOut(Model):
    claim: str


class InvitePhoneIn(Model):
    token: str = Field(min_length=10, max_length=200)
    claim: str = Field(min_length=10, max_length=200)
    phone: str = Field(min_length=7, max_length=20)


class InviteAcceptIn(Model):
    token: str = Field(min_length=10, max_length=200)
    claim: str = Field(min_length=10, max_length=200)
    phone: str | None = Field(None, max_length=20)
    setup_token: str | None = Field(None, max_length=1000)
    code: str | None = Field(None, max_length=8)
    google_id_token: str | None = Field(None, max_length=4096)
    email_sign_in: bool = False  # no authenticator: sign in with emailed links


class MfaEnrollOut(Model):
    secret: str
    otpauth_uri: str


class NonceOut(Model):
    nonce: str


class GoogleHomeownerIn(Model):
    id_token: str = Field(min_length=20, max_length=4096)


class GoogleShopIn(GoogleHomeownerIn):
    shop_name: str | None = Field(None, max_length=160)


class PhoneStartIn(Model):
    phone: str = Field(min_length=7, max_length=20)


class PhoneVerifyIn(PhoneStartIn):
    code: str = Field(min_length=4, max_length=8)


class MfaCodeIn(Model):
    code: str = Field(min_length=6, max_length=8)


class MfaLoginIn(MfaCodeIn):
    token: str


# --- Homeowner ------------------------------------------------------------------------------
class HomeownerOut(Model):
    id: uuid.UUID
    phone: str | None
    email: str | None
    name: str | None
    address: str | None
    lat: float | None
    lng: float | None
    sms_opt_in: bool
    payment_method_label: str | None
    photo_url: str | None = None


class ProfileSuggestionsOut(Model):
    name: str | None
    address: str | None
    companies: list[str]


class CustomerInviteIn(Model):
    code: str = Field(min_length=4, max_length=16)


class InviteOut(Model):
    shop_name: str
    shop_phone: str | None


class HomeownerUpdateIn(Model):
    name: str | None = Field(None, max_length=120)
    address: str | None = Field(None, max_length=300)  # looked up with the geocoder
    sms_opt_in: bool | None = None


class CardSetupOut(Model):
    publishable_key: str
    customer_id: str
    setup_intent_id: str
    client_secret: str
    ephemeral_key_secret: str | None


class CardSetupFinishIn(Model):
    setup_intent_id: str = Field(max_length=100)


# --- Requests -------------------------------------------------------------------------------
class RequestCreateIn(Model):
    symptoms: list[str] = Field(default_factory=list, max_length=6)
    description: str | None = Field(None, max_length=2000)
    urgency: str = "asap"
    # Defaults to the homeowner's saved address; looked up with the geocoder.
    address: str | None = Field(None, max_length=300)


class UnitUpdateIn(Model):
    brand: str | None = Field(None, max_length=60)
    model_number: str | None = Field(None, max_length=60)
    equipment_type: str | None = None
    approx_age_years: int | None = None


class RatingIn(Model):
    rating: int | None = Field(None, ge=1, le=5)  # the technician (older apps send only this)
    technician_rating: int | None = Field(None, ge=1, le=5)
    shop_rating: int | None = Field(None, ge=1, le=5)
    review: str | None = Field(None, max_length=500)


class MatchIn(Model):
    """Who the homeowner wants: a company, a specific technician, or neither (soonest)."""

    shop_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None


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
    shop_name: str
    shop_phone: str | None
    shop_logo_url: str | None = None
    distance_km: float | None
    eta_minutes: int | None
    arrival_at: datetime | None  # when the tech is expected (now-ish, or e.g. tomorrow 8:15)
    # Live position: ONLY while this job is en route (null before and after).
    location: dict[str, float] | None
    location_updated_at: datetime | None = None
    # Direct number, only if the company lets this technician take customer calls.
    phone: str | None = None
    can_message: bool = False
    # False while the company is still choosing the technician (name shows the company).
    assigned: bool = True


class WaitlistInfo(Model):
    position: int | None
    eta_minutes: int | None
    since: datetime | None
    reason: str | None = None  # why nobody could be matched, in plain language


class EstimateInfo(Model):
    diagnostic_fee_cents: int | None
    low_cents: int | None  # visit + low end of the repair
    high_cents: int | None = None  # None: the repair is priced on site
    basis: str | None = None  # what the range is based on, for the homeowner
    source: str | None = None  # ai | past_jobs | price_book


class QuoteInfo(Model):
    final_price_cents: int
    notes: str | None
    actual_issue: str | None = None


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
    technician: TechnicianSummary | None
    proposal_expires_at: datetime | None
    offer_expires_at: datetime | None
    waitlist: WaitlistInfo | None
    quote: QuoteInfo | None
    payment: PaymentInfo
    rating: int | None
    shop_rating: int | None = None
    preferred_shop_id: uuid.UUID | None = None
    preferred_technician_id: uuid.UUID | None = None
    canceled_reason: str | None
    completed_at: datetime | None
    chat_open: bool = False


class MessageOut(Model):
    id: uuid.UUID
    sender: str  # homeowner | technician | shop
    sender_name: str | None
    body: str
    created_at: datetime


class MessageIn(Model):
    body: str = Field(min_length=1, max_length=1000)


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
    rating: float | None = None
    rating_count: int = 0
    payout_schedule: str
    scheduling_provider: str
    scheduling_last_synced_at: datetime | None
    scheduling_last_error: str | None
    write_back_jobs: bool
    dispatch_mode: str = "platform"
    instant_book: bool = False
    instant_book_daily_limit: int = 3
    # Paste into Housecall Pro > App Store > Webhooks (optional; polling works without it).
    scheduling_webhook_url: str | None = None
    logo_url: str | None = None


class DispatchSettingsIn(Model):
    dispatch_mode: str | None = Field(None, pattern="^(platform|office|software)$")
    instant_book: bool | None = None
    instant_book_daily_limit: int | None = Field(None, ge=1, le=50)


class TechOptionOut(Model):
    technician_id: uuid.UUID
    name: str
    arrival_at: datetime | None
    distance_km: float | None
    available: bool
    reason: str | None  # why not, in plain words
    suggested: bool


class TimeOffIn(Model):
    starts_at: datetime
    ends_at: datetime
    label: str | None = Field(None, max_length=60)


class TimeOffOut(Model):
    id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    label: str | None


class ShopMeOut(Model):
    user_email: str
    user_name: str | None
    has_password: bool = True  # False: signed up with Google (can set one)
    shop: ShopOut


class ShopAccountIn(Model):
    name: str | None = Field(None, max_length=120)


class ChangePasswordIn(Model):
    current_password: str | None = Field(None, max_length=200)  # not needed if none is set yet
    new_password: str = Field(min_length=1, max_length=200)  # rules: core.passwords


class TechUpdateIn(Model):
    phone: str | None = Field(None, max_length=20)


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
    service_radius_km: float | None = None
    working_hours: dict[str, list[list[str]]] | None = None
    is_active: bool | None = None
    can_respond_offers: bool | None = None
    can_contact_customers: bool | None = None
    schedule_view: str | None = Field(None, pattern="^(full|next)$")
    # The same person in Housecall Pro (employee id), to match its assignments.
    external_id: str | None = Field(None, max_length=64)


class TechInviteIn(Model):
    email: EmailStr
    can_respond_offers: bool = True
    can_contact_customers: bool = True
    schedule_view: str = Field("full", pattern="^(full|next)$")


class TechnicianOut(Model):
    id: uuid.UUID
    name: str
    phone: str | None
    photo_url: str | None
    external_id: str | None
    equipment_types: list[str]
    certifications: list[str]
    service_radius_km: float
    working_hours: dict[str, Any]
    is_active: bool
    rating: float | None
    rating_count: int
    email: str | None = None
    app_status: str = "none"  # none | invited | active | disabled
    invited_at: datetime | None = None
    joined_at: datetime | None = None
    can_respond_offers: bool = True
    can_contact_customers: bool = True
    schedule_view: str = "full"


class TechInviteOut(Model):
    technician: TechnicianOut
    email_link: EmailLinkOut


class BlockOut(Model):
    kind: str
    starts_at: datetime
    ends_at: datetime
    label: str | None = None
    source: str | None = None  # job | manual | hours | servicetitan | housecall_pro


class CalendarLinkOut(Model):
    url: str  # https link to the .ics feed
    webcal_url: str  # opens Apple Calendar / Outlook directly
    google_url: str  # "add by URL" in Google Calendar (needs the API reachable from the internet)


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
    notes: str | None = Field(None, max_length=1000)  # what was fixed
    actual_issue: str | None = Field(None, max_length=40)  # what was actually wrong


class ShopJobOut(Model):
    id: uuid.UUID
    status: str
    created_at: datetime
    arrival_at: datetime | None  # when the technician is due at the home
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
    technician_id: uuid.UUID | None
    technician_name: str | None
    offer_expires_at: datetime | None
    quote: QuoteInfo | None
    payment: PaymentInfo
    payout_cents: int | None  # what the shop receives after the platform fee
    picked_by_customer: bool = False  # the homeowner chose this company / technician
    # No per-job ratings or review text: homeowners rate privately. The shop sees only the
    # averages (ShopOut.rating, TechnicianOut.rating); reviews are read by the platform admin.
    technician_flag: str | None = None  # the technician said they can't make it
    chat_open: bool = False
    driving: bool = False  # the technician is sharing their location on the way
    # False until the office / Housecall Pro dispatcher picks the technician.
    technician_confirmed: bool = True
    instant_booked: bool = False
    offered_to_several: bool = False  # first shop to accept gets it
    external_job_id: str | None = None  # the job in Housecall Pro
    external_error: str | None = None  # why sending it to Housecall Pro failed


# --- Technician app -------------------------------------------------------------------------
class TechMeOut(Model):
    id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    shop_name: str
    shop_phone: str | None
    can_respond_offers: bool
    can_contact_customers: bool
    schedule_view: str
    photo_url: str | None = None
    sign_in: str = "authenticator"  # authenticator | email | google


class TechJobOut(Model):
    id: uuid.UUID
    status: str
    arrival_at: datetime | None
    offer_expires_at: datetime | None
    customer_name: str | None
    customer_phone: str | None  # only with permission, after the job is accepted
    address: str | None  # only after the job is accepted
    area_label: str
    distance_km: float | None
    symptoms: list[str]
    description: str | None
    photos: list[PhotoOut]
    unit: dict[str, Any] | None
    diagnosis: dict[str, Any] | None
    quote: QuoteInfo | None
    approved: bool
    technician_flag: str | None
    chat_open: bool
    can_contact: bool
    completed_at: datetime | None


class OutsideJobOut(Model):
    """A job from the shop's own software (Housecall Pro), read-only in our apps."""

    id: uuid.UUID
    provider: str
    invoice_number: str | None
    work_status: str
    description: str | None
    customer_name: str | None
    customer_phone: str | None  # technicians: only with "contact customers" permission
    address: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    technician_id: uuid.UUID | None
    technician_name: str | None
    customer_uses_app: bool
    # Progress from our app: "" | en_route | on_site | working | finished
    app_status: str = ""
    on_my_way_at: datetime | None = None
    arrived_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    unsent: int = 0  # actions still waiting to reach Housecall Pro


class OutsideActivity(Model):
    id: uuid.UUID
    kind: str  # status | note | line_item | photo
    text: str
    created_at: datetime
    sent: bool
    error: str | None


class OutsideLineItem(Model):
    name: str
    quantity: float
    unit_price_cents: int
    total_cents: int


class OutsideJobDetailOut(OutsideJobOut):
    activity: list[OutsideActivity]
    line_items: list[OutsideLineItem] | None  # as Housecall Pro has them; None: unreachable


class OutsideStepIn(Model):
    step: str = Field(pattern="^(on_my_way|arrived|started|finished)$")
    summary: str | None = Field(None, max_length=2000)
    actual_issue: str | None = Field(None, max_length=40)  # what was wrong (at finish)


class OutsideLineItemIn(Model):
    name: str = Field(min_length=1, max_length=120)
    quantity: float = Field(1, gt=0, le=1000)
    unit_price_cents: int = Field(ge=0, le=10_000_000)


class OutsideNoteIn(Model):
    body: str = Field(min_length=1, max_length=2000)


class TechBoardOut(Model):
    offers: list[TechJobOut]
    jobs: list[TechJobOut]
    hidden_jobs: int
    recent: list[TechJobOut]
    # From the shop's software; merged into the day by time in the app.
    outside_jobs: list[OutsideJobOut] = []


class DeclineIn(Model):
    reason: str | None = Field(None, max_length=200)


class LocationIn(Model):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(None, ge=0, le=100000)


class CustomerOut(Model):
    id: uuid.UUID
    provider: str  # housecall_pro | app
    name: str | None
    phone: str | None
    email: str | None
    address: str | None
    status: str  # joined | invited | not_invited
    invited_at: datetime | None
    joined_at: datetime | None
    last_job_at: datetime | None
    invite_url: str
    invite_message: str


class CustomerListOut(Model):
    customers: list[CustomerOut]
    total: int
    joined: int
    invited: int
    imported_at: datetime | None
    shop_invite_url: str
    shop_invite_message: str


class UnreadChat(Model):
    request_id: uuid.UUID
    count: int
    sender_name: str | None
    preview: str  # the newest message, shortened
    last_at: datetime


class NotificationsOut(Model):
    unread_messages: list[UnreadChat]
    total_unread: int


class ComplaintIn(Model):
    category: str = Field(max_length=32)
    details: str = Field(min_length=1, max_length=2000)


class ComplaintOut(Model):
    """What the homeowner sees about their own complaint."""

    id: uuid.UUID
    category: str
    category_label: str
    details: str
    status: str  # open | resolved
    shop_response: str | None
    created_at: datetime


class ComplaintStateOut(Model):
    can_file: bool
    categories: dict[str, str]
    complaint: ComplaintOut | None


class ShopComplaintOut(ComplaintOut):
    request_id: uuid.UUID
    technician_id: uuid.UUID | None
    technician_name: str | None
    customer_name: str | None  # first name
    job_date: datetime
    issue: str | None
    shop_responded_at: datetime | None
    resolved_at: datetime | None
    resolved_by: str | None


class AdminComplaintOut(ShopComplaintOut):
    shop_id: uuid.UUID
    shop_name: str
    admin_note: str | None


class ComplaintResponseIn(Model):
    response: str = Field("", max_length=2000)
    resolved: bool = False


class AdminComplaintIn(Model):
    note: str | None = Field(None, max_length=2000)
    status: str | None = Field(None, pattern="^(open|resolved)$")


class AdminReviewOut(Model):
    request_id: uuid.UUID
    completed_at: datetime | None
    shop_name: str | None
    technician_name: str | None
    technician_rating: int | None
    shop_rating: int | None
    review: str | None


class IntegrationLogOut(Model):
    created_at: datetime
    action: str
    ok: bool
    detail: str | None


class HcpActivityOut(Model):
    connected: bool
    last_read_at: datetime | None
    last_error: str | None
    waiting: int  # updates not yet accepted by Housecall Pro
    log: list[IntegrationLogOut]


class HomeVisitOut(Model):
    """A visit the homeowner's company booked in Housecall Pro (shown so the customer sees
    the same visit in our app)."""

    id: uuid.UUID
    shop_name: str
    shop_phone: str | None
    technician_first_name: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    description: str | None
    status: str  # scheduled | en_route | on_site | working | finished
