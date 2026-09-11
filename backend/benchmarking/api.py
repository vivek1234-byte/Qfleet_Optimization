"""
Benchmarking API.

The original router never touched :class:`BenchmarkRunner`. ``/run`` echoed the
request back with ``"summary": "Benchmarking completed successfully."``,
``/results`` returned whatever ``/run`` last echoed (a module-level global that
any client could overwrite for every other client), and ``/convergence``
returned three hand-typed lists of ten numbers.

Every endpoint here runs the real suite: multiple seeded repetitions per
algorithm, hypervolume / IGD / IGD+ / spread / spacing against a shared
reference front, and a scalability sweep.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from ..config import settings
    from ..core.errors import ComputationError, NotFoundError, ValidationError
    from ..optimization.engine import ALGORITHM_IDS
    from ..optimization.fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
    from .runner import BenchmarkRunner
except ImportError:  # pragma: no cover
    from config import settings
    from core.errors import ComputationError, NotFoundError, ValidationError
    from optimization.engine import ALGORITHM_IDS
    from optimization.fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
    from benchmarking.runner import BenchmarkRunner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/benchmarks", tags=["Benchmarking"])


class _ResultStore:
    """
    Thread-safe holder for the most recent benchmark run.

    The previous ``latest_results = {}`` module global was mutated with a bare
    ``global`` statement from an async handler, so two concurrent requests could
    interleave and each read the other's results.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload: Optional[Dict[str, Any]] = None

    def set(self, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._payload = payload

    def get(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._payload


_store = _ResultStore()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithms: List[str] = Field(
        default_factory=lambda: list(ALGORITHM_IDS),
        description=f"Algorithms to benchmark. Any of: {', '.join(ALGORITHM_IDS)}",
    )
    n_runs: int = Field(3, ge=1, le=settings.MAX_BENCHMARK_RUNS)
    n_vessels: int = Field(10, ge=1, le=settings.MAX_VESSELS)
    n_routes: int = Field(5, ge=1, le=settings.MAX_ROUTES)
    max_iterations: int = Field(60, ge=5, le=settings.MAX_ITERATIONS)
    population_size: int = Field(40, ge=8, le=settings.MAX_POPULATION)
    seed: int = Field(1000, ge=0, le=2**31 - 1)

    @field_validator("algorithms")
    @classmethod
    def _known(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("algorithms must not be empty")
        cleaned, seen = [], set()
        for raw in v:
            key = (raw or "").strip().lower()
            if key not in ALGORITHM_IDS:
                raise ValueError(f"Unknown algorithm '{raw}'. Available: {', '.join(ALGORITHM_IDS)}")
            if key not in seen:
                seen.add(key)
                cleaned.append(key)
        return cleaned


class ScalabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithms: List[str] = Field(default_factory=lambda: list(ALGORITHM_IDS))
    problem_sizes: List[int] = Field(default_factory=lambda: [5, 10, 20, 40])
    n_runs: int = Field(2, ge=1, le=5)
    max_iterations: int = Field(40, ge=5, le=200)
    population_size: int = Field(30, ge=8, le=100)

    @field_validator("problem_sizes")
    @classmethod
    def _valid_sizes(cls, v: List[int]) -> List[int]:
        if not v:
            raise ValueError("problem_sizes must not be empty")
        if len(v) > 6:
            raise ValueError("at most 6 problem sizes per request")
        for size in v:
            if not 1 <= size <= settings.MAX_VESSELS:
                raise ValueError(f"problem sizes must be between 1 and {settings.MAX_VESSELS}")
        return sorted(set(v))

    @field_validator("algorithms")
    @classmethod
    def _known(cls, v: List[str]) -> List[str]:
        return BenchmarkRequest._known(v)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/run")
def run_benchmarks(request: BenchmarkRequest) -> Dict[str, Any]:
    """Run the benchmark suite and return (and cache) the scored results."""
    started = time.perf_counter()
    try:
        problem = FleetOptimizationProblem(
            n_vessels=request.n_vessels, n_routes=request.n_routes, seed=request.seed
        )
        runner = BenchmarkRunner(
            problem,
            request.algorithms,
            max_iterations=request.max_iterations,
            population_size=request.population_size,
            base_seed=request.seed,
        )
        results = runner.run_all(n_runs=request.n_runs)
        table = runner.comparison_table(results)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("benchmark run failed")
        raise ComputationError(f"Benchmark run failed: {exc}") from exc

    payload = {
        "status": "completed",
        "completed_at": time.time(),
        "wall_time_seconds": round(time.perf_counter() - started, 3),
        "config": request.model_dump(),
        "problem": {
            "n_vessels": problem.n_vessels,
            "n_routes": problem.n_routes,
            "n_dimensions": problem.n_dimensions,
        },
        "objective_names": list(OBJECTIVE_NAMES),
        "results": table,
        "convergence": {name: res.median_history for name, res in results.items()},
        "winner": table[0]["algorithm"] if table else None,
        "summary": _summarise(table),
    }
    _store.set(payload)
    return payload


def _summarise(table: List[Dict[str, Any]]) -> str:
    if not table:
        return "No results."
    best = table[0]
    parts = [
        f"{best['algorithm_name']} ranked first with a mean scalarised objective of "
        f"{best['best_fitness_mean']:.4f} over {best['n_runs']} run(s) "
        f"({best['time_seconds_mean']:.2f}s per run)."
    ]
    quantum = [r for r in table if r.get("quantum_inspired")]
    classical = [r for r in table if not r.get("quantum_inspired")]
    if quantum and classical:
        q_best = min(r["best_fitness_mean"] for r in quantum)
        c_best = min(r["best_fitness_mean"] for r in classical)
        if c_best > 0:
            delta = (c_best - q_best) / c_best * 100.0
            direction = "better" if delta > 0 else "worse"
            parts.append(
                f"The best quantum-inspired solver is {abs(delta):.1f}% {direction} than the "
                f"best classical baseline on this instance."
            )
    return " ".join(parts)


@router.get("/results")
def get_results() -> Dict[str, Any]:
    """The most recent benchmark run held by this server process."""
    payload = _store.get()
    if payload is None:
        raise NotFoundError(
            "No benchmark has been run yet on this server. POST /api/benchmarks/run first."
        )
    return payload


@router.get("/convergence")
def get_convergence() -> Dict[str, Any]:
    """
    Median convergence trace per algorithm from the last run.

    All algorithms report the same normalised scalar, so the curves are
    directly comparable on one axis.
    """
    payload = _store.get()
    if payload is None:
        raise NotFoundError(
            "No benchmark has been run yet on this server. POST /api/benchmarks/run first."
        )
    return {
        "metric": "normalised weighted objective (lower is better)",
        "completed_at": payload["completed_at"],
        "series": payload["convergence"],
    }


@router.post("/scalability")
def run_scalability(request: ScalabilityRequest) -> Dict[str, Any]:
    """Measure how run time and solution quality scale with fleet size."""
    try:
        seed_problem = FleetOptimizationProblem(n_vessels=max(request.problem_sizes), n_routes=5)
        runner = BenchmarkRunner(
            seed_problem,
            request.algorithms,
            max_iterations=request.max_iterations,
            population_size=request.population_size,
        )
        rows = runner.scalability_test(
            problem_sizes=request.problem_sizes, n_runs=request.n_runs
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        logger.exception("scalability test failed")
        raise ComputationError(f"Scalability test failed: {exc}") from exc

    return {
        "problem_sizes": request.problem_sizes,
        "algorithms": request.algorithms,
        "rows": rows,
    }


@router.get("/metrics-guide")
def metrics_guide() -> List[Dict[str, str]]:
    """What each quality indicator means — used by the UI's tooltips."""
    return [
        {
            "id": "hypervolume_mean",
            "name": "Hypervolume",
            "direction": "higher is better",
            "description": "Volume of objective space dominated by the front, relative to a shared reference point. Captures convergence and spread at once.",
        },
        {
            "id": "igd_mean",
            "name": "IGD",
            "direction": "lower is better",
            "description": "Mean distance from a reference front to the nearest solution found. Penalises gaps in coverage.",
        },
        {
            "id": "igd_plus_mean",
            "name": "IGD+",
            "direction": "lower is better",
            "description": "Pareto-compliant variant of IGD; only counts the dominated part of each distance.",
        },
        {
            "id": "spread_mean",
            "name": "Spread (Delta)",
            "direction": "lower is better",
            "description": "Deb's diversity metric. Low values mean solutions are evenly distributed along the front.",
        },
        {
            "id": "spacing_mean",
            "name": "Spacing",
            "direction": "lower is better",
            "description": "Normalised standard deviation of nearest-neighbour distances on the front.",
        },
        {
            "id": "best_fitness_mean",
            "name": "Scalarised objective",
            "direction": "lower is better",
            "description": "Equally weighted, baseline-normalised combination of fuel, CO2e and cost.",
        },
    ]
