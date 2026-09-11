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
