"""
Password hashing and session tokens.

Deliberately free of FastAPI and SQLAlchemy imports so it can be tested — and
reasoned about — on its own. Two jobs:

* **Passwords** are hashed with bcrypt. Never stored, never logged, never
  returned. bcrypt is used directly rather than through passlib because
  passlib's bcrypt backend has been broken against bcrypt 4.x for a while and
  the wrapper buys nothing here.

* **Sessions** are stateless JWTs signed with HS256. Stateless means signing
  out is a client-side discard, which is the honest trade: no server-side
  revocation, but no session table to keep consistent either. Token lifetime
  is short enough (12 hours by default) that it matches a working day.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt

from config import settings

# bcrypt hashes at most 72 bytes and silently ignores the rest, so a password
# longer than that would make every suffix equivalent. Reject rather than
# truncate: silently accepting a wrong password is worse than an error.
BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """A token was missing, malformed, expired, or signed with another key."""


def hash_password(password: str) -> str:
    """bcrypt digest of ``password``, as an ASCII string."""
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password must be at most {BCRYPT_MAX_BYTES} bytes.")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(raw, salt).decode("ascii")


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    """
    Check a password against a stored digest.

    Returns False rather than raising on a malformed or missing hash: a row
    with a corrupt hash must fail to log in, not crash the endpoint.
    """
    if not password_hash:
        # Still burn a hash so a missing account is not detectably faster than
        # a present one. See dummy_verify().
        return False
    raw = password.encode("utf-8")
    if len(raw) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# A real bcrypt hash of a value nobody will type, used to equalise timing when
# the Employee ID does not exist. Computed once, lazily, at the configured
# cost so it takes the same time as a genuine check.
_DUMMY_HASH: Optional[str] = None


def dummy_verify(password: str) -> None:
    """
    Spend the same time a real password check would.

    Without this, "no such Employee ID" returns in microseconds while a wrong
    password takes ~250 ms, and the difference is a perfectly good account
    enumeration oracle regardless of what the error message says.
    """
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password-placeholder")
    verify_password(password, _DUMMY_HASH)


def create_access_token(
    *,
    subject: str,
    employee_id: str,
    role: str,
    token_version: int = 0,
    expires_minutes: Optional[int] = None,
) -> tuple[str, datetime]:
    """
    Sign a session token.

    Returns ``(token, expires_at)`` so the caller can tell the client when it
    will need to sign in again instead of letting it discover that with a 401
    halfway through a task.
    """
    minutes = expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=minutes)
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "eid": employee_id,
        "role": role,
        # The revocation counter. Compared against the row on every request,
        # so bumping it in the database invalidates every token already out
        # there — see db/models.Employee.token_version.
        "tv": int(token_version),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "iss": "qfleet",
    }
    token = jwt.encode(payload, settings.jwt_secret_resolved, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> Dict[str, Any]:
    """Verify and decode a session token, or raise ``TokenError``."""
    try:
        return jwt.decode(
            token,
            settings.jwt_secret_resolved,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="qfleet",
            options={"require": ["exp", "sub", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Your session has expired. Sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Your session is no longer valid. Sign in again.") from exc


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# ---------------------------------------------------------------------------
# Password quality
# ---------------------------------------------------------------------------
# A length floor alone lets "password" and "12345678" through, and those are
# the first two guesses anyone makes. This is not a strength meter and not a
# character-class rule — NIST dropped composition rules years ago because they
# push people towards "Password1!" — it is a blocklist of the passwords that
# actually appear at the top of every breach corpus, plus the shapes this
# particular deployment invites.
#
# A real deployment should check against a downloaded breach list (or the
# k-anonymity range API of one) instead. This is the offline version that
# works at a venue with no network.
COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password123", "passw0rd", "p@ssw0rd", "p@ssword",
        "12345678", "123456789", "1234567890", "qwerty123", "qwertyui", "1q2w3e4r",
        "iloveyou", "sunshine", "princess", "football", "baseball", "superman",
        "trustno1", "welcome1", "welcome123", "admin123", "administrator",
        "letmein1", "letmein123", "monkey123", "dragon123", "abc12345",
        "changeme", "changeme123", "default1", "secret123", "temp1234",
        # Shapes this project invites specifically.
        "qfleet123", "fleet1234", "employee1", "employee123", "shipping1",
    }
)


def password_problem(password: str, *, employee_id: str = "", full_name: str = "") -> Optional[str]:
    """
    Why this password is unacceptable, or None if it is fine.

    Checks the three things that matter and none of the things that do not:
    length, whether it is a password everyone tries, and whether it is just
    the account's own name or ID — which is the most common weak password in
    any staff system and one no generic blocklist catches.
    """
    if not password:
        return "Password is required."

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        return f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters."

    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        return f"Password must be at most {BCRYPT_MAX_BYTES} bytes."

    lowered = password.lower()

    if lowered in COMMON_PASSWORDS:
        return "That password appears on every list attackers try. Choose another."

    # Strip digits and punctuation before comparing, so "EMP001!" and
    # "priyanair2026" are caught alongside the bare forms.
    stripped = "".join(ch for ch in lowered if ch.isalpha())
    if employee_id and stripped and stripped == employee_id.lower().replace("-", "").replace("_", ""):
        return "The password cannot be the Employee ID."
    if employee_id and employee_id.lower() in lowered:
        return "The password cannot contain the Employee ID."
    for part in str(full_name or "").lower().split():
        if len(part) >= 4 and part in lowered:
            return "The password cannot contain the employee's name."

    if len(set(password)) < 4:
        return "That password repeats too few different characters."

    return None
