"""
Employee administration: ``/api/admin/employees``.

Every route in this module carries ``Depends(require_admin)``, declared on the
router itself so a route added later cannot be left unprotected by
forgetting it. That dependency is the authorization boundary — the admin
navigation being hidden in the frontend is presentation, and presentation is
not a permission check.

No response here contains ``password_hash``. Everything is serialised through
``EmployeeOut``, which lists its fields by name.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.orm import Session

from auth.deps import require_admin
from auth.schemas import (
    AuditEntryOut,
    AuditListResponse,
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeOut,
    EmployeeUpdate,
    MessageResponse,
    PasswordResetRequest,
)
from auth.security import password_problem
from auth.service import (
    count_audit,
    create_employee,
    delete_employee,
    list_audit,
    list_employees,
    record_audit,
    require_by_pk,
    revoke_sessions,
    set_password,
    update_employee,
)
from core.errors import ValidationError
from db.models import Employee, Role
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["Administration"],
    dependencies=[Depends(require_admin)],
)


@router.get(
    "/employees",
    response_model=EmployeeListResponse,
    summary="List and search employees",
)
def list_all(
    search: str = Query("", max_length=120, description="Matches ID, name, department or email"),
    role: Optional[str] = Query(None, description="ADMIN or EMPLOYEE"),
    active: Optional[bool] = Query(None, description="Filter by account status"),
    db: Session = Depends(get_db),
) -> EmployeeListResponse:
    if role is not None and role.strip().upper() not in Role.values():
        raise ValidationError(f"Role must be one of: {', '.join(Role.values())}.")

    rows = list_employees(db, search=search, role=role, active=active)
    # Totals describe the filtered set, so the header figures always match the
    # table underneath them rather than describing some other population.
    active_count = sum(1 for row in rows if row.is_active)
    return EmployeeListResponse(
        employees=[EmployeeOut.from_model(row) for row in rows],
        total=len(rows),
        active=active_count,
        admins=sum(1 for row in rows if row.role == Role.ADMIN.value),
        inactive=len(rows) - active_count,
    )


@router.get("/employees/{pk}", response_model=EmployeeOut, summary="One employee")
def get_one(pk: int = Path(..., ge=1), db: Session = Depends(get_db)) -> EmployeeOut:
    return EmployeeOut.from_model(require_by_pk(db, pk))


@router.post(
    "/employees",
    response_model=EmployeeOut,
    status_code=201,
    summary="Add an employee",
)
def create(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> EmployeeOut:
    # The schema already rejected the universally weak passwords; this catches
    # the ones that are only weak for *this* person — their own name or ID,
    # which is the single most common choice in any staff system.
    _reject_weak(payload.password, payload.employee_id, payload.full_name)

    employee = create_employee(
        db,
        employee_id=payload.employee_id,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
        department=payload.department,
        designation=payload.designation,
        email=payload.email,
        is_active=payload.is_active,
    )
    logger.info("%s created employee %s (%s)", actor.employee_id, employee.employee_id, employee.role)
    record_audit(db, actor=actor.employee_id, action="Created employee", target=employee.employee_id)
    return EmployeeOut.from_model(employee)


@router.put("/employees/{pk}", response_model=EmployeeOut, summary="Edit an employee")
def update(
    payload: EmployeeUpdate,
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> EmployeeOut:
    employee = require_by_pk(db, pk)

    changes = payload.model_dump(exclude_unset=True)

    # An administrator editing themselves cannot remove their own access; the
    # UI disables it, and this is the check that actually holds.
    if employee.id == actor.id:
        if changes.get("is_active") is False:
            raise ValidationError("You cannot deactivate your own account.")
        if changes.get("role") is not None and changes["role"] != Role.ADMIN.value:
            raise ValidationError("You cannot remove your own administrator role.")

    employee = update_employee(db, employee, changes)
    logger.info("%s updated employee %s", actor.employee_id, employee.employee_id)
    record_audit(db, actor=actor.employee_id, action="Edited employee", target=employee.employee_id)
    return EmployeeOut.from_model(employee)


@router.post(
    "/employees/{pk}/activate",
    response_model=EmployeeOut,
    summary="Reactivate an account",
)
def activate(
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> EmployeeOut:
    employee = update_employee(db, require_by_pk(db, pk), {"is_active": True})
    logger.info("%s activated %s", actor.employee_id, employee.employee_id)
    record_audit(db, actor=actor.employee_id, action="Reactivated account", target=employee.employee_id)
    return EmployeeOut.from_model(employee)


@router.post(
    "/employees/{pk}/deactivate",
    response_model=EmployeeOut,
    summary="Revoke an account without deleting it",
)
def deactivate(
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> EmployeeOut:
    employee = require_by_pk(db, pk)
    if employee.id == actor.id:
        raise ValidationError("You cannot deactivate your own account.")
    employee = update_employee(db, employee, {"is_active": False})
    logger.info("%s deactivated %s", actor.employee_id, employee.employee_id)
    record_audit(db, actor=actor.employee_id, action="Deactivated account", target=employee.employee_id)
    return EmployeeOut.from_model(employee)


@router.post(
    "/employees/{pk}/reset-password",
    response_model=MessageResponse,
    summary="Set a new password for an employee",
)
def reset_password(
    payload: PasswordResetRequest,
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> MessageResponse:
    employee = require_by_pk(db, pk)
    _reject_weak(payload.new_password, employee.employee_id, employee.full_name)

    # set_password bumps token_version, so a reset also throws the account off
    # every device it is currently signed in on. That is the behaviour you want
    # when the reason for the reset is "we think someone else has it".
    set_password(db, employee, payload.new_password)
    logger.info(
        "%s reset the password for %s (all sessions revoked)",
        actor.employee_id,
        employee.employee_id,
    )
    record_audit(db, actor=actor.employee_id, action="Reset password", target=employee.employee_id)
    return MessageResponse(
        message=(
            f"Password reset for {employee.employee_id} and all their sessions ended. "
            "Give the new password to them over a trusted channel."
        )
    )


@router.post(
    "/employees/{pk}/revoke-sessions",
    response_model=MessageResponse,
    summary="Sign an employee out of every device",
)
def revoke(
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> MessageResponse:
    """
    End every session without changing the password or disabling the account.

    The middle option between "do nothing" and "deactivate": a lost phone, a
    shared terminal someone forgot to sign out of, a contractor finishing a
    shift. They can sign straight back in with the password they already have.
    """
    employee = require_by_pk(db, pk)
    revoke_sessions(db, employee)
    logger.info("%s revoked all sessions for %s", actor.employee_id, employee.employee_id)
    record_audit(db, actor=actor.employee_id, action="Signed out everywhere", target=employee.employee_id)
    return MessageResponse(message=f"{employee.employee_id} has been signed out everywhere.")


def _reject_weak(password: str, employee_id: str, full_name: str) -> None:
    problem = password_problem(password, employee_id=employee_id, full_name=full_name)
    if problem:
        raise ValidationError(
            problem, details={"fields": [{"field": "password", "message": problem}]}
        )


@router.delete(
    "/employees/{pk}",
    response_model=MessageResponse,
    summary="Delete an employee",
)
def remove(
    pk: int = Path(..., ge=1),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_admin),
) -> MessageResponse:
    employee = require_by_pk(db, pk)
    if employee.id == actor.id:
        raise ValidationError("You cannot delete your own account.")
    employee_id = employee.employee_id
    delete_employee(db, employee)
    logger.info("%s deleted employee %s", actor.employee_id, employee_id)
    record_audit(db, actor=actor.employee_id, action="Deleted employee", target=employee_id)
    return MessageResponse(message=f"{employee_id} deleted.")


@router.get("/audit", response_model=AuditListResponse, summary="Recent administrator actions")
def audit(
    limit: int = Query(100, ge=1, le=500, description="How many recent entries to return"),
    db: Session = Depends(get_db),
) -> AuditListResponse:
    """
    The administrator action log, newest first.

    Admin-only like everything else on this router. It records who did what to
    whom and when — never a password or a token, because the recording sites
    pass a summary line, not a payload.
    """
    rows = list_audit(db, limit=limit)
    return AuditListResponse(
        entries=[AuditEntryOut.model_validate(row, from_attributes=True) for row in rows],
        total=count_audit(db),
    )
