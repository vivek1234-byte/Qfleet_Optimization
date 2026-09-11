"""
Declarative base.

Kept in its own module so Alembic can import the metadata without pulling in
the engine, which would otherwise try to open a database just to generate a
migration.
"""
from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Explicit constraint names. Without them SQLite invents anonymous names and a
# later migration that wants to drop a constraint has nothing to refer to —
# the classic "cannot ALTER TABLE" wall people hit six months in.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
