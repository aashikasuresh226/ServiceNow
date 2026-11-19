"""Catch bad email addresses before we send anything: common typos ("gmial.com") and
domains that can't receive mail (no mail server in DNS). Proof that the person owns
the address comes later, from the emailed link."""

from __future__ import annotations

import asyncio
import logging

from email_validator import EmailNotValidError, EmailUndeliverableError, validate_email

from app.core.errors import AppError

log = logging.getLogger(__name__)

TYPOS = {
    "gmial.com": "gmail.com",
    "gmal.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gamil.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gmail.con": "gmail.com",
    "gnail.com": "gmail.com",
    "yaho.com": "yahoo.com",
    "yahooo.com": "yahoo.com",
    "yahoo.con": "yahoo.com",
    "hotmial.com": "hotmail.com",
    "hotmal.com": "hotmail.com",
    "hotmail.con": "hotmail.com",
    "outlok.com": "outlook.com",
    "outloo.com": "outlook.com",
    "outlook.con": "outlook.com",
    "iclod.com": "icloud.com",
    "icloud.con": "icloud.com",
    "gatech.ed": "gatech.edu",
}


async def check_email(raw: str, *, check_dns: bool) -> str:
    email = raw.strip().lower()
    domain = email.rpartition("@")[2]
    if domain in TYPOS:
        raise AppError(
            f"Did you mean {email.rpartition('@')[0]}@{TYPOS[domain]}?", code="email_typo"
        )
    try:
        result = await asyncio.to_thread(
            validate_email, email, check_deliverability=check_dns, timeout=4
        )
    except EmailUndeliverableError as exc:
        raise AppError(
            f"{domain} can't receive email. Check the address.", code="email_undeliverable"
        ) from exc
    except EmailNotValidError as exc:
        raise AppError("Please enter a valid email address", code="invalid_email") from exc
    except Exception as exc:  # DNS unreachable: don't block sign-up, the link still proves it
        log.info("Email DNS check skipped: %s", exc)
        return email
    return result.normalized.lower()
