"""Renumber employee IDs by role: ADMIN001.. for administrators, EMP001.. for staff.

Revision ID: 0005_renumber_ids
Revises: 0004_permissions
Create Date: 2026-09-12

The seed script already issues IDs this way; databases created before that
change carry the old flat ``EMP001..EMPnnn`` series where an administrator and
an employee are indistinguishable by their login identifier. This brings an
existing database onto the convention.

What it does, per role, ordered by primary key so the oldest account keeps the
lowest number: administrators become ``ADMIN001``, ``ADMIN002``, …; everyone
else becomes ``EMP001``, ``EMP002``, …

Three things worth knowing before running it:

* **Login identifiers change.** Anyone signing in with an old ID has to use
  the new one. Every session is ended (``token_version`` is incremented) so
  nobody stays signed in under an identifier that no longer exists.
* **Passwords are untouched.** This migration cannot read them and does not
  try; ``manage.py passwd`` is still the only way to set one.
* **The audit log is left alone on purpose.** Its rows record the ID that was
  in force when the action happened. Rewriting them would make the log say
  something that was never true, which is the one thing an audit log must not
  do. A line is added recording the renumbering itself.

The renaming happens via a temporary prefix. Going straight from ``EMP002`` to
``EMP001`` while some other row still holds ``EMP001`` would collide with the
unique index mid-pass, and the order that avoids it depends on the data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_renumber_ids"
down_revision: Union[str, None] = "0004_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TMP = "__MIGRATING__"


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(
        sa.text("SELECT id, employee_id, role FROM employees ORDER BY id")
    ).fetchall()
    if not rows:
        return

    counters = {"ADMIN": 0, "EMPLOYEE": 0}
    planned: list[tuple[int, str, str]] = []  # (pk, old_id, new_id)

    for pk, old_id, role in rows:
        prefix = "ADMIN" if role == "ADMIN" else "EMP"
        key = "ADMIN" if role == "ADMIN" else "EMPLOYEE"
        counters[key] += 1
        new_id = f"{prefix}{counters[key]:03d}"
        if new_id != old_id:
            planned.append((pk, old_id, new_id))

    if not planned:
        return

    # Two passes through a temporary prefix: the target of one rename is very
    # often the current value of another row, and the unique index does not
    # care that the collision is transient.
    for pk, _old, new_id in planned:
        bind.execute(
            sa.text("UPDATE employees SET employee_id = :tmp WHERE id = :pk"),
            {"tmp": f"{_TMP}{new_id}", "pk": pk},
        )
    for pk, _old, new_id in planned:
        bind.execute(
            sa.text(
                "UPDATE employees SET employee_id = :new, token_version = token_version + 1 "
                "WHERE id = :pk"
            ),
            {"new": new_id, "pk": pk},
        )

    # One audit line, so the change is visible to whoever wonders later why
    # their ID moved. Existing lines keep the IDs that were true at the time.
    summary = ", ".join(f"{old}->{new}" for _pk, old, new in planned)
    bind.execute(
        sa.text(
            "INSERT INTO audit_log (created_at, actor, action, target, result) "
            "VALUES (:created_at, :actor, :action, :target, :result)"
        ),
        {
            "created_at": datetime.now(timezone.utc),
            "actor": "migration 0005",
            "action": "Renumbered employee IDs by role",
            "target": summary[:490],
            "result": "success",
        },
    )


def downgrade() -> None:
    # The previous IDs were a flat series with no record of which row held
    # which number, so there is nothing faithful to restore. Renumbering back
    # into EMPnnn is done deliberately with `manage.py`, not implicitly here.
    raise NotImplementedError(
        "0005 renumbers login identifiers and cannot be reversed automatically. "
        "Rename accounts with `python -m backend.manage` if you need the old scheme."
    )
