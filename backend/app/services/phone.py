"""Phone numbers: checked with Google's libphonenumber, stored as E.164 (+14045550123).

libphonenumber knows every country's numbering plan, so it rejects numbers that
can't exist (wrong length, an area code that isn't assigned, ...). It can't tell
whether a number is in service or who owns it: only a texted code proves that.
"""

from __future__ import annotations

import phonenumbers

from app.core.errors import AppError

DEFAULT_REGION = "US"


def normalize_phone(raw: str) -> str:
    try:
        parsed = phonenumbers.parse(raw.strip(), DEFAULT_REGION)
    except phonenumbers.NumberParseException as exc:
        raise AppError("Please enter a valid phone number", code="invalid_phone") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise AppError(
            "That phone number doesn't exist. Check the area code and digits.",
            code="invalid_phone",
        )
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_optional_phone(raw: str | None) -> str | None:
    return normalize_phone(raw) if raw and raw.strip() else None


def mask_phone(phone: str) -> str:
    return f"{phone[:-4].replace(phone[2:-4], '•' * len(phone[2:-4]))}{phone[-4:]}"
