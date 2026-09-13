"""
Vercel Serverless Function entry point.

Wraps the FastAPI app so Vercel can serve it as a serverless function.
On each cold start: creates the DB schema directly (no alembic — too slow)
and seeds demo accounts with pre-computed password hashes (no bcrypt at
runtime) into a /tmp SQLite database.
"""
import os
import sys
from pathlib import Path

# ---- Paths ----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"

for p in (str(PROJECT_ROOT), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Point SQLite at /tmp so it's writable on Vercel's read-only filesystem.
TMP_DB = "/tmp/qfleet.db"
os.environ.setdefault("QGF_DATABASE_URL", f"sqlite:///{TMP_DB}")

# CORS: allow the Vercel frontend.
os.environ.setdefault(
    "QGF_CORS_ORIGINS",
    "https://qfleetoptimization.vercel.app,http://localhost:5173,http://127.0.0.1:5173",
)

# Ephemeral JWT secret (sessions won't survive cold starts — fine for demo).
if not os.environ.get("QGF_JWT_SECRET"):
    import secrets
    os.environ["QGF_JWT_SECRET"] = secrets.token_urlsafe(48)


# ---- Fast DB bootstrap (no alembic, pre-computed hashes) ------------------
def _bootstrap_db():
    """Create tables + seed demo users. Runs in <200ms."""
    db_path = Path(TMP_DB)
    if db_path.exists() and db_path.stat().st_size > 0:
        return  # Already initialised in this warm instance

    from db.base import Base
    from db.models import Employee, Role, AuditLog  # noqa: F401 — registers tables
    from db.session import get_engine, get_sessionmaker

    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    # Pre-computed bcrypt hashes — avoids 2+ seconds of hashing per user.
    # Admin@12345 and Emp@12345 (cost factor 4, fast enough for demo).
    ADMIN_HASH = "$2b$04$ha6AbZJygfjr6kSFPdUyoOpOX8ZMkugp4S.kHPMQC8agWHt8Hx.Gu"
    EMP_HASH = "$2b$04$yd.1W8aMUnkRaaE6Km8WXuk.gp30W7KtaKcLnXNbYtOMvoIVUZWRu"

    DEMO_EMPLOYEES = [
        ("ADMIN001", "Fleet Administrator", Role.ADMIN, "Operations", "Fleet Administrator", "admin@qfleet.local", ADMIN_HASH),
        ("ADMIN002", "Rohit Deshmukh", Role.ADMIN, "Fleet Management", "Fleet Manager", "rohit.d@qfleet.local", ADMIN_HASH),
        ("EMP001", "Priya Nair", Role.EMPLOYEE, "Voyage Planning", "Voyage Planner", "priya.nair@qfleet.local", EMP_HASH),
        ("EMP002", "Arjun Menon", Role.EMPLOYEE, "Bunkering", "Bunker Analyst", "arjun.menon@qfleet.local", EMP_HASH),
        ("EMP003", "Sara Iqbal", Role.EMPLOYEE, "Compliance", "Compliance Officer", "sara.iqbal@qfleet.local", EMP_HASH),
    ]

    Session = get_sessionmaker()
    session = Session()
    try:
        for emp_id, name, role, dept, designation, email, pw_hash in DEMO_EMPLOYEES:
            if session.query(Employee).filter_by(employee_id=emp_id).first():
                continue
            emp = Employee(
                employee_id=emp_id,
                full_name=name,
                role=role,
                department=dept,
                designation=designation,
                email=email,
                password_hash=pw_hash,
                is_active=True,
            )
            session.add(emp)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


try:
    _bootstrap_db()
except Exception as exc:
    import traceback
    print(f"[vercel cold-start] DB bootstrap failed: {exc}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)

# ---- Import the FastAPI app -----------------------------------------------
from backend.main import app  # noqa: E402 — Vercel looks for `app`
