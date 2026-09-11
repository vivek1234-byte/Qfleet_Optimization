"""Shared pytest fixtures. Adds backend/ to sys.path so `main` imports cleanly."""
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
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
