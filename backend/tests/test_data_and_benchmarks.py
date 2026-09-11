"""Tests for the fuel database, the dataset generator and the benchmark runner."""
from __future__ import annotations

import numpy as np
import pytest

from benchmarking.metrics import (
    combined_reference_front,
    convergence_metric,
    hypervolume,
    igd,
    igd_plus,
    reference_point,
    spacing,
    spread,
)
from benchmarking.runner import BenchmarkRunner
from data.fuel_database import (
    FUEL_DATABASE,
    cost_from_mass,
    emissions_from_mass,
    fuel_names,
    get_fuel,
    require_fuel,
    resolve_fuels,
)
from data.generator import generate_dataset


# ---------------------------------------------------------------------------
# Fuel database
# ---------------------------------------------------------------------------
def test_lookup_is_case_insensitive():
    assert get_fuel("lng") is get_fuel("LNG")
    assert get_fuel("  MgO  ").name == "MGO"
    assert get_fuel("nope") is None


def test_require_fuel_raises_with_a_helpful_message():
    with pytest.raises(ValueError, match="Available fuels"):
        require_fuel("Unobtanium")


def test_derived_units_are_self_consistent():
    """tCO2/t and USD/t must follow from the g/MJ and USD/GJ figures."""
    for fuel in FUEL_DATABASE.values():
        expected_co2 = fuel.emission_factor_gco2_per_mj * fuel.energy_density_mj_per_kg / 1000.0
        assert fuel.co2_tons_per_ton_fuel == pytest.approx(expected_co2)
        assert fuel.cost_per_ton == pytest.approx(fuel.cost_per_gj * fuel.energy_density_mj_per_kg)


def test_zero_carbon_fuels_emit_nothing():
    for name in ("Hydrogen", "Ammonia"):
        assert emissions_from_mass(name, 100.0)["co2_tons"] == 0.0
        assert get_fuel(name).is_zero_carbon


def test_hfo_matches_the_conventional_emission_factor():
    # ~3.11 t CO2 per tonne of HFO is the standard IMO figure.
    assert emissions_from_mass("HFO", 1.0)["co2_tons"] == pytest.approx(3.11, abs=0.02)


def test_cost_scales_linearly():
    assert cost_from_mass("LNG", 200.0) == pytest.approx(2 * cost_from_mass("LNG", 100.0))


def test_resolve_fuels():
    assert len(resolve_fuels(None)) == len(fuel_names())
    assert [f.name for f in resolve_fuels(["lng", "LNG", "hfo"])] == ["LNG", "HFO"]
    with pytest.raises(ValueError):
        resolve_fuels(["nope"])


# ---------------------------------------------------------------------------
# Dataset generator
# ---------------------------------------------------------------------------
def test_generator_is_reproducible():
    a = generate_dataset(200, seed=5)
    b = generate_dataset(200, seed=5)
    assert a.equals(b)


def test_generated_data_is_physical():
    df = generate_dataset(500, seed=1)
    assert len(df) == 500
    assert (df["fuel_consumption_tons"] > 0).all()
    assert (df["co2_emissions_tons"] >= 0).all()
    assert df["cargo_load_pct"].between(0, 100).all()
    assert df["weather_beaufort"].between(0, 12).all()
    assert not df.isna().any().any()


def test_zero_carbon_rows_have_zero_co2():
    df = generate_dataset(2000, seed=3)
    zero = df[df["fuel_type"].isin(["Hydrogen", "Ammonia"])]
    assert (zero["co2_emissions_tons"] == 0).all()


def test_generator_rejects_bad_size():
    with pytest.raises(ValueError):
        generate_dataset(0)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def test_hypervolume_of_a_known_square():
    # One point at (1,1) with reference (2,2) dominates a 1x1 box.
    assert hypervolume(np.array([[1.0, 1.0]]), np.array([2.0, 2.0])) == pytest.approx(1.0)


def test_hypervolume_rewards_a_better_front():
    ref = np.array([10.0, 10.0])
    good = np.array([[1.0, 1.0], [2.0, 0.5]])
    poor = np.array([[8.0, 8.0]])
    assert hypervolume(good, ref) > hypervolume(poor, ref)


def test_hypervolume_of_empty_front_is_zero():
    assert hypervolume(np.empty((0, 2)), np.array([1.0, 1.0])) == 0.0


def test_igd_is_zero_for_an_exact_match():
    front = np.array([[1.0, 2.0], [2.0, 1.0]])
    assert igd(front, front) == pytest.approx(0.0)
    assert igd_plus(front, front) == pytest.approx(0.0)


def test_igd_grows_with_distance():
    true_front = np.array([[0.0, 1.0], [1.0, 0.0]])
    near = np.array([[0.1, 1.1], [1.1, 0.1]])
    far = np.array([[5.0, 5.0]])
    assert igd(near, true_front) < igd(far, true_front)


def test_spread_and_spacing_prefer_even_distributions():
    even = np.array([[0.0, 3.0], [1.0, 2.0], [2.0, 1.0], [3.0, 0.0]])
    clumped = np.array([[0.0, 3.0], [0.05, 2.95], [0.1, 2.9], [3.0, 0.0]])
    assert spacing(even) < spacing(clumped)
    assert spread(even) < spread(clumped)


def test_single_point_front_is_degenerate_not_an_error():
    assert spread(np.array([[1.0, 1.0]])) == 0.0
    assert spacing(np.array([[1.0, 1.0]])) == 0.0


def test_reference_point_dominates_every_solution():
    fronts = [np.array([[1.0, 5.0]]), np.array([[4.0, 2.0]])]
    ref = reference_point(fronts)
    assert np.all(ref > np.vstack(fronts).max(axis=0))


def test_combined_reference_front_drops_dominated_points():
    merged = combined_reference_front([np.array([[1.0, 1.0], [5.0, 5.0]]), np.array([[2.0, 0.5]])])
    assert len(merged) == 2


def test_convergence_metric():
    summary = convergence_metric([10.0, 5.0, 2.0, 1.0, 1.0])
    assert summary["final_value"] == 1.0
    assert summary["total_improvement"] == 9.0
    assert 1 <= summary["iterations_to_90pct"] <= 5
    assert convergence_metric([])["iterations"] == 0


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------
def test_runner_produces_scored_results(problem):
    runner = BenchmarkRunner(problem, ["qpso", "pso"], max_iterations=15, population_size=16)
    results = runner.run_all(n_runs=2)
    assert set(results) == {"qpso", "pso"}
    for res in results.values():
        assert len(res.runs) == 2
        assert res.avg_time_seconds > 0
        assert "hypervolume_mean" in res.metrics
        assert len(res.median_history) == 15


def test_comparison_table_is_ranked(problem):
    runner = BenchmarkRunner(problem, ["qpso", "pso", "qga"], max_iterations=10, population_size=12)
    table = runner.comparison_table(runner.run_all(n_runs=1))
    assert [row["rank"] for row in table] == [1, 2, 3]
    fitnesses = [row["best_fitness_mean"] for row in table]
    assert fitnesses == sorted(fitnesses)


def test_scalability_builds_a_new_problem_per_size(problem):
    runner = BenchmarkRunner(problem, ["pso"], max_iterations=8, population_size=10)
    rows = runner.scalability_test(problem_sizes=(4, 12), n_runs=1)
    dims = {row["n_dimensions"] for row in rows}
    assert dims == {16, 48}, "each size must build its own problem"


def test_runner_rejects_empty_algorithm_list(problem):
    with pytest.raises(ValueError):
        BenchmarkRunner(problem, [])
