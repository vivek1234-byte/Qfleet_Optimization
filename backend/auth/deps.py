"""
FastAPI dependencies: bearer token in, ``Employee`` out.

**This is the authorization boundary, not the sidebar.** The frontend hides
the admin navigation from non-administrators, which is a courtesy to the user;
``require_admin`` below is what actually stops an employee from calling
``POST /api/admin/employees`` with curl. Every admin route declares it.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from core.errors import AuthenticationError, PermissionError_
from db.models import Employee, Role
from db.session import get_db

from .security import TokenError, decode_access_token
from .service import get_by_pk

# Same text for every authentication failure the client could use to probe.
GENERIC_AUTH_MESSAGE = "Invalid Employee ID or password"


def _bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    
    # Fallback for EventSource (Server-Sent Events) which cannot send headers
    query_token = request.query_params.get("token")
    if query_token:
        return query_token.strip()
        
    return None


def get_current_employee(
    request: Request,
    db: Session = Depends(get_db),
) -> Employee:
    """
    The signed-in employee, or 401.

    Re-reads the row on every request rather than trusting the claims in the
    token. That costs one indexed lookup and buys the thing a stateless token
    otherwise cannot do: an account deactivated in the admin dashboard stops
    working immediately, instead of when its token happens to expire.
    """
    token = _bearer_token(request)
    if not token:
        raise AuthenticationError("Sign in to continue.")

    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    try:
        pk = int(claims.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Your session is no longer valid. Sign in again.") from exc

    employee = get_by_pk(db, pk)
    if employee is None:
        raise AuthenticationError("Your session is no longer valid. Sign in again.")
    if not employee.is_active:
        raise AuthenticationError("Account is inactive. Contact an administrator.")

    # The revocation check. A password change or a forced sign-out increments
    # the stored counter, which strands every token issued before it — this is
    # the line that makes "change your password" actually end a stolen
    # session rather than merely stop new ones being created.
    if int(claims.get("tv", 0)) != int(employee.token_version):
        raise AuthenticationError(
            "Your session was ended. Sign in again.",
            code="SESSION_REVOKED",
        )

    return employee


def require_admin(employee: Employee = Depends(get_current_employee)) -> Employee:
    """403 for anyone who is not an administrator."""
    if employee.role != Role.ADMIN.value:
        raise PermissionError_("Administrator access is required for this action.")
    return employee
