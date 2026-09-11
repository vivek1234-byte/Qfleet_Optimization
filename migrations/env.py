"""
Alembic environment.

The database URL comes from the application settings — that is,
``QGF_DATABASE_URL`` or the SQLite default — rather than from alembic.ini, so
a connection string carrying a password is never committed and migrations
always run against exactly the database the API will use.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config import settings  # noqa: E402
from db.base import Base  # noqa: E402
import db.models  # noqa: E402,F401  (imported for its side effect: registering tables)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("%", "%%"))

target_metadata = Base.metadata

# SQLite cannot ALTER a column in place. Batch mode rewrites the table
# instead, which is what makes later migrations possible at all on the
# default database.
RENDER_AS_BATCH = settings.DATABASE_URL.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=RENDER_AS_BATCH,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=RENDER_AS_BATCH,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
