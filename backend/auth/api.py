"""
Sign-in routes: ``/api/auth/*``.

The one rule that shapes this module: **a failed sign-in must not reveal
whether the Employee ID exists.** That means the same message, the same
status code, and — via ``dummy_verify`` — roughly the same response time
whether the ID is unknown or the password is wrong. An error that says
"unknown Employee ID" turns a login form into a staff directory.

A *disabled* account is the one case that could report itself distinctly, and
by default it does not — ``QGF_DISCLOSE_INACTIVE`` is false, so a revoked
account fails exactly like a wrong password. Turning it on is kinder to the
person (they know to call an administrator instead of retrying) at the cost of
confirming the Employee ID exists. Choose per deployment; the private default
is the safer one to ship.

Attempts are rate limited per Employee ID and per client address — see
``ratelimit.py`` for why both.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from config import settings
from core.errors import AuthenticationError, ValidationError
from db.models import Employee
from db.session import get_db

from . import ratelimit
from .deps import GENERIC_AUTH_MESSAGE, get_current_employee
from .schemas import (
    ChangePasswordRequest,
    EmployeeOut,
    LoginRequest,
    LoginResponse,
    MessageResponse,
    PasswordChangedResponse,
)
from .security import create_access_token, dummy_verify, password_problem, verify_password
from .service import get_by_employee_id, revoke_sessions, set_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse, summary="Sign in with an Employee ID")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    address = _client(request)

    # Checked before the password is verified, so a locked-out attacker cannot
    # keep spending a bcrypt hash per guess. That ordering is the difference
    # between a rate limit and a CPU amplifier. The `Retry-After` header is
    # added by the AppError handler in main.py, from `details`.
    try:
        ratelimit.guard(payload.employee_id, address)
    except ratelimit.RateLimitedError:
        logger.warning("login throttled for %s from %s", payload.employee_id, address)
        raise

    employee = get_by_employee_id(db, payload.employee_id)

    def reject(reason: str, message: str = GENERIC_AUTH_MESSAGE, code: str | None = None):
        ratelimit.note_failure(payload.employee_id, address)
        logger.info("login rejected (%s) for %s from %s", reason, payload.employee_id, address)
        return AuthenticationError(message, code=code)

    if employee is None:
        # Hash something anyway, so "no such ID" takes as long as "wrong
        # password". Without this the timing alone enumerates the directory.
        dummy_verify(payload.password)
        raise reject("unknown id")

    if not verify_password(payload.password, employee.password_hash):
        raise reject("bad password")

    if not employee.is_active:
        raise reject(
            "inactive",
            message=(
                "Account is inactive. Contact an administrator."
                if settings.DISCLOSE_INACTIVE
                else GENERIC_AUTH_MESSAGE
            ),
            code="ACCOUNT_INACTIVE" if settings.DISCLOSE_INACTIVE else None,
        )

    ratelimit.note_success(payload.employee_id, address)

    token, expires_at = create_access_token(
        subject=str(employee.id),
        employee_id=employee.employee_id,
        role=employee.role,
        token_version=employee.token_version,
    )
    logger.info("login accepted for %s (%s) from %s", employee.employee_id, employee.role, address)
    return LoginResponse(
        access_token=token,
        expires_at=expires_at,
        employee=EmployeeOut.from_model(employee),
    )


@router.get("/me", response_model=EmployeeOut, summary="The signed-in employee")
def me(employee: Employee = Depends(get_current_employee)) -> EmployeeOut:
    """
    Who the current token belongs to.

    The frontend calls this on load to revalidate a stored token, which is how
    a deactivated account loses the dashboard on the next page view rather
    than when its token eventually expires.
    """
    return EmployeeOut.from_model(employee)


@router.post("/logout", response_model=MessageResponse, summary="Sign out on this device")
def logout(employee: Employee = Depends(get_current_employee)) -> MessageResponse:
    """
    Sign out here.

    Deliberately does *not* bump ``token_version``: signing out of a shared
    terminal should not kick the same person off their phone. Use
    ``/logout-everywhere`` for that, which is a different intention and says
    so in its name.
    """
    logger.info("logout for %s", employee.employee_id)
    return MessageResponse(message="Signed out.")


@router.post(
    "/logout-everywhere",
    response_model=MessageResponse,
    summary="End every session for this account",
)
def logout_everywhere(
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """
    End every session, on every device, including this one.

    What you reach for when a laptop goes missing. Increments the revocation
    counter, so every token already issued — including the one used to make
    this call — stops working on its next request.
    """
    revoke_sessions(db, employee)
    logger.info("all sessions revoked for %s (self-service)", employee.employee_id)
    return MessageResponse(message="Signed out on every device. Sign in again to continue.")


@router.post(
    "/change-password",
    response_model=PasswordChangedResponse,
    summary="Change your own password",
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> PasswordChangedResponse:
    address = _client(request)
    # Rate limited too: an attacker with a stolen token would otherwise get
    # unlimited guesses at the current password in order to change it.
    ratelimit.guard(employee.employee_id, address)

    if not verify_password(payload.current_password, employee.password_hash):
        ratelimit.note_failure(employee.employee_id, address)
        raise AuthenticationError(
            "Your current password is incorrect.",
            code="INVALID_CURRENT_PASSWORD",
        )
    ratelimit.note_success(employee.employee_id, address)

    if payload.current_password == payload.new_password:
        raise ValidationError(
            "The new password must be different from the current one.",
            details={"fields": [{"field": "new_password", "message": "Unchanged."}]},
        )

    problem = password_problem(
        payload.new_password,
        employee_id=employee.employee_id,
        full_name=employee.full_name,
    )
    if problem:
        raise ValidationError(
            problem, details={"fields": [{"field": "new_password", "message": problem}]}
        )

    # Bumps token_version, so every other session ends here. The message below
    # is therefore true — an earlier version of it claimed this while the old
    # tokens carried on working.
    set_password(db, employee, payload.new_password)
    logger.info("password changed for %s (all sessions revoked)", employee.employee_id)

    # Including this one, so hand back a replacement rather than signing the
    # caller out of the device they are standing at.
    token, expires_at = create_access_token(
        subject=str(employee.id),
        employee_id=employee.employee_id,
        role=employee.role,
        token_version=employee.token_version,
    )
    return PasswordChangedResponse(
        message="Password changed. Every other session has been signed out.",
        access_token=token,
        expires_at=expires_at,
    )


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"
