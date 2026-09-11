"""End-to-end API tests — every route, its happy path and its failure modes."""
from __future__ import annotations

import pytest

VALID_VOYAGE = {
    "vessel_type": "Container",
    "dwt": 120_000,
    "engine_power_kw": 35_000,
    "speed_knots": 16.5,
    "distance_nm": 5_000,
    "cargo_load_pct": 85,
    "weather_beaufort": 4,
    "draft_meters": 13.5,
    "fuel_type": "LNG",
}
SMALL_PROBLEM = {
    "n_vessels": 6,
    "n_routes": 3,
    "max_iterations": 20,
    "population_size": 20,
}


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------
def test_root(client):
    body = client.get("/").json()
    assert body["status"] == "running"
    assert "endpoints" in body


def test_health_reports_subsystems(client):
    body = client.get("/api/health").json()
    assert body["status"] in {"healthy", "degraded"}
    assert set(body["checks"]) == {"api", "accounts", "prediction_model", "dataset"}


def test_openapi_lists_every_router(client):
    paths = client.get("/openapi.json").json()["paths"]
    for prefix in (
        "/api/auth",
        "/api/admin",
        "/api/optimization",
        "/api/benchmarks",
        "/api/prediction",
        "/api/scenarios",
    ):
        assert any(p.startswith(prefix) for p in paths), f"no routes under {prefix}"


def test_responses_carry_request_id(client):
    response = client.get("/api/health")
    assert response.headers.get("X-Request-ID")
    assert float(response.headers["X-Process-Time"]) >= 0


# ---------------------------------------------------------------------------
# Optimization
# ---------------------------------------------------------------------------
def test_list_algorithms(client):
    body = client.get("/api/optimization/algorithms").json()
    assert {a["id"] for a in body} == {"qpso", "qga", "pso", "nsga2"}
    assert all({"name", "description", "multi_objective"} <= set(a) for a in body)


@pytest.mark.parametrize("algorithm", ["qpso", "qga", "pso", "nsga2"])
def test_optimize_returns_real_results(client, algorithm):
    """
    The original endpoint returned an identical hard-coded body for every
    request. These assertions fail against that implementation.
    """
    response = client.post(
        "/api/optimization/optimize", json={"algorithm": algorithm, **SMALL_PROBLEM}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == algorithm
    assert body["n_evaluations"] > 0
    assert len(body["convergence_history"]) == SMALL_PROBLEM["max_iterations"]
    assert len(body["plan"]["assignments"]) == SMALL_PROBLEM["n_vessels"]
    assert body["elapsed_seconds"] != 2.34  # the old placeholder


def test_optimize_responds_to_its_inputs(client):
    """Different fleet sizes must produce different answers."""
    small = client.post(
        "/api/optimization/optimize",
        json={"algorithm": "qpso", "n_vessels": 4, "n_routes": 2, "max_iterations": 20},
    ).json()
    large = client.post(
        "/api/optimization/optimize",
        json={"algorithm": "qpso", "n_vessels": 20, "n_routes": 6, "max_iterations": 20},
    ).json()
    assert len(small["plan"]["assignments"]) == 4
    assert len(large["plan"]["assignments"]) == 20
    assert small["best_objectives"] != large["best_objectives"]


def test_optimize_is_reproducible(client):
    payload = {"algorithm": "qpso", "seed": 123, **SMALL_PROBLEM}
    first = client.post("/api/optimization/optimize", json=payload).json()
    second = client.post("/api/optimization/optimize", json=payload).json()
    assert first["best_objectives"] == second["best_objectives"]


def test_optimize_restricted_to_selected_fuels(client):
    body = client.post(
        "/api/optimization/optimize",
        json={"algorithm": "qpso", "fuel_types": ["HFO", "LNG"], **SMALL_PROBLEM},
    ).json()
    assert set(body["plan"]["fuel_mix"]) <= {"HFO", "LNG"}


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"algorithm": "warp"}, "algorithm"),
        ({"algorithm": "qpso", "n_vessels": 0}, "n_vessels"),
        ({"algorithm": "qpso", "n_vessels": 100_000}, "n_vessels"),
        ({"algorithm": "qpso", "max_iterations": 1_000_000}, "max_iterations"),
        ({"algorithm": "qpso", "fuel_types": ["Unobtanium"]}, "fuel_types"),
        ({"algorithm": "qpso", "objective_weights": [1, 2]}, "objective_weights"),
    ],
)
def test_optimize_rejects_bad_input(client, payload, field):
    response = client.post("/api/optimization/optimize", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(field in f["field"] for f in body["error"]["details"]["fields"])


def test_optimize_rejects_unknown_fields(client):
    response = client.post(
        "/api/optimization/optimize", json={"algorithm": "qpso", "sneaky": True}
    )
    assert response.status_code == 422


def test_compare_runs_every_algorithm(client):
    body = client.post(
        "/api/optimization/compare", json={"algorithms": ["qpso", "pso"], **SMALL_PROBLEM}
    ).json()
    assert {row["algorithm"] for row in body["comparison"]} == {"qpso", "pso"}
    assert set(body["convergence"]) == {"qpso", "pso"}
    assert body["winner"] in {"qpso", "pso"}
    # Every algorithm must have been judged on the same problem instance.
    assert body["problem"]["n_vessels"] == SMALL_PROBLEM["n_vessels"]


def test_fleet_inspection(client):
    body = client.get("/api/optimization/fleet", params={"n_vessels": 4, "n_routes": 2}).json()
    assert len(body["vessels"]) == 4
    assert len(body["routes"]) == 2
    assert body["baseline"]["feasible"] is True


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------
def test_predict(client):
    response = client.post("/api/prediction/predict", json=VALID_VOYAGE)
    if response.status_code == 409:
        pytest.skip("no trained model available in this environment")
    assert response.status_code == 200
    body = response.json()
    assert body["predicted_fuel_consumption"] > 0
    assert body["estimated_co2_tons"] > 0
    assert len(body["confidence_interval"]) == 2


def test_predict_batch_matches_single(client):
    single = client.post("/api/prediction/predict", json=VALID_VOYAGE)
    if single.status_code == 409:
        pytest.skip("no trained model available in this environment")
    batch = client.post("/api/prediction/predict/batch", json={"voyages": [VALID_VOYAGE] * 3})
    assert batch.status_code == 200
    values = batch.json()["predictions"]
    assert len(values) == 3
    assert values[0] == pytest.approx(single.json()["predicted_fuel_consumption"], rel=1e-6)


@pytest.mark.parametrize(
    "override",
    [
        {"speed_knots": -5},
        {"cargo_load_pct": 150},
        {"weather_beaufort": 99},
        {"fuel_type": "Plutonium"},
        {"vessel_type": "Submarine"},
        {"dwt": 0},
    ],
)
def test_predict_rejects_impossible_values(client, override):
    response = client.post("/api/prediction/predict", json={**VALID_VOYAGE, **override})
    assert response.status_code == 422


def test_train_rejects_absolute_paths(client):
    """Regression: the endpoint used to read any path the caller supplied."""
    for attack in ("/etc/passwd", "../../etc/passwd", "C:\\Windows\\win.ini", "./secrets"):
        response = client.post("/api/prediction/train", json={"dataset": attack})
        assert response.status_code in {404, 422}
        assert "passwd" not in response.text and "win.ini" not in response.text


def test_train_reports_missing_dataset(client):
    response = client.post("/api/prediction/train", json={"dataset": "does_not_exist.csv"})
    assert response.status_code == 404
    assert "available_datasets" in response.json()["error"]["details"]


def test_metrics_are_real(client):
    response = client.get("/api/prediction/metrics")
    if response.status_code == 409:
        pytest.skip("no trained model available in this environment")
    body = response.json()
    # The original returned rmse=mae=r2=0.0 unconditionally.
    assert body["r2"] > 0.5
    assert body["rmse"] > 0
    assert body["n_train"] > 0


def test_feature_importance(client):
    response = client.get("/api/prediction/feature-importance")
    if response.status_code == 409:
        pytest.skip("no trained model available in this environment")
    features = response.json()["features"]
    assert sum(f["importance"] for f in features) == pytest.approx(1.0, abs=1e-3)
    # Sorted most important first.
    assert features == sorted(features, key=lambda f: -f["importance"])


def test_model_info(client):
    body = client.get("/api/prediction/model-info").json()
    assert "fuel_types" in body and "vessel_types" in body
    assert isinstance(body["trained"], bool)


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------
def test_benchmark_run_and_fetch(client):
    body = client.post(
        "/api/benchmarks/run",
        json={
            "algorithms": ["qpso", "pso"],
            "n_runs": 2,
            "n_vessels": 6,
            "n_routes": 3,
            "max_iterations": 20,
            "population_size": 20,
        },
    ).json()
    assert body["status"] == "completed"
    # The original returned a fixed string and never ran anything.
    assert body["summary"] != "Benchmarking completed successfully."
    assert len(body["results"]) == 2
    for row in body["results"]:
        assert row["n_runs"] == 2
        assert row["time_seconds_mean"] > 0
        assert "hypervolume_mean" in row
        assert row["rank"] in {1, 2}

    stored = client.get("/api/benchmarks/results").json()
    assert stored["completed_at"] == body["completed_at"]

    convergence = client.get("/api/benchmarks/convergence").json()
    assert set(convergence["series"]) == {"qpso", "pso"}
    # The original served three hand-typed 10-point lists.
    assert any(len(series) == 20 for series in convergence["series"].values())


def test_benchmark_rejects_unknown_algorithm(client):
    response = client.post("/api/benchmarks/run", json={"algorithms": ["quantum_magic"]})
    assert response.status_code == 422


def test_scalability(client):
    body = client.post(
        "/api/benchmarks/scalability",
        json={"algorithms": ["pso"], "problem_sizes": [4, 8], "n_runs": 1, "max_iterations": 10},
    ).json()
    sizes = {row["problem_size"] for row in body["rows"]}
    assert sizes == {4, 8}
    # Different sizes must yield different problems — the original reused one.
    dims = {row["n_dimensions"] for row in body["rows"]}
    assert len(dims) == 2


def test_metrics_guide(client):
    guide = client.get("/api/benchmarks/metrics-guide").json()
    assert all({"id", "name", "direction", "description"} <= set(item) for item in guide)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def test_fuels_match_the_optimizer(client):
    """Regression: the scenario module used to carry a different fuel table."""
    scenario_fuels = {f["name"] for f in client.get("/api/scenarios/fuels").json()}
    model_info = client.get("/api/prediction/model-info").json()
    assert scenario_fuels == set(model_info["fuel_types"])


def test_scenario_analyze(client):
    body = client.post("/api/scenarios/analyze", json={"target_fuel": "LNG"}).json()
    assert body["scenario"]["emission_reduction_pct"] > 0
    assert body["scenario"]["vessels_switched"] > 0
    assert body["scenario"]["retrofit_capex_usd"] > 0


def test_scenario_zero_carbon_fuel_eliminates_co2(client):
    body = client.post("/api/scenarios/analyze", json={"target_fuel": "Hydrogen"}).json()
    assert body["scenario"]["total_emissions_co2"] == pytest.approx(0.0, abs=1e-6)
    assert body["scenario"]["emission_reduction_pct"] == pytest.approx(100.0, abs=1e-6)


def test_scenario_with_custom_fleet(client):
    body = client.post(
        "/api/scenarios/analyze",
        json={
            "target_fuel": "Methanol",
            "fleet": {"vessels": [{"id": 1, "fuel_type": "HFO", "fuel_consumption": 1000}]},
        },
    ).json()
    assert body["base"]["total_fuel_tons"] == 1000
    assert body["scenario"]["vessels_switched"] == 1


def test_scenario_compare(client):
    body = client.post(
        "/api/scenarios/compare", json={"fuel_options": ["LNG", "Ammonia"]}
    ).json()
    assert len(body["scenarios"]) == 3  # base + two
    assert body["scenarios"][0]["scenario_name"] == "Base Scenario"


def test_shore_power(client):
    body = client.post("/api/scenarios/shore-power", json={"shore_power_pct": 100}).json()
    assert body["avoided_co2_tons"] > 0
    none = client.post("/api/scenarios/shore-power", json={"shore_power_pct": 0}).json()
    assert none["avoided_co2_tons"] == 0


def test_transition_plan_is_monotone(client):
    body = client.post(
        "/api/scenarios/transition-plan", json={"target_year": 2032, "target_fuel": "LNG"}
    ).json()
    pcts = [phase["target_pct_green_fuel"] for phase in body["phases"]]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100.0
    # Regression: the start year used to be hard-coded to 2024.
    assert body["phases"][0]["year"] > 2025


def test_transition_plan_rejects_past_target(client):
    response = client.post("/api/scenarios/transition-plan", json={"target_year": 2025})
    assert response.status_code in {422}


@pytest.mark.parametrize(
    "payload",
    [
        {"target_fuel": "Unobtanium"},
        {"target_fuel": "LNG", "vessel_indices": [999]},
    ],
)
def test_scenario_bad_input(client, payload):
    response = client.post("/api/scenarios/analyze", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_set_and_get_session_fleet(client):
    fleet = {"vessels": [{"id": 7, "name": "MV Test", "fuel_type": "VLSFO", "fuel_consumption": 250}]}
    put = client.put("/api/scenarios/fleet", json=fleet).json()
    assert put["vessel_count"] == 1
    assert client.get("/api/scenarios/fleet").json()["vessels"][0]["name"] == "MV Test"


# ---------------------------------------------------------------------------
# Error contract
# ---------------------------------------------------------------------------
def test_unknown_route_returns_structured_error(client):
    body = client.get("/api/does-not-exist").json()
    assert "error" in body and "code" in body["error"]


def test_errors_never_leak_internals(client):
    """The old global handler returned str(exc), exposing server file paths."""
    response = client.post("/api/prediction/train", json={"dataset": "nope.csv"})
    assert "/home/" not in response.text
    assert "Traceback" not in response.text
