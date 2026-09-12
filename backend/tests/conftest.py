"""Shared pytest fixtures. Adds backend/ to sys.path so `main` imports cleanly."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def client():
    """
    A client that is signed in as an administrator.

    The data routers are behind ``require_module`` (see ``main.py``), because
    per-employee access control is meaningless if ``/api/prediction`` answers
    an anonymous caller. These tests are about whether the optimiser, the
    model and the scenario engine are correct, not about who may reach them —
    authorization has its own suite in ``test_auth.py`` — so the fixture
    carries a token and the functional tests stay focused.
    """
    import tempfile
    from pathlib import Path

    from fastapi.testclient import TestClient

    from config import settings
    from db import session as db_session
    from db.models import Base, Role

    db_path = Path(tempfile.gettempdir()) / "qfleet_test_api.sqlite3"
    settings.DATABASE_URL = f"sqlite:///{db_path.as_posix()}"
    settings.BCRYPT_ROUNDS = 4
    settings.JWT_SECRET = "test-secret-not-used-anywhere-real"
    db_session.reset_engine()

    engine = db_session.get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from auth.service import create_employee

    with db_session.session_scope() as db:
        create_employee(
            db,
            employee_id="EMP001",
            full_name="Fleet Administrator",
            password="Admin@12345",
            role=Role.ADMIN.value,
            department="Operations",
        )

    import main

    with TestClient(main.app) as c:
        token = c.post(
            "/api/auth/login",
            json={"employee_id": "EMP001", "password": "Admin@12345"},
        ).json()["access_token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


@pytest.fixture
def problem():
    from optimization.fleet_problem import FleetOptimizationProblem

    return FleetOptimizationProblem(n_vessels=6, n_routes=3, seed=42)


@pytest.fixture(scope="session")
def voyage_df():
    import pandas as pd

    from config import settings

    if not settings.DEFAULT_DATASET.exists():
        pytest.skip("voyage dataset not generated")
    return pd.read_csv(settings.DEFAULT_DATASET)
