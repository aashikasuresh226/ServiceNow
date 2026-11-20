"""Password rules for shop accounts.

- at least 8 characters, with a capital letter, a number and a symbol;
- not a common password ("Password1!" is rejected: its letters are "password");
- not in a known data breach, checked with Have I Been Pwned's free "Pwned
  Passwords" service using k-anonymity: only the first 5 characters of the
  password's SHA-1 hash are sent, the service returns every leaked hash starting
  with them, and the match is done here. The password never leaves the server.
"""

from __future__ import annotations

import hashlib
import logging
import re

import httpx

from app.core.errors import AppError

log = logging.getLogger(__name__)

MIN_LENGTH = 8
MAX_LENGTH = 200
HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"

# The most-used passwords and password "words" (from public breach-frequency lists).
# Compared case-insensitively against the whole password and its letters alone.
COMMON = frozenset(
    [
        "password",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "pass",
        "passwd",
        "letmein",
        "welcome",
        "welcomeback",
        "admin",
        "administrator",
        "root",
        "user",
        "login",
        "guest",
        "test",
        "tester",
        "qwerty",
        "qwertyuiop",
        "asdf",
        "asdfgh",
        "asdfghjkl",
        "zxcvbn",
        "zxcvbnm",
        "abc",
        "abcd",
        "abcdef",
        "abcdefg",
        "qazwsx",
        "qwe",
        "qweasd",
        "iloveyou",
        "loveyou",
        "love",
        "lovely",
        "princess",
        "sunshine",
        "shadow",
        "monkey",
        "dragon",
        "master",
        "football",
        "baseball",
        "basketball",
        "soccer",
        "hockey",
        "superman",
        "batman",
        "starwars",
        "pokemon",
        "charlie",
        "michael",
        "jordan",
        "jennifer",
        "hunter",
        "killer",
        "trustno",
        "whatever",
        "freedom",
        "secret",
        "summer",
        "winter",
        "spring",
        "autumn",
        "hello",
        "hellokitty",
        "flower",
        "flowers",
        "cheese",
        "computer",
        "internet",
        "google",
        "samsung",
        "apple",
        "iphone",
        "android",
        "football",
        "mustang",
        "ginger",
        "maggie",
        "buster",
        "tigger",
        "pepper",
        "cookie",
        "banana",
        "chocolate",
        "orange",
        "purple",
        "yellow",
        "changeme",
        "default",
        "company",
        "business",
        "office",
        "hvac",
        "heating",
        "cooling",
        "service",
        "servicenow",
        "homeowner",
        "technician",
        "contractor",
        "money",
        "dollar",
        "success",
        "access",
        "matrix",
        "ninja",
    ]
)


def problems(password: str) -> list[str]:
    """What's wrong with a password, in plain words (empty = OK). Shown as a checklist."""
    issues: list[str] = []
    if len(password) < MIN_LENGTH:
        issues.append(f"at least {MIN_LENGTH} characters")
    if not re.search(r"[A-Z]", password):
        issues.append("a capital letter")
    if not re.search(r"\d", password):
        issues.append("a number")
    if not re.search(r"[^A-Za-z0-9]", password):
        issues.append("a symbol (like ! # $ %)")
    return issues


def is_common(password: str) -> bool:
    lowered = password.lower()
    letters = re.sub(r"[^a-z]", "", lowered.replace("@", "a").replace("0", "o").replace("$", "s"))
    return lowered in COMMON or letters in COMMON or len(set(lowered)) <= 2


async def breach_count(password: str, http: httpx.AsyncClient) -> int | None:
    """How many times this password appears in known breaches; None if the check failed."""
    digest = hashlib.sha1(password.encode()).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        response = await http.get(
            HIBP_RANGE_URL + prefix, headers={"Add-Padding": "true"}, timeout=5.0
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Password breach check unavailable: %s", exc)
        return None
    for line in response.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            return int(count.strip() or 0)
    return 0


async def ensure_strong(
    password: str, *, http: httpx.AsyncClient | None, check_breaches: bool
) -> None:
    if len(password) > MAX_LENGTH:
        raise AppError("That password is too long", code="weak_password")
    missing = problems(password)
    if missing:
        raise AppError("Password needs " + ", ".join(missing), code="weak_password")
    if is_common(password):
        raise AppError(
            "That password is too common. Pick something less predictable.", code="weak_password"
        )
    # If the breach service is down we still accept the password (it passed the rules).
    if check_breaches and http is not None and (await breach_count(password, http) or 0) > 0:
        raise AppError(
            "That password has appeared in a data breach. Please choose a different one.",
            code="breached_password",
        )
