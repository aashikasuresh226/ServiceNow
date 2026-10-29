"""Phone number normalization to E.164 (US-first, international allowed)."""

from __future__ import annotations

import re

from app.core.errors import AppError


def normalize_phone(raw: str) -> str:
    has_plus = raw.strip().startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not has_plus and len(digits) == 10:
        return f"+1{digits}"
    if not has_plus and len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if has_plus and 8 <= len(digits) <= 15:
        return f"+{digits}"
    raise AppError("Please enter a valid mobile number", code="invalid_phone")


def mask_phone(phone: str) -> str:
    return f"{phone[:-4].replace(phone[2:-4], '•' * len(phone[2:-4]))}{phone[-4:]}"
