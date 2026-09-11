"""
Request and response shapes for authentication and employee administration.

The response models list their fields **explicitly**. None of them is built
with ``from_attributes`` over a blanket field set, and none has
``password_hash``. That is the mechanism that keeps the hash out of the API:
adding a column to the model later cannot leak it, because nothing serialises
the model itself.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config import settings
from db.models import Employee, Role, normalise_employee_id

from .security import password_problem

# Letters, digits, dash, underscore. Deliberately permissive about the shape
# of the ID itself (operators number people in all sorts of ways) but strict
# about characters, so nothing exotic reaches a query or a log line.
EMPLOYEE_ID_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def _validate_employee_id(value: str) -> str:
    normalised = normalise_employee_id(value)
    if not normalised:
        raise ValueError("Employee ID is required.")
    if not EMPLOYEE_ID_PATTERN.match(normalised):
        raise ValueError(
            "Employee ID must be 2-32 characters: letters, digits, dashes or underscores."
        )
    return normalised


def _validate_password(value: str) -> str:
    """
    Length, plus the checks a length rule misses.

    ``password_problem`` also knows how to reject a password that is the
    employee's own name or ID, but a field validator cannot see the other
    fields — so the routes call it again with that context. This catches the
    universal cases early and cheaply.
    """
    problem = password_problem(value)
    if problem:
        raise ValueError(problem)
    return value


def _validate_optional_email(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if not EMAIL_PATTERN.match(trimmed):
        raise ValueError("That does not look like an email address.")
    return trimmed.lower()


# --------------------------------------------------------------------------
# Sign-in
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str = Field(..., description="Employee ID, e.g. EMP001")
    password: str = Field(..., description="Account password")

    @field_validator("employee_id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        # No format validation on the login path. A rejected *shape* would
        # leak which IDs are plausible; an unknown ID must fail exactly the
        # way a wrong password does.
        cleaned = normalise_employee_id(value)
        if not cleaned:
            raise ValueError("Employee ID is required.")
        return cleaned[:64]

    @field_validator("password")
    @classmethod
    def _require_password(cls, value: str) -> str:
        if not value:
            raise ValueError("Password is required.")
        return value


class EmployeeOut(BaseModel):
    """
    A person, as the API describes them. No password material of any kind.
    """

    id: int
    employee_id: str
    full_name: str
    role: str
    department: str
    email: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, employee: Employee) -> "EmployeeOut":
        return cls(
            id=employee.id,
            employee_id=employee.employee_id,
            full_name=employee.full_name,
            role=employee.role,
            department=employee.department or "",
            email=employee.email,
            is_active=employee.is_active,
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    employee: EmployeeOut


class MessageResponse(BaseModel):
    message: str


class PasswordChangedResponse(BaseModel):
    """
    Changing a password revokes every token, including the one that made the
    call — so a replacement comes back with the confirmation. Without it the
    caller would be signed out of the very device they just used, which reads
    as a bug rather than as security.
    """

    message: str
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new(cls, value: str) -> str:
        return _validate_password(value)


# --------------------------------------------------------------------------
# Employee administration
# --------------------------------------------------------------------------
class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: str
    full_name: str
    department: str = ""
    role: str = Role.EMPLOYEE.value
    email: Optional[str] = None
    password: str
    is_active: bool = True

    @field_validator("employee_id")
    @classmethod
    def _clean_id(cls, value: str) -> str:
        return _validate_employee_id(value)

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split())
        if len(cleaned) < 2:
            raise ValueError("Full name is required.")
        if len(cleaned) > 120:
            raise ValueError("Full name must be at most 120 characters.")
        return cleaned

    @field_validator("department")
    @classmethod
    def _clean_department(cls, value: str) -> str:
        cleaned = " ".join(str(value or "").split())
        if len(cleaned) > 80:
            raise ValueError("Department must be at most 80 characters.")
        return cleaned

    @field_validator("role")
    @classmethod
    def _clean_role(cls, value: str) -> str:
        cleaned = str(value or "").strip().upper()
        if cleaned not in Role.values():
            raise ValueError(f"Role must be one of: {', '.join(Role.values())}.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: Optional[str]) -> Optional[str]:
        return _validate_optional_email(value)

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class EmployeeUpdate(BaseModel):
    """
    Partial update. Every field is optional; only what is sent is changed.

    There is no ``password`` here on purpose — resetting a password is its own
    endpoint, so it cannot happen as a side effect of editing a department.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: Optional[str] = None
    department: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("full_name")
    @classmethod
    def _clean_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return EmployeeCreate._clean_name(value)

    @field_validator("department")
    @classmethod
    def _clean_department(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return EmployeeCreate._clean_department(value)

    @field_validator("role")
    @classmethod
    def _clean_role(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return EmployeeCreate._clean_role(value)

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: Optional[str]) -> Optional[str]:
        return _validate_optional_email(value)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check(cls, value: str) -> str:
        return _validate_password(value)


class EmployeeListResponse(BaseModel):
    employees: List[EmployeeOut]
    total: int
    active: int
    admins: int
