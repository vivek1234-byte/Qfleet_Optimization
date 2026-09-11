"""Add employees.token_version, so sessions can actually be revoked.

Revision ID: 0002_token_version
Revises: 0001_employees
Create Date: 2026-09-11

Session tokens are stateless, which means nothing on the server can invalidate
one before it expires. This column is the counter that fixes that: it is
copied into each token as `tv`, compared on every authenticated request, and
incremented whenever every existing session must stop working — a password
change, or an administrator forcing a sign-out.

Existing rows start at 0, matching the default for new rows, so tokens issued
before this migration keep working until they expire. That is deliberate:
bumping everyone to 1 here would sign out the whole company at deploy time.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_token_version"
down_revision: Union[str, None] = "0001_employees"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode: SQLite cannot ALTER a column in place, so alembic rewrites
    # the table. Harmless on PostgreSQL, required on the default database.
    with op.batch_alter_table("employees") as batch:
        batch.add_column(
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("employees") as batch:
        batch.drop_column("token_version")
