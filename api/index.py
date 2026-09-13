"""
Vercel Serverless Function entry point.

Wraps the FastAPI app so Vercel can serve it as a serverless function.
On each cold start: migrates the DB schema and seeds demo accounts into
a /tmp SQLite database (Vercel's only writable directory).
"""
import os
import sys
from pathlib import Path

# ---- Paths ----------------------------------------------------------------
# Vercel unpacks the project at a read-only location. The backend modules need
# to be importable, and the database must live in /tmp (the only writable dir).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

for p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Point SQLite at /tmp so it survives within a single function instance.
# Data will be lost on cold starts — acceptable for a demo.
TMP_DB = "/tmp/qfleet.db"
os.environ.setdefault("QGF_DATABASE_URL", f"sqlite:///{TMP_DB}")

# Allow the Vercel frontend origin for CORS.
os.environ.setdefault(
    "QGF_CORS_ORIGINS",
    "https://qfleetoptimization.vercel.app,http://localhost:5173,http://127.0.0.1:5173",
)

# Seed demo accounts automatically on every cold start.
os.environ.setdefault("QGF_SEED_DEMO", "true")

# Use an ephemeral JWT secret if none is set (sessions won't survive cold starts).
if not os.environ.get("QGF_JWT_SECRET"):
    import secrets
    os.environ["QGF_JWT_SECRET"] = secrets.token_urlsafe(48)

# ---- Bootstrap the database on cold start ---------------------------------
def _bootstrap_db():
    """Run migrations + seed on cold start if DB doesn't exist yet."""
    db_path = Path(TMP_DB)
    if db_path.exists() and db_path.stat().st_size > 0:
        return  # Already initialised in this instance

    # Run alembic migrations
    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    alembic_ini = PROJECT_ROOT / "alembic.ini"
    alembic_cfg = AlembicConfig(str(alembic_ini))
    alembic_cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{TMP_DB}")
    alembic_command.upgrade(alembic_cfg, "head")

    # Seed demo accounts
    from db.session import get_engine, session_scope
    from db.models import Employee, Role, normalise_employee_id
    from auth.security import hash_password

    DEMO_EMPLOYEES = [
        ("ADMIN001", "Fleet Administrator", "ADMIN", "Operations", "Fleet Administrator", "admin@qfleet.local", "Admin@12345"),
        ("ADMIN002", "Rohit Deshmukh", "ADMIN", "Fleet Management", "Fleet Manager", "rohit.d@qfleet.local", "Admin@12345"),
        ("EMP001", "Priya Nair", "EMPLOYEE", "Voyage Planning", "Voyage Planner", "priya.nair@qfleet.local", "Emp@12345"),
        ("EMP002", "Arjun Menon", "EMPLOYEE", "Bunkering", "Bunker Analyst", "arjun.menon@qfleet.local", "Emp@12345"),
        ("EMP003", "Sara Iqbal", "EMPLOYEE", "Compliance", "Compliance Officer", "sara.iqbal@qfleet.local", "Emp@12345"),
    ]

    with session_scope() as session:
        for emp_id, name, role, dept, designation, email, password in DEMO_EMPLOYEES:
            norm_id = normalise_employee_id(emp_id)
            if session.query(Employee).filter_by(employee_id=norm_id).first():
                continue
            emp = Employee(
                employee_id=norm_id,
                full_name=name,
                role=Role(role),
                department=dept,
                designation=designation,
                email=email,
                password_hash=hash_password(password),
                is_active=True,
            )
            session.add(emp)

try:
    _bootstrap_db()
except Exception as exc:
    print(f"[vercel cold-start] DB bootstrap warning: {exc}", file=sys.stderr)

# ---- Import the FastAPI app -----------------------------------------------
from backend.main import app

# Vercel looks for `app` in this module — that's all it needs.
