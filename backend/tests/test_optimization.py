"""Tests for the fleet model and the four solvers."""
from __future__ import annotations

import numpy as np
import pytest

from optimization.base import (
    crowding_distance,
    dominates,
    fast_non_dominated_sort,
    knee_point_index,
    non_dominated_mask,
)
from optimization.engine import ALGORITHM_IDS, optimize, run_algorithm, summarise_run
from optimization.fleet_problem import FleetOptimizationProblem
from optimization.nsga2 import NSGA2


# ---------------------------------------------------------------------------
# Problem model
# ---------------------------------------------------------------------------
def test_problem_dimensions(problem):
    assert problem.n_dimensions == problem.n_vessels * 4
    assert problem.bounds.shape == (problem.n_dimensions, 2)
    assert np.all(problem.bounds[:, 0] <= problem.bounds[:, 1])


def test_generation_is_deterministic():
    a = FleetOptimizationProblem(n_vessels=8, n_routes=4, seed=7)
    b = FleetOptimizationProblem(n_vessels=8, n_routes=4, seed=7)
    assert [v.to_dict() for v in a.vessels] == [v.to_dict() for v in b.vessels]
    assert [r.to_dict() for r in a.routes] == [r.to_dict() for r in b.routes]


def test_objectives_respond_to_fuel_choice(problem):
    """
    The original evaluate() ignored the fuel gene entirely, so switching the
    whole fleet to hydrogen changed nothing. It must change emissions now.
    """
    base = {
        "route_index": np.zeros(problem.n_vessels, dtype=int),
        "speed": np.full(problem.n_vessels, 14.0),
        "fuel_selection": np.zeros(problem.n_vessels, dtype=int),
        "shore_power_pct": np.zeros(problem.n_vessels),
    }
    hfo = problem.evaluate_raw(problem.encode_solution(base))

    zero_carbon = dict(base)
    zero_carbon["fuel_selection"] = np.full(
        problem.n_vessels, problem.fuel_types.index("Hydrogen"), dtype=int
    )
    hydrogen = problem.evaluate_raw(problem.encode_solution(zero_carbon))

    assert hydrogen[1] < hfo[1], "zero-carbon fuel must cut CO2"
    assert hydrogen[1] == pytest.approx(0.0, abs=1e-6)


def test_objectives_respond_to_speed(problem):
    def at_speed(v):
        return problem.evaluate_raw(
            problem.encode_solution(
                {
                    "route_index": np.zeros(problem.n_vessels, dtype=int),
                    "speed": np.full(problem.n_vessels, v),
                    "fuel_selection": np.zeros(problem.n_vessels, dtype=int),
                    "shore_power_pct": np.zeros(problem.n_vessels),
                }
            )
        )

    # Slow steaming burns less fuel: power scales with v^3, time only with 1/v.
    assert at_speed(11.0)[0] < at_speed(15.0)[0]


def test_shore_power_reduces_emissions(problem):
    def with_shore(pct):
        return problem.evaluate_raw(
            problem.encode_solution(
                {
                    "route_index": np.zeros(problem.n_vessels, dtype=int),
                    "speed": np.full(problem.n_vessels, 13.0),
                    "fuel_selection": np.zeros(problem.n_vessels, dtype=int),
                    "shore_power_pct": np.full(problem.n_vessels, pct),
                }
            )
        )

    assert with_shore(100.0)[1] <= with_shore(0.0)[1]


def test_encode_decode_roundtrip(problem):
    decisions = {
        "route_index": np.arange(problem.n_vessels) % problem.n_routes,
        "speed": np.full(problem.n_vessels, 13.0),
        "fuel_selection": np.zeros(problem.n_vessels, dtype=int),
        "shore_power_pct": np.full(problem.n_vessels, 25.0),
    }
    decoded = problem.decode_solution(problem.encode_solution(decisions))
    np.testing.assert_array_equal(decoded["route_index"], decisions["route_index"])
    np.testing.assert_allclose(decoded["shore_power_pct"], decisions["shore_power_pct"])


def test_baseline_is_feasible(problem):
    """Savings are only meaningful against a baseline that satisfies demand."""
    baseline = problem.baseline()
    assert baseline["feasible"], f"baseline violates constraints: {baseline['constraint_violation']}"
    assert all(r["covered"] for r in baseline["route_coverage"].values())


def test_batch_and_single_evaluation_agree(problem):
    rng = np.random.default_rng(0)
    X = rng.uniform(problem.bounds[:, 0], problem.bounds[:, 1], (12, problem.n_dimensions))
    np.testing.assert_allclose(
        problem.evaluate_batch(X), np.array([problem.evaluate(x) for x in X]), rtol=1e-9
    )


def test_infeasible_is_penalised(problem):
    """An infeasible plan must score worse than the feasible baseline."""
    baseline_x = problem.baseline_vector()
    # Pile every vessel onto one route so the other lanes go uncovered.
    bad = problem.encode_solution(
        {
            "route_index": np.zeros(problem.n_vessels, dtype=int),
            "speed": np.full(problem.n_vessels, 12.0),
            "fuel_selection": np.zeros(problem.n_vessels, dtype=int),
            "shore_power_pct": np.zeros(problem.n_vessels),
        }
    )
    assert problem.check_constraints(bad) > 0
    weights = problem.scalar_weights()
    scalar = problem.scalar_objective()
    assert scalar(bad) > scalar(baseline_x)


def test_rejects_bad_sizes():
    with pytest.raises(ValueError):
        FleetOptimizationProblem(n_vessels=0, n_routes=3)
    with pytest.raises(ValueError):
        FleetOptimizationProblem(n_vessels=3, n_routes=0)


def test_unknown_fuel_rejected():
    with pytest.raises(ValueError, match="Unknown fuel"):
        FleetOptimizationProblem(n_vessels=3, n_routes=2, fuel_types=["Unobtanium"])


# ---------------------------------------------------------------------------
# Pareto helpers
# ---------------------------------------------------------------------------
def test_dominance():
    assert dominates([1, 1], [2, 2])
    assert not dominates([1, 3], [2, 2])
    assert not dominates([2, 2], [2, 2])


def test_non_dominated_mask():
    F = np.array([[1.0, 5.0], [2.0, 3.0], [5.0, 1.0], [6.0, 6.0]])
    assert non_dominated_mask(F).tolist() == [True, True, True, False]


def test_fast_non_dominated_sort_partitions_everything():
    rng = np.random.default_rng(1)
    F = rng.random((40, 3))
    fronts = fast_non_dominated_sort(F)
    flat = sorted(i for front in fronts for i in front)
    assert flat == list(range(40)), "every solution must land in exactly one front"


def test_crowding_distance_marks_boundaries():
    F = np.array([[0.0, 3.0], [1.0, 2.0], [2.0, 1.0], [3.0, 0.0]])
    d = crowding_distance(F)
    assert np.isinf(d[0]) and np.isinf(d[-1])
    assert np.all(np.isfinite(d[1:-1]))


def test_knee_point_prefers_the_compromise():
    F = np.array([[0.0, 10.0], [5.0, 5.0], [10.0, 0.0]])
    assert knee_point_index(F) == 1


# ---------------------------------------------------------------------------
# Solvers
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("algorithm", ALGORITHM_IDS)
def test_every_algorithm_runs_and_improves(algorithm, problem):
    result = run_algorithm(
        algorithm, problem, max_iterations=25, population_size=24, seed=3
    )
    assert result.history, "solver produced no convergence history"
    assert result.n_evaluations > 0
    # Convergence traces are best-so-far values, so they can never increase.
    assert all(
        result.history[i] >= result.history[i + 1] - 1e-9 for i in range(len(result.history) - 1)
    ), f"{algorithm} convergence history is not monotone"
    assert result.history[-1] <= result.history[0] + 1e-9


@pytest.mark.parametrize("algorithm", ALGORITHM_IDS)
def test_results_are_reproducible(algorithm, problem):
    a = run_algorithm(algorithm, problem, max_iterations=15, population_size=16, seed=99)
    b = run_algorithm(algorithm, problem, max_iterations=15, population_size=16, seed=99)
    assert a.history == b.history, f"{algorithm} is not reproducible for a fixed seed"


@pytest.mark.parametrize("algorithm", ALGORITHM_IDS)
def test_no_algorithm_is_worse_than_the_baseline(algorithm, problem):
    """Warm starting from the baseline makes this a hard guarantee."""
    summary = summarise_run(
        run_algorithm(algorithm, problem, max_iterations=40, population_size=30, seed=5),
        problem,
    )
    for name, change in summary["improvement_vs_baseline"].items():
        assert change["percent_saving"] >= -1e-6, f"{algorithm} made {name} worse"


@pytest.mark.parametrize("algorithm", ALGORITHM_IDS)
def test_solutions_stay_inside_bounds(algorithm, problem):
    result = run_algorithm(algorithm, problem, max_iterations=20, population_size=20, seed=11)
    points = (
        result.front_positions() if result.is_multi_objective else result.best_solution[None, :]
    )
    assert np.all(points >= problem.bounds[:, 0] - 1e-6)
    assert np.all(points <= problem.bounds[:, 1] + 1e-6)


def test_nsga2_mutation_actually_mutates(problem):
    """
    Regression: the original mutation loop rebound the loop variable, so the
    operator was a no-op and offspring were pure crossover.
    """
    solver = NSGA2(
        pop_size=40,
        n_dimensions=problem.n_dimensions,
        bounds=problem.bounds,
        max_generations=5,
        n_objectives=3,
        mutation_prob=1.0,
        seed=1,
    )
    X = solver.population.copy()
    mutated = solver._polynomial_mutation(X)
    assert not np.allclose(X, mutated), "polynomial mutation had no effect"
    assert np.all(mutated >= problem.bounds[:, 0] - 1e-9)
    assert np.all(mutated <= problem.bounds[:, 1] + 1e-9)


def test_nsga2_keeps_population_size(problem):
    """Regression: environmental selection used to IndexError on an exact fill."""
    solver = NSGA2(
        pop_size=20,
        n_dimensions=problem.n_dimensions,
        bounds=problem.bounds,
        max_generations=10,
        n_objectives=3,
        seed=2,
    )
    solver.optimize(_vector_objective(problem))
    assert len(solver.population) == solver.pop_size
    assert len(solver.fitness) == solver.pop_size


def test_qpso_archive_is_bounded(problem):
    from optimization.qpso import MultiObjectiveQPSO

    solver = MultiObjectiveQPSO(
        n_particles=40,
        n_dimensions=problem.n_dimensions,
        bounds=problem.bounds,
        max_iterations=40,
        archive_size=15,
        seed=4,
    )
    result = solver.optimize(_vector_objective(problem))
    assert len(result.pareto_front) <= 15, "archive grew past its cap"


def test_solver_rejects_mismatched_bounds(problem):
    from optimization.pso import PSO

    with pytest.raises(ValueError):
        PSO(n_particles=10, n_dimensions=5, bounds=problem.bounds, max_iterations=5)


def _vector_objective(problem):
    def objective(x):
        return problem.evaluate(x)

    objective.batch = problem.evaluate_batch
    return objective


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def test_optimize_payload_shape():
    payload = optimize("qpso", n_vessels=6, n_routes=3, max_iterations=20, population_size=20, seed=1)
    for key in (
        "algorithm",
        "pareto_front",
        "convergence_history",
        "best_objectives",
        "improvement_vs_baseline",
        "plan",
    ):
        assert key in payload
    assert payload["pareto_size"] == len(payload["pareto_front"])
    assert len(payload["plan"]["assignments"]) == 6


def test_engine_rejects_unknown_algorithm():
    with pytest.raises(ValueError, match="Unknown algorithm"):
        optimize("teleportation", n_vessels=4, n_routes=2)
