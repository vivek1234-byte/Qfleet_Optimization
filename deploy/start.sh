#!/usr/bin/env sh
#
# Container entrypoint: bring the schema up to date, optionally seed the demo
# accounts, then serve.
#
# Migrations run on every boot rather than as a separate release step because
# the free tiers this is aimed at have no release phase — the container starts
# and that is the only hook there is. `alembic upgrade head` is a no-op when
# the schema is already current, so this costs nothing after the first boot.
set -e

echo "→ migrating database"
alembic upgrade head

# Demo accounts are OFF unless asked for. Their passwords are printed in this
# repository, so seeding a public deployment hands an administrator login to
# anyone who can read it. `manage.py seed` refuses outside development for
# exactly that reason; QGF_SEED_DEMO=true is the deliberate override, and it
# skips any account that already exists, so restarts do not duplicate anyone.
if [ "${QGF_SEED_DEMO:-false}" = "true" ]; then
  echo "→ seeding demo accounts (existing accounts are left alone)"
  python -m backend.manage seed --force
fi

# One worker. The free tiers hold 512 MB, and the numeric stack is ~200 MB
# resident per worker — a second one would not fit, and the solver is a
# two-second CPU burst rather than a concurrency problem.
echo "→ serving on :${PORT:-8000}"
exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
