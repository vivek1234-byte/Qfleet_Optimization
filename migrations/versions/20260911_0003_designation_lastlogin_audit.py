"""Add designation + last_login to employees, and the audit_log table.

Revision ID: 0003_designation_audit
Revises: 0002_token_version
Create Date: 2026-09-11

All additive. ``designation`` and ``last_login`` are new columns with safe
defaults — existing rows get an empty designation and a NULL last_login
("never signed in"), so no data is touched and nobody is signed out. The
``audit_log`` table is new and starts empty; it records administrator actions
going forward and holds no password material.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_designation_audit"
down_revision: Union[str, None] = "0002_token_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode: SQLite rewrites the table rather than ALTERing in place.
    # Harmless on PostgreSQL, required on the default SQLite database.
    with op.batch_alter_table("employees") as batch:
        batch.add_column(
            sa.Column("designation", sa.String(length=80), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("last_login", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("result", sa.String(length=120), nullable=False, server_default="Success"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("last_login")
        batch.drop_column("designation")
