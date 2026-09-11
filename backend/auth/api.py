"""
Sign-in routes: ``/api/auth/*``.

The one rule that shapes this module: **a failed sign-in must not reveal
whether the Employee ID exists.** That means the same message, the same
status code, and — via ``dummy_verify`` — roughly the same response time
whether the ID is unknown or the password is wrong. An error that says
"unknown Employee ID" turns a login form into a staff directory.

The one exception is a *disabled* account, which reports itself as inactive.
That does disclose the ID exists, and it is the right trade: someone whose
account was revoked needs to know to call an administrator rather than
retrying their password until they are locked out, and their ID is not a
secret from them. Operators who would rather not disclose even that can set
``QGF_DISCLOSE_INACTIVE=false``.
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from core.errors import AuthenticationError
from db.models import Employee
from db.session import get_db

from .deps import GENERIC_AUTH_MESSAGE, get_current_employee
from .schemas import (
    ChangePasswordRequest,
    EmployeeOut,
    LoginRequest,
    LoginResponse,
    MessageResponse,
)
from .security import create_access_token, dummy_verify, verify_password
from .service import get_by_employee_id, set_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

DISCLOSE_INACTIVE = os.getenv("QGF_DISCLOSE_INACTIVE", "true").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}


@router.post("/login", response_model=LoginResponse, summary="Sign in with an Employee ID")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    employee = get_by_employee_id(db, payload.employee_id)

    if employee is None:
        # Hash something anyway, so "no such ID" takes as long as "wrong
        # password". Without this the timing alone enumerates the directory.
        dummy_verify(payload.password)
        logger.info("login rejected (unknown id) from %s", _client(request))
        raise AuthenticationError(GENERIC_AUTH_MESSAGE)

    if not verify_password(payload.password, employee.password_hash):
        logger.info("login rejected (bad password) for %s", employee.employee_id)
        raise AuthenticationError(GENERIC_AUTH_MESSAGE)

    if not employee.is_active:
        logger.info("login rejected (inactive) for %s", employee.employee_id)
        raise AuthenticationError(
            "Account is inactive. Contact an administrator."
            if DISCLOSE_INACTIVE
            else GENERIC_AUTH_MESSAGE,
            code="ACCOUNT_INACTIVE" if DISCLOSE_INACTIVE else None,
        )

    token, expires_at = create_access_token(
        subject=str(employee.id),
        employee_id=employee.employee_id,
        role=employee.role,
    )
    logger.info("login accepted for %s (%s)", employee.employee_id, employee.role)
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


@router.post("/logout", response_model=MessageResponse, summary="Sign out")
def logout(employee: Employee = Depends(get_current_employee)) -> MessageResponse:
    """
    Sign out.

    Tokens are stateless, so the real work is the client discarding its copy;
    this endpoint exists so that happens against a server that has confirmed
    the session and logged it, and so a future token blocklist has somewhere
    to live. Do not tell the user a token has been revoked server-side — it
    has not.
    """
    logger.info("logout for %s", employee.employee_id)
    return MessageResponse(message="Signed out.")


@router.post(
    "/change-password",
    response_model=MessageResponse,
    summary="Change your own password",
)
def change_password(
    payload: ChangePasswordRequest,
    employee: Employee = Depends(get_current_employee),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.current_password, employee.password_hash):
        raise AuthenticationError(
            "Your current password is incorrect.",
            code="INVALID_CURRENT_PASSWORD",
        )
    if payload.current_password == payload.new_password:
        raise AuthenticationError(
            "The new password must be different from the current one.",
            status_code=422,
            code="PASSWORD_UNCHANGED",
        )
    set_password(db, employee, payload.new_password)
    logger.info("password changed for %s", employee.employee_id)
    return MessageResponse(message="Password changed. Sign in again on your other devices.")


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"
