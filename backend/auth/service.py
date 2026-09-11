"""
Database operations behind sign-in and employee administration.

Kept out of the routers so the rules — who may be deactivated, what makes an
Employee ID a duplicate, how a password is changed — exist in one place and
are testable without an HTTP client.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.errors import ConflictError, NotFoundError, ValidationError
from db.models import AuditLog, Employee, Role, normalise_employee_id

from .security import hash_password


def get_by_employee_id(db: Session, employee_id: str) -> Optional[Employee]:
    normalised = normalise_employee_id(employee_id)
    if not normalised:
        return None
    return db.scalar(select(Employee).where(Employee.employee_id == normalised))


def get_by_pk(db: Session, pk: int) -> Optional[Employee]:
    return db.get(Employee, pk)


def require_by_pk(db: Session, pk: int) -> Employee:
    employee = get_by_pk(db, pk)
    if employee is None:
        raise NotFoundError(f"No employee with id {pk}.")
    return employee


def list_employees(
    db: Session,
    *,
    search: str = "",
    role: Optional[str] = None,
    active: Optional[bool] = None,
) -> Sequence[Employee]:
    """
    Every employee, newest-looking first by ID, filtered as asked.

    ``search`` matches Employee ID, full name or department, case-insensitively
    and anywhere in the value — an operator looking for "nair" should not have
    to know whether that is a first or last name.
    """
    stmt = select(Employee)

    term = " ".join(str(search or "").split())
    if term:
        pattern = f"%{term.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Employee.employee_id).like(pattern),
                func.lower(Employee.full_name).like(pattern),
                func.lower(Employee.department).like(pattern),
                func.lower(func.coalesce(Employee.email, "")).like(pattern),
            )
        )

    if role:
        stmt = stmt.where(Employee.role == role.strip().upper())
    if active is not None:
        stmt = stmt.where(Employee.is_active.is_(active))

    stmt = stmt.order_by(Employee.employee_id.asc())
    return list(db.scalars(stmt).all())


def count_active_admins(db: Session, *, excluding_pk: Optional[int] = None) -> int:
    stmt = select(func.count()).select_from(Employee).where(
        Employee.role == Role.ADMIN.value, Employee.is_active.is_(True)
    )
    if excluding_pk is not None:
        stmt = stmt.where(Employee.id != excluding_pk)
    return int(db.scalar(stmt) or 0)


def create_employee(
    db: Session,
    *,
    employee_id: str,
    full_name: str,
    password: str,
    role: str = Role.EMPLOYEE.value,
    department: str = "",
    designation: str = "",
    email: Optional[str] = None,
    is_active: bool = True,
) -> Employee:
    normalised = normalise_employee_id(employee_id)

    # Checked here for a clean message, and again by the unique index below —
    # two admins creating EMP007 at the same moment would both pass this check.
    if get_by_employee_id(db, normalised) is not None:
        raise ConflictError(
            f"Employee ID {normalised} is already in use.",
            details={"fields": [{"field": "employee_id", "message": "Already in use."}]},
        )

    employee = Employee(
        employee_id=normalised,
        full_name=full_name,
        password_hash=hash_password(password),
        role=role,
        department=department or "",
        designation=designation or "",
        email=email,
        is_active=is_active,
    )
    db.add(employee)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Employee ID {normalised} is already in use.",
            details={"fields": [{"field": "employee_id", "message": "Already in use."}]},
        ) from exc
    db.refresh(employee)
    return employee


def update_employee(db: Session, employee: Employee, changes: dict) -> Employee:
    """
    Apply a partial update.

    Two rules the UI must not be the only thing enforcing:
    the last active administrator cannot be demoted, and cannot be
    deactivated. Either would lock everyone out of employee management with no
    way back in short of the command line.
    """
    becoming_non_admin = (
        changes.get("role") is not None
        and changes["role"] != Role.ADMIN.value
        and employee.role == Role.ADMIN.value
    )
    becoming_inactive = changes.get("is_active") is False and employee.is_active

    if (becoming_non_admin or becoming_inactive) and employee.role == Role.ADMIN.value:
        if count_active_admins(db, excluding_pk=employee.id) == 0:
            raise ValidationError(
                "This is the last active administrator. Promote another administrator first.",
                details={"fields": [{"field": "role", "message": "Last active administrator."}]},
            )

    for field in ("full_name", "department", "designation", "role", "email", "is_active"):
        if field in changes and changes[field] is not None:
            setattr(employee, field, changes[field])
    # `email` is the one field that can legitimately be cleared.
    if "email" in changes and changes["email"] is None:
        employee.email = None

    db.commit()
    db.refresh(employee)
    return employee


def set_password(db: Session, employee: Employee, new_password: str) -> Employee:
    """
    Replace the password and end every session that used the old one.

    The second half is not optional. Someone changing their password because
    they think it was stolen is doing it to lock the thief out; leaving the
    thief's token working for another twelve hours defeats the entire point of
    the action.
    """
    employee.password_hash = hash_password(new_password)
    employee.token_version = int(employee.token_version or 0) + 1
    db.commit()
    db.refresh(employee)
    return employee


def revoke_sessions(db: Session, employee: Employee) -> Employee:
    """End every session for this employee without touching their password."""
    employee.token_version = int(employee.token_version or 0) + 1
    db.commit()
    db.refresh(employee)
    return employee


def delete_employee(db: Session, employee: Employee) -> None:
    if employee.role == Role.ADMIN.value and count_active_admins(db, excluding_pk=employee.id) == 0:
        raise ValidationError(
            "This is the last active administrator and cannot be deleted."
        )
    db.delete(employee)
    db.commit()


def record_login(db: Session, employee: Employee) -> Employee:
    """Stamp the successful sign-in. Cheap, and the only per-login write."""
    employee.last_login = datetime.now(timezone.utc)
    db.commit()
    db.refresh(employee)
    return employee


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def record_audit(
    db: Session,
    *,
    actor: str,
    action: str,
    target: str = "",
    result: str = "Success",
) -> None:
    """
    Append one line to the administrator action log.

    Best-effort: an audit write must never be the thing that fails an
    otherwise-successful administrative action, so a problem here is swallowed
    rather than rolled back over the change it was recording.
    """
    try:
        db.add(AuditLog(actor=actor, action=action, target=target or "", result=result))
        db.commit()
    except Exception:  # pragma: no cover - the log is not load-bearing
        db.rollback()


def list_audit(db: Session, *, limit: int = 100) -> Sequence[AuditLog]:
    """The most recent administrator actions, newest first."""
    limit = max(1, min(int(limit), 500))
    stmt = select(AuditLog).order_by(desc(AuditLog.created_at), desc(AuditLog.id)).limit(limit)
    return list(db.scalars(stmt).all())


def count_audit(db: Session) -> int:
    return int(db.scalar(select(func.count()).select_from(AuditLog)) or 0)
