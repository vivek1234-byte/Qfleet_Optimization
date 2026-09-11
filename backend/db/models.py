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

    # The job title within the department — "Fleet Manager", "Bunker Analyst".
    # Distinct from role, which is a permission level, not a job.
    designation: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")

    # Optional: an operator may not issue addresses to every rank on board.
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)

    # Stamped on each successful sign-in. Nullable because a freshly created
    # account has never signed in — the UI shows "Never" rather than a fake date.
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Deactivation instead of deletion, so an account can be revoked without
    # losing who it was.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Bumped whenever every existing session for this person must stop working:
    # a password change, or an administrator forcing a sign-out. The number is
    # copied into each token as `tv` and compared on every request, which is
    # what turns a stateless token into a revocable one without a session
    # table. Without it, "change your password" does not end a stolen session —
    # the thief keeps working until the token expires on its own.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

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


class AuditLog(Base):
    """
    An administrator action worth keeping a record of.

    Deliberately append-only and self-contained: it stores the *text* of who
    did what to whom, not foreign keys, so deleting an employee never erases
    the history of what was done to their account. No password material is ever
    written here — the recording sites pass a human summary, never a payload.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, server_default=func.now(), index=True
    )
    # Who did it — the acting administrator's Employee ID, copied in as text.
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    # What they did — a short verb phrase, e.g. "Created employee".
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    # Who it was done to — the target's Employee ID, or "" for fleet-wide acts.
    target: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    # How it went — "Success" or a short failure reason.
    result: Mapped[str] = mapped_column(String(120), nullable=False, default="Success")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AuditLog {self.created_at} {self.actor} {self.action} {self.target}>"


def normalise_employee_id(raw: str) -> str:
    """
    Canonical form of an employee ID: trimmed, collapsed, upper-cased.

    Applied on both write and lookup. Doing it in one function rather than at
    each call site is what stops "EMP001" and "emp001 " becoming two accounts.
    """
    return " ".join(str(raw or "").split()).upper()
