"""
Benchmark runner.

The previous version called ``algo.optimize(self.problem)`` and read ``.get()``
keys off the return value — but every solver in this project returns a tuple,
so ``run_single`` raised ``AttributeError`` on its first line of real work.
The runner was never actually runnable.

It now drives the solvers through :mod:`optimization.engine`, which gives every
algorithm the same :class:`OptimizeResult` interface, repeats each algorithm
over several seeded runs, and computes quality indicators against a shared
reference front so hypervolume and IGD are comparable across algorithms.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

try:
    from ..optimization.engine import ALGORITHM_SPECS, normalise_algorithm, run_algorithm
    from ..optimization.fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
    from .metrics import (
        combined_reference_front,
        convergence_metric,
        hypervolume,
        igd,
        igd_plus,
        reference_point,
        spacing,
        spread,
    )
except ImportError:  # pragma: no cover
    from optimization.engine import ALGORITHM_SPECS, normalise_algorithm, run_algorithm
    from optimization.fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
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

logger = logging.getLogger(__name__)


@dataclass
class RunRecord:
    """One seeded run of one algorithm."""

    seed: int
    elapsed_seconds: float
    n_evaluations: int
    history: List[float]
    front: np.ndarray
    best_scalar: float
    feasible: bool


@dataclass
class BenchmarkResult:
    """Aggregated results for one algorithm across ``n_runs`` runs."""

    algorithm: str
    algorithm_name: str
    quantum_inspired: bool
    runs: List[RunRecord] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    # -- aggregates --------------------------------------------------------
    @property
    def avg_best_fitness(self) -> float:
        return float(np.mean([r.best_scalar for r in self.runs])) if self.runs else float("nan")

    @property
    def std_best_fitness(self) -> float:
        return float(np.std([r.best_scalar for r in self.runs])) if self.runs else 0.0

    @property
    def avg_time_seconds(self) -> float:
        return float(np.mean([r.elapsed_seconds for r in self.runs])) if self.runs else 0.0

    @property
    def convergence_histories(self) -> List[List[float]]:
        return [r.history for r in self.runs]

    @property
    def median_history(self) -> List[float]:
        """Element-wise median trace — robust to a single unlucky seed."""
        if not self.runs:
            return []
        length = min(len(r.history) for r in self.runs)
        if length == 0:
            return []
        stacked = np.array([r.history[:length] for r in self.runs], dtype=float)
        return [float(v) for v in np.median(stacked, axis=0)]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "algorithm_name": self.algorithm_name,
            "quantum_inspired": self.quantum_inspired,
            "n_runs": len(self.runs),
            "best_fitness_mean": round(self.avg_best_fitness, 6),
            "best_fitness_std": round(self.std_best_fitness, 6),
            "best_fitness_min": round(min((r.best_scalar for r in self.runs), default=float("nan")), 6),
            "time_seconds_mean": round(self.avg_time_seconds, 4),
            "evaluations_mean": int(np.mean([r.n_evaluations for r in self.runs])) if self.runs else 0,
            "feasible_runs": sum(1 for r in self.runs if r.feasible),
            "convergence": self.median_history,
            **{k: (round(v, 6) if isinstance(v, float) else v) for k, v in self.metrics.items()},
        }


class BenchmarkRunner:
    """Runs a set of algorithms against one fleet problem and scores them."""

    def __init__(
        self,
        problem: FleetOptimizationProblem,
        algorithms: Sequence[str],
        *,
        max_iterations: int = 100,
        population_size: int = 60,
        base_seed: int = 1000,
    ) -> None:
        if not algorithms:
            raise ValueError("at least one algorithm is required")
        self.problem = problem
        self.algorithms = [normalise_algorithm(a) for a in algorithms]
        self.max_iterations = int(max_iterations)
        self.population_size = int(population_size)
        self.base_seed = int(base_seed)
        self._weights = problem.scalar_weights()

    # -- single algorithm --------------------------------------------------
    def run_single(self, algorithm: str, n_runs: int = 5) -> BenchmarkResult:
        algorithm = normalise_algorithm(algorithm)
        spec = ALGORITHM_SPECS[algorithm]
        result = BenchmarkResult(
            algorithm=algorithm,
            algorithm_name=spec.name,
            quantum_inspired=spec.quantum_inspired,
        )

        for run_index in range(max(int(n_runs), 1)):
            seed = self.base_seed + run_index
            outcome = run_algorithm(
                algorithm,
                self.problem,
                max_iterations=self.max_iterations,
                population_size=self.population_size,
                seed=seed,
            )

            if outcome.is_multi_objective:
                positions = outcome.front_positions()
                front = outcome.front_objectives()
            else:
                positions = (
                    outcome.best_solution[None, :]
                    if outcome.best_solution is not None
                    else np.empty((0, self.problem.n_dimensions))
                )
                front = (
                    self.problem.evaluate(outcome.best_solution)[None, :]
                    if outcome.best_solution is not None
                    else np.empty((0, self.problem.n_objectives))
                )

            if positions.size:
                raw, violations = self.problem.evaluate_detailed(positions)
                feasible = bool(np.any(violations <= 1e-9))
                scalar = float((self.problem.normalise(front) @ self._weights).min())
            else:  # pragma: no cover - defensive
                raw, feasible, scalar = front, False, float("inf")

            result.runs.append(
                RunRecord(
                    seed=seed,
                    elapsed_seconds=float(outcome.meta.get("elapsed_seconds", 0.0)),
                    n_evaluations=outcome.n_evaluations,
                    history=[float(v) for v in outcome.history],
                    front=raw,
                    best_scalar=scalar,
                    feasible=feasible,
                )
            )

        return result

    # -- whole suite -------------------------------------------------------
    def run_all(self, n_runs: int = 5) -> Dict[str, BenchmarkResult]:
        results: Dict[str, BenchmarkResult] = {}
        for algorithm in self.algorithms:
            logger.info("benchmarking %s over %d runs", algorithm, n_runs)
            results[algorithm] = self.run_single(algorithm, n_runs)
        self.score(results)
        return results

    def score(self, results: Dict[str, BenchmarkResult]) -> Dict[str, BenchmarkResult]:
        """
        Attach quality indicators, computed against a *shared* reference.

        Hypervolume and IGD are only meaningful when every algorithm is
        measured against the same reference point and reference front, which is
        why this is a suite-level step rather than a per-run one.
        """
        all_fronts = [r.front for res in results.values() for r in res.runs if r.front.size]
        if not all_fronts:
            return results

        ref_point = reference_point(all_fronts, margin=0.05)
        true_front = combined_reference_front(all_fronts)

        for res in results.values():
            hv, igd_vals, igdp, spr, spc = [], [], [], [], []
            for run in res.runs:
                if not run.front.size:
                    continue
                hv.append(hypervolume(run.front, ref_point))
                igd_vals.append(igd(run.front, true_front))
                igdp.append(igd_plus(run.front, true_front))
                spr.append(spread(run.front))
                spc.append(spacing(run.front))

            res.metrics = {
                "hypervolume_mean": float(np.mean(hv)) if hv else 0.0,
                "hypervolume_std": float(np.std(hv)) if hv else 0.0,
                "igd_mean": float(np.mean(igd_vals)) if igd_vals else float("inf"),
                "igd_plus_mean": float(np.mean(igdp)) if igdp else float("inf"),
                "spread_mean": float(np.mean(spr)) if spr else 0.0,
                "spacing_mean": float(np.mean(spc)) if spc else 0.0,
                "front_size_mean": float(np.mean([len(r.front) for r in res.runs])),
                "convergence_summary": convergence_metric(res.median_history),
            }
        return results

    # -- reporting ---------------------------------------------------------
    def comparison_table(self, results: Dict[str, BenchmarkResult]) -> List[Dict[str, Any]]:
        """Flat rows, ranked best-first by mean scalarised objective."""
        rows = [res.to_dict() for res in results.values()]
        rows.sort(key=lambda r: (r["best_fitness_mean"], r["time_seconds_mean"]))
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows

    def scalability_test(
        self,
        problem_sizes: Sequence[int] = (5, 10, 20, 40),
        n_runs: int = 2,
        n_routes: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Time each algorithm as the fleet grows.

        The original built a new problem only if it happened to expose
        ``set_size`` or ``n_var``; a FleetOptimizationProblem exposes neither,
        so every "size" ran the identical problem. A fresh problem is now built
        per size, which is the only way the numbers mean anything.
        """
        rows: List[Dict[str, Any]] = []
        for size in problem_sizes:
            problem = FleetOptimizationProblem(
                n_vessels=int(size),
                n_routes=min(int(n_routes), max(int(size), 1)),
                fuel_types=self.problem.fuel_types,
                seed=self.problem.seed,
            )
            runner = BenchmarkRunner(
                problem,
                self.algorithms,
                max_iterations=self.max_iterations,
                population_size=self.population_size,
                base_seed=self.base_seed,
            )
            for algorithm in self.algorithms:
                res = runner.run_single(algorithm, n_runs=n_runs)
                rows.append(
                    {
                        "algorithm": algorithm,
                        "problem_size": int(size),
                        "n_dimensions": problem.n_dimensions,
                        "time_seconds": round(res.avg_time_seconds, 4),
                        "evaluations": int(np.mean([r.n_evaluations for r in res.runs])),
                        "best_fitness": round(res.avg_best_fitness, 6),
                    }
                )
        return rows
