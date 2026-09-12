"""Add per-employee module permissions.

Revision ID: 0004_permissions
Revises: 0003_designation_audit
Create Date: 2026-09-12

Additive and non-destructive. Every existing row gets ``permissions = ''``,
which ``auth.permissions.allowed_modules`` reads as "the role default" — the
exact set of screens employees could already open. Nobody loses access on
upgrade and nobody is signed out; an administrator restricts an individual
afterwards by saving an explicit list.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_permissions"
down_revision: Union[str, None] = "0003_designation_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode: SQLite rewrites the table rather than ALTERing in place.
    # Harmless on PostgreSQL, required on the default SQLite database.
    with op.batch_alter_table("employees") as batch:
        batch.add_column(
            sa.Column("permissions", sa.String(length=512), nullable=False, server_default="")
        )


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("permissions")
