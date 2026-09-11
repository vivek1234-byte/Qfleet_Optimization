"""
The optimization engine: the single place that knows how to run each algorithm
against a :class:`FleetOptimizationProblem` and turn the result into a payload
the API and the benchmark runner can both consume.

This is what replaced the hard-coded JSON that ``optimization/api.py`` used to
return. Every number the API now reports comes from an actual solver run.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

try:
    from .base import OptimizeResult, knee_point_index, non_dominated_mask
    from .fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
    from .nsga2 import NSGA2
    from .pso import PSO
    from .qga import QGA
    from .qpso import QPSO, MultiObjectiveQPSO
except ImportError:  # pragma: no cover
    from base import OptimizeResult, knee_point_index, non_dominated_mask
    from fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
    from nsga2 import NSGA2
    from pso import PSO
    from qga import QGA
    from qpso import QPSO, MultiObjectiveQPSO

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlgorithmSpec:
    """Everything the API needs to describe and instantiate an algorithm."""

    id: str
    name: str
    description: str
    family: str
    multi_objective: bool
    quantum_inspired: bool


ALGORITHM_SPECS: Dict[str, AlgorithmSpec] = {
    "qpso": AlgorithmSpec(
        id="qpso",
        name="Quantum Particle Swarm Optimization",
        description=(
            "Quantum-behaved PSO with an external, crowding-pruned Pareto archive. "
            "Particles are sampled from a delta potential well around a stochastic "
            "attractor, so the swarm keeps global search ability without velocity."
        ),
        family="swarm",
        multi_objective=True,
        quantum_inspired=True,
    ),
    "qga": AlgorithmSpec(
        id="qga",
        name="Quantum Genetic Algorithm",
        description=(
            "Qubit-encoded GA with Gray decoding, a vectorised rotation gate and a "
            "catastrophe operator. Scalarised weighted-sum objective."
        ),
        family="evolutionary",
        multi_objective=False,
        quantum_inspired=True,
    ),
    "pso": AlgorithmSpec(
        id="pso",
        name="Particle Swarm Optimization",
        description=(
            "Classical PSO with decreasing inertia and velocity clamping. Serves as "
            "the non-quantum baseline for benchmarking."
        ),
        family="swarm",
        multi_objective=False,
        quantum_inspired=False,
    ),
    "nsga2": AlgorithmSpec(
        id="nsga2",
        name="NSGA-II",
        description=(
            "Non-dominated Sorting Genetic Algorithm II with SBX crossover and "
            "polynomial mutation. The reference multi-objective baseline."
        ),
        family="evolutionary",
        multi_objective=True,
        quantum_inspired=False,
    ),
}

ALGORITHM_IDS: List[str] = list(ALGORITHM_SPECS.keys())


def list_algorithms() -> List[Dict[str, Any]]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "family": s.family,
            "multi_objective": s.multi_objective,
            "quantum_inspired": s.quantum_inspired,
        }
        for s in ALGORITHM_SPECS.values()
    ]


def normalise_algorithm(algorithm: str) -> str:
    key = (algorithm or "").strip().lower()
    if key not in ALGORITHM_SPECS:
        raise ValueError(
            f"Unknown algorithm '{algorithm}'. Available: {', '.join(ALGORITHM_IDS)}"
        )
    return key


# ---------------------------------------------------------------------------
# Solver construction
# ---------------------------------------------------------------------------
def build_solver(
    algorithm: str,
    problem: FleetOptimizationProblem,
    *,
    max_iterations: int = 100,
    population_size: int = 60,
    archive_size: int = 100,
    seed: Optional[int] = None,
    warm_start: bool = True,
):
    """Instantiate the requested solver, sized for ``problem``."""
    algorithm = normalise_algorithm(algorithm)
    bounds = problem.bounds
    n_dim = problem.n_dimensions
    # Seed every solver with the feasible baseline plan so no run can report a
    # result worse than the do-nothing case.
    seeds = problem.baseline_vector()[None, :] if warm_start else None

    common = dict(bounds=bounds, seed=seed, seed_solutions=seeds)

    if algorithm == "qpso":
        return MultiObjectiveQPSO(
            n_particles=population_size,
            n_dimensions=n_dim,
            max_iterations=max_iterations,
            archive_size=archive_size,
            **common,
        )
    if algorithm == "nsga2":
        return NSGA2(
            pop_size=population_size,
            n_dimensions=n_dim,
            max_generations=max_iterations,
            n_objectives=problem.n_objectives,
            **common,
        )
    if algorithm == "pso":
        return PSO(
            n_particles=population_size,
            n_dimensions=n_dim,
            max_iterations=max_iterations,
            **common,
        )
    if algorithm == "qga":
        # 8 qubits per decision variable keeps the register small enough that a
        # 60-vessel fleet stays inside a few thousand qubits.
        return QGA(
            pop_size=population_size,
            n_qubits_per_var=8,
            n_variables=n_dim,
            max_generations=max_iterations,
            **common,
        )
    raise ValueError(f"Unhandled algorithm '{algorithm}'")  # pragma: no cover


def objective_for(algorithm: str, problem: FleetOptimizationProblem, weights=None):
    """
    Multi-objective solvers get the vector objective, the rest a scalar one.

    Both carry the same ``trace`` function, so every algorithm's convergence
    history is the *same* normalised scalar and the four curves can be
    compared directly on one chart.
    """
    spec = ALGORITHM_SPECS[normalise_algorithm(algorithm)]
    w = problem.scalar_weights(weights)

    def trace(F: np.ndarray) -> float:
        return float((problem.normalise(np.atleast_2d(F)) @ w).min())

    if spec.multi_objective:
        def vector_objective(x: np.ndarray) -> np.ndarray:
            return problem.evaluate(x)

        vector_objective.batch = problem.evaluate_batch  # type: ignore[attr-defined]
        vector_objective.trace = trace  # type: ignore[attr-defined]
        return vector_objective

    scalar = problem.scalar_objective(weights)
    scalar.trace = lambda F: float(np.asarray(F, dtype=float).min())  # type: ignore[attr-defined]
    return scalar


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
def run_algorithm(
    algorithm: str,
    problem: FleetOptimizationProblem,
    *,
    max_iterations: int = 100,
    population_size: int = 60,
    archive_size: int = 100,
    weights: Optional[Sequence[float]] = None,
    seed: Optional[int] = None,
) -> OptimizeResult:
    """Run one solver on ``problem`` and return its raw result."""
    algorithm = normalise_algorithm(algorithm)
    solver = build_solver(
        algorithm,
        problem,
        max_iterations=max_iterations,
        population_size=population_size,
        archive_size=archive_size,
        seed=seed,
    )
    objective = objective_for(algorithm, problem, weights)

    started = time.perf_counter()
    result = solver.optimize(objective)
    elapsed = time.perf_counter() - started

    result.meta["elapsed_seconds"] = elapsed
    result.meta["max_iterations"] = max_iterations
    result.meta["population_size"] = population_size
    logger.info(
        "%s finished in %.2fs (%d evaluations, %d dimensions)",
        algorithm,
        elapsed,
        result.n_evaluations,
        problem.n_dimensions,
    )
    return result


def _pareto_from_result(
    result: OptimizeResult, problem: FleetOptimizationProblem
) -> np.ndarray:
    """Objective matrix of the result's front, or the single best point."""
    if result.is_multi_objective:
        F = result.front_objectives()
        if F.size:
            return F
    if result.best_solution is not None:
        return problem.evaluate(result.best_solution)[None, :]
    return np.empty((0, problem.n_objectives))


def _positions_from_result(
    result: OptimizeResult, problem: FleetOptimizationProblem
) -> np.ndarray:
    if result.is_multi_objective:
        P = result.front_positions()
        if P.size:
            return P
    if result.best_solution is not None:
        return result.best_solution[None, :]
    return np.empty((0, problem.n_dimensions))


def summarise_run(
    result: OptimizeResult,
    problem: FleetOptimizationProblem,
    *,
    include_plan: bool = True,
    max_front_points: int = 120,
) -> Dict[str, Any]:
    """Turn a solver result into the JSON payload the API returns."""
    positions = _positions_from_result(result, problem)
    penalised = _pareto_from_result(result, problem)

    if len(penalised) == 0:
        raise RuntimeError(f"{result.algorithm} produced no solutions")

    # Filter on the penalised objectives (what the solver actually optimised),
    # but report the raw ones — a plan's real fuel bill has no solver penalty
    # in it. Feasibility is reported separately rather than baked into a number.
    if len(penalised) > 1:
        keep = non_dominated_mask(penalised)
        positions, penalised = positions[keep], penalised[keep]
    if len(penalised) > max_front_points:
        step = max(len(penalised) // max_front_points, 1)
        positions = positions[::step][:max_front_points]
        penalised = penalised[::step][:max_front_points]

    raw, violations = problem.evaluate_detailed(positions)
    feasible_mask = violations <= 1e-9

    # Prefer a feasible compromise. An infeasible plan can look cheaper simply
    # because it skips a route or overruns a schedule, so it must never win
    # the knee-point pick while any feasible alternative exists.
    if np.any(feasible_mask):
        candidate_idx = np.flatnonzero(feasible_mask)
    else:
        candidate_idx = np.argsort(violations, kind="stable")[: max(len(violations) // 4, 1)]
    knee_local = knee_point_index(raw[candidate_idx])
    best_x = positions[candidate_idx[knee_local]]

    baseline = problem.baseline()
    plan = problem.describe_solution(best_x)

    improvements = {}
    for key in OBJECTIVE_NAMES:
        base_val = baseline["objectives"][key]
        new_val = plan["objectives"][key]
        improvements[key] = {
            "baseline": base_val,
            "optimized": new_val,
            "absolute_saving": round(base_val - new_val, 2),
            "percent_saving": round(((base_val - new_val) / base_val * 100.0) if base_val else 0.0, 2),
        }

    spec = ALGORITHM_SPECS[result.algorithm]
    payload: Dict[str, Any] = {
        "algorithm": result.algorithm,
        "algorithm_name": spec.name,
        "quantum_inspired": spec.quantum_inspired,
        "multi_objective": spec.multi_objective,
        "elapsed_seconds": round(float(result.meta.get("elapsed_seconds", 0.0)), 4),
        "n_evaluations": result.n_evaluations,
        "iterations": int(result.meta.get("max_iterations", len(result.history))),
        "population_size": int(result.meta.get("population_size", 0)),
        "seed": result.meta.get("seed"),
        "convergence_history": [round(float(v), 6) for v in result.history],
        "pareto_front": [
            {
                **{name: round(float(val), 3) for name, val in zip(OBJECTIVE_NAMES, row)},
                "feasible": bool(feasible_mask[i]),
            }
            for i, row in enumerate(raw)
        ],
        "pareto_size": int(len(raw)),
        "feasible_solutions": int(feasible_mask.sum()),
        "objective_names": list(OBJECTIVE_NAMES),
        "best_objectives": plan["objectives"],
        "improvement_vs_baseline": improvements,
        "baseline_objectives": baseline["objectives"],
        "feasible": plan["feasible"],
        "constraint_violation": plan["constraint_violation"],
    }
    if not spec.multi_objective:
        payload["best_fitness"] = round(float(result.best_fitness), 6)
    if include_plan:
        payload["plan"] = plan
        payload["decision_vector"] = [round(float(v), 4) for v in best_x]
    return payload


def optimize(
    algorithm: str,
    *,
    n_vessels: int = 10,
    n_routes: int = 5,
    fuel_types: Optional[Sequence[str]] = None,
    max_iterations: int = 100,
    population_size: int = 60,
    carbon_price_usd_per_ton: float = 0.0,
    weights: Optional[Sequence[float]] = None,
    seed: Optional[int] = 42,
    include_plan: bool = True,
) -> Dict[str, Any]:
    """End-to-end convenience wrapper: build the problem, solve it, summarise."""
    problem = FleetOptimizationProblem(
        n_vessels=n_vessels,
        n_routes=n_routes,
        fuel_types=list(fuel_types) if fuel_types else None,
        seed=seed if seed is not None else 42,
        carbon_price_usd_per_ton=carbon_price_usd_per_ton,
    )
    result = run_algorithm(
        algorithm,
        problem,
        max_iterations=max_iterations,
        population_size=population_size,
        weights=weights,
        seed=seed,
    )
    payload = summarise_run(result, problem, include_plan=include_plan)
    payload["problem"] = {
        "n_vessels": problem.n_vessels,
        "n_routes": problem.n_routes,
        "n_dimensions": problem.n_dimensions,
        "fuel_types": problem.fuel_types,
        "carbon_price_usd_per_ton": problem.carbon_price_usd_per_ton,
    }
    return payload
