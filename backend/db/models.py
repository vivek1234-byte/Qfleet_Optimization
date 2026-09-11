"""
ORM models.

One table, ``employees``. Everything the login screen and the admin dashboard
need is here; nothing else in the platform stores rows.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Role(str, enum.Enum):
    """
    Who can do what.

    Deliberately two values. Every extra role is an extra set of checks to get
    wrong, and the requirement is a fleet operations tool with administrators
    and everyone else. Adding a third is a migration plus one entry in
    ``require_roles``.
    """

    ADMIN = "ADMIN"
    EMPLOYEE = "EMPLOYEE"

    @classmethod
    def values(cls) -> list[str]:
        return [role.value for role in cls]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Employee(Base):
    """
    A person who can sign in.

    ``password_hash`` is a bcrypt digest and is never serialised: the response
    schemas in ``auth.schemas`` list their fields explicitly rather than
    dumping the model, so a hash cannot leak by someone adding a column later.
    """

    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'EMPLOYEE')",
            name="role_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # The login identifier. Stored upper-cased and trimmed (see
    # ``normalise_employee_id``) so "emp001" and "EMP001" are the same person
    # and the unique index actually holds.
    employee_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.EMPLOYEE.value)
    department: Mapped[str] = mapped_column(String(80), nullable=False, default="")

    # Optional: an operator may not issue addresses to every rank on board.
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    # Deactivation instead of deletion, so an account can be revoked without
    # losing who it was.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Employee {self.employee_id} {self.role} active={self.is_active}>"


def normalise_employee_id(raw: str) -> str:
    """
    Canonical form of an employee ID: trimmed, collapsed, upper-cased.

    Applied on both write and lookup. Doing it in one function rather than at
    each call site is what stops "EMP001" and "emp001 " becoming two accounts.
    """
    return " ".join(str(raw or "").split()).upper()
