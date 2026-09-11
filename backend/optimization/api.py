"""
Optimization API.

The original router returned a hard-coded dictionary — the same three vessel
assignments, the same three Pareto points and ``"time_taken": 2.34`` — for
every request, and never imported a single solver. ``/compare`` likewise
returned four fixed numbers. Every response here now comes from an actual run
of the requested algorithm against a real fleet model.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from ..config import settings
    from ..core.errors import ComputationError, ValidationError
    from ..data.fleet_registry import registry_summary
    from ..data.fuel_database import fuel_names, get_fuel
    from .engine import ALGORITHM_IDS, list_algorithms, optimize, run_algorithm, summarise_run
    from .fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem
except ImportError:  # pragma: no cover
    from config import settings
    from core.errors import ComputationError, ValidationError
    from data.fleet_registry import registry_summary
    from data.fuel_database import fuel_names, get_fuel
    from optimization.engine import (
        ALGORITHM_IDS,
        list_algorithms,
        optimize,
        run_algorithm,
        summarise_run,
    )
    from optimization.fleet_problem import OBJECTIVE_NAMES, FleetOptimizationProblem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/optimization", tags=["Optimization"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class FleetConfig(BaseModel):
    """Problem sizing shared by the optimize and compare endpoints."""

    model_config = ConfigDict(extra="forbid")

    n_vessels: int = Field(10, ge=1, le=settings.MAX_VESSELS)
    n_routes: int = Field(5, ge=1, le=settings.MAX_ROUTES)
    max_iterations: int = Field(100, ge=5, le=settings.MAX_ITERATIONS)
    population_size: int = Field(60, ge=8, le=settings.MAX_POPULATION)
    fuel_types: Optional[List[str]] = Field(
        None, description=f"Subset of {', '.join(fuel_names())}. Omit for all fuels."
    )
    carbon_price_usd_per_ton: float = Field(
        0.0, ge=0, le=1000, description="Carbon price folded into the cost objective"
    )
    seed: Optional[int] = Field(42, ge=0, le=2**31 - 1, description="Set for reproducible runs")

    @field_validator("fuel_types")
    @classmethod
    def _known_fuels(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return None
        if not v:
            raise ValueError("fuel_types must not be an empty list; omit it to use all fuels")
        unknown = [name for name in v if get_fuel(name) is None]
        if unknown:
            raise ValueError(
                f"Unknown fuel(s): {', '.join(unknown)}. Available: {', '.join(fuel_names())}"
            )
        return v


class OptimizeRequest(FleetConfig):
    algorithm: str = Field("qpso", description=f"One of: {', '.join(ALGORITHM_IDS)}")
    objective_weights: Optional[List[float]] = Field(
        None,
        description=(
            "Relative weights for [fuel, CO2, cost] used by the single-objective "
            "solvers (PSO, QGA). Defaults to equal weighting."
        ),
    )
    include_plan: bool = Field(True, description="Include the full per-vessel deployment plan")

    @field_validator("algorithm")
    @classmethod
    def _known_algorithm(cls, v: str) -> str:
        key = (v or "").strip().lower()
        if key not in ALGORITHM_IDS:
            raise ValueError(f"algorithm must be one of: {', '.join(ALGORITHM_IDS)}")
        return key

    @field_validator("objective_weights")
    @classmethod
    def _check_weights(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is None:
            return None
        if len(v) != len(OBJECTIVE_NAMES):
            raise ValueError(
                f"objective_weights must have {len(OBJECTIVE_NAMES)} entries "
                f"({', '.join(OBJECTIVE_NAMES)})"
            )
        if any(w < 0 for w in v):
            raise ValueError("objective_weights must be non-negative")
        if sum(v) <= 0:
            raise ValueError("objective_weights must not sum to zero")
        return v


class CompareRequest(FleetConfig):
    algorithms: List[str] = Field(
        default_factory=lambda: list(ALGORITHM_IDS),
        description=f"Algorithms to compare. Any of: {', '.join(ALGORITHM_IDS)}",
    )

    @field_validator("algorithms")
    @classmethod
    def _known_algorithms(cls, v: List[str]) -> List[str]:
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/algorithms")
def get_algorithms() -> List[Dict[str, Any]]:
    """The solvers this build can run, with their capabilities."""
    return list_algorithms()


@router.get("/registry")
def get_registry() -> Dict[str, Any]:
    """
    The full vessel and trade-lane registry the problem builder draws from.

    Vessels are fictional Indian-flag ships across three classes; lanes are
    real port pairs with published sea distances (Suez for Europe, Malacca for
    East Asia). Useful for showing a jury exactly what is being scheduled.
    """
    return registry_summary()


@router.get("/fleet")
def get_fleet(
    n_vessels: int = Query(10, ge=1, le=settings.MAX_VESSELS),
    n_routes: int = Query(5, ge=1, le=settings.MAX_ROUTES),
    seed: int = Query(42, ge=0, le=2**31 - 1),
) -> Dict[str, Any]:
    """
    Inspect the fleet and route network a given configuration produces.

    Generation is deterministic for a seed, so the UI can show the exact
    vessels an optimisation run will be scheduling.
    """
    problem = FleetOptimizationProblem(n_vessels=n_vessels, n_routes=n_routes, seed=seed)
    summary = problem.summary()
    summary["baseline"] = problem.baseline()
    return summary


@router.post("/optimize")
def run_optimization(request: OptimizeRequest) -> Dict[str, Any]:
    """
    Run one algorithm and return the optimised deployment plan.

    The response includes the Pareto front, the convergence trace, the chosen
    compromise plan vessel by vessel, and the saving against a feasible
    do-nothing baseline.
    """
    try:
        return optimize(
            request.algorithm,
            n_vessels=request.n_vessels,
            n_routes=request.n_routes,
            fuel_types=request.fuel_types,
            max_iterations=request.max_iterations,
            population_size=request.population_size,
            carbon_price_usd_per_ton=request.carbon_price_usd_per_ton,
            weights=request.objective_weights,
            seed=request.seed,
            include_plan=request.include_plan,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - genuine solver failure
        logger.exception("optimization failed")
        raise ComputationError(f"Optimization failed: {exc}") from exc


@router.post("/compare")
def compare_algorithms(request: CompareRequest) -> Dict[str, Any]:
    """
    Run several algorithms on the *same* problem instance and rank them.

    Sharing one problem object matters: each solver is then judged on identical
    vessels, routes and demand, which the previous hard-coded response could
    not claim.
    """
    try:
        problem = FleetOptimizationProblem(
            n_vessels=request.n_vessels,
            n_routes=request.n_routes,
            fuel_types=request.fuel_types,
            seed=request.seed if request.seed is not None else 42,
            carbon_price_usd_per_ton=request.carbon_price_usd_per_ton,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    comparison: List[Dict[str, Any]] = []
    convergence: Dict[str, List[float]] = {}

    for algorithm in request.algorithms:
        try:
            result = run_algorithm(
                algorithm,
                problem,
                max_iterations=request.max_iterations,
                population_size=request.population_size,
                seed=request.seed,
            )
            summary = summarise_run(result, problem, include_plan=False)
        except Exception as exc:  # one bad solver must not sink the comparison
            logger.exception("algorithm %s failed during comparison", algorithm)
            comparison.append({"algorithm": algorithm, "error": str(exc), "failed": True})
            continue

        convergence[algorithm] = summary["convergence_history"]
        comparison.append(
            {
                "algorithm": algorithm,
                "algorithm_name": summary["algorithm_name"],
                "quantum_inspired": summary["quantum_inspired"],
                "multi_objective": summary["multi_objective"],
                "time_seconds": summary["elapsed_seconds"],
                "n_evaluations": summary["n_evaluations"],
                "pareto_size": summary["pareto_size"],
                "feasible": summary["feasible"],
                "objectives": summary["best_objectives"],
                "savings_pct": {
                    key: value["percent_saving"]
                    for key, value in summary["improvement_vs_baseline"].items()
                },
                "final_convergence": (
                    summary["convergence_history"][-1] if summary["convergence_history"] else None
                ),
                "failed": False,
            }
        )

    ranked = sorted(
        (row for row in comparison if not row.get("failed")),
        key=lambda r: (
            not r["feasible"],
            -sum(r["savings_pct"].values()),
            r["time_seconds"],
        ),
    )
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank

    return {
        "problem": {
            "n_vessels": problem.n_vessels,
            "n_routes": problem.n_routes,
            "n_dimensions": problem.n_dimensions,
            "fuel_types": problem.fuel_types,
            "seed": problem.seed,
        },
        "baseline_objectives": problem.baseline()["objectives"],
        "objective_names": list(OBJECTIVE_NAMES),
        "comparison": comparison,
        "convergence": convergence,
        "winner": ranked[0]["algorithm"] if ranked else None,
    }
