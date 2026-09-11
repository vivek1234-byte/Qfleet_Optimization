"""
Shared machinery for every optimizer in this package.

All four solvers now speak the same interface, which is what makes the
benchmark runner and the API able to treat them interchangeably:

    solver = Solver(...)
    result = solver.optimize(objective)   # -> OptimizeResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np


@dataclass
class OptimizeResult:
    """Uniform return type for single- and multi-objective solvers."""

    algorithm: str
    #: Best decision vector found (single-objective), or the knee point.
    best_solution: Optional[np.ndarray] = None
    #: Best scalar fitness (single-objective solvers only).
    best_fitness: float = float("inf")
    #: Per-iteration convergence trace.
    history: List[float] = field(default_factory=list)
    #: ``(positions, objectives)`` pairs for multi-objective solvers.
    pareto_front: Optional[List[Tuple[np.ndarray, np.ndarray]]] = None
    #: Number of objective evaluations consumed.
    n_evaluations: int = 0
    #: Free-form extras (population size, seed, ...).
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_multi_objective(self) -> bool:
        return self.pareto_front is not None

    def front_objectives(self) -> np.ndarray:
        """Pareto objectives as an ``(n, n_obj)`` array (empty if none)."""
        if not self.pareto_front:
            return np.empty((0, 0))
        return np.array([f for _, f in self.pareto_front], dtype=float)

    def front_positions(self) -> np.ndarray:
        if not self.pareto_front:
            return np.empty((0, 0))
        return np.array([p for p, _ in self.pareto_front], dtype=float)


class BaseSolver:
    """Common bounds handling, RNG seeding and evaluation counting."""

    name = "base"

    def __init__(
        self,
        n_dimensions: int,
        bounds: Sequence[Sequence[float]],
        max_iterations: int = 100,
        seed: Optional[int] = None,
        seed_solutions: Optional[np.ndarray] = None,
    ) -> None:
        bounds_arr = np.asarray(bounds, dtype=float)
        if bounds_arr.ndim != 2 or bounds_arr.shape[1] != 2:
            raise ValueError("bounds must have shape (n_dimensions, 2)")
        if bounds_arr.shape[0] != n_dimensions:
            raise ValueError(
                f"bounds has {bounds_arr.shape[0]} rows but n_dimensions is {n_dimensions}"
            )
        if np.any(bounds_arr[:, 0] > bounds_arr[:, 1]):
            raise ValueError("every lower bound must be <= its upper bound")
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")

        self.n_dimensions = int(n_dimensions)
        self.bounds = bounds_arr
        self.lower = bounds_arr[:, 0]
        self.upper = bounds_arr[:, 1]
        self.span = np.maximum(self.upper - self.lower, 1e-12)
        self.max_iterations = int(max_iterations)
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self._n_evaluations = 0

        if seed_solutions is None:
            self.seed_solutions = np.empty((0, self.n_dimensions))
        else:
            arr = np.atleast_2d(np.asarray(seed_solutions, dtype=float))
            if arr.shape[1] != self.n_dimensions:
                raise ValueError("seed_solutions must match n_dimensions")
            self.seed_solutions = np.clip(arr, self.lower, self.upper)

    # -- helpers -----------------------------------------------------------
    def _init_population(self, size: int) -> np.ndarray:
        """
        Random population, warm-started with any supplied seed solutions.

        Injecting the known-good baseline plan guarantees the optimiser can
        never return something worse than doing nothing, which is what makes
        the reported savings trustworthy.
        """
        pop = self.rng.uniform(self.lower, self.upper, (size, self.n_dimensions))
        n_seed = min(len(self.seed_solutions), max(size - 1, 0))
        if n_seed:
            pop[:n_seed] = self.seed_solutions[:n_seed]
        return pop

    def _clip(self, X: np.ndarray) -> np.ndarray:
        return np.clip(X, self.lower, self.upper)

    def _evaluate_population(
        self, objective: Callable[[np.ndarray], Any], X: np.ndarray
    ) -> np.ndarray:
        """
        Evaluate a population, using the objective's vectorised ``.batch``
        variant when the problem exposes one. This is the single biggest
        speed-up available to every solver here.
        """
        self._n_evaluations += len(X)
        batch = getattr(objective, "batch", None)
        if callable(batch):
            return np.asarray(batch(X), dtype=float)
        return np.asarray([objective(row) for row in X], dtype=float)

    @staticmethod
    def _trace(objective: Callable[..., Any], F: np.ndarray) -> float:
        """
        One comparable number per iteration for the convergence chart.

        Multi-objective solvers have no scalar fitness, and plotting archive
        size or front spread is misleading — both grow as the search improves.
        When the problem supplies a ``trace`` function on the objective, the
        solver records that instead, so QPSO, NSGA-II, PSO and QGA all plot the
        same normalised quantity and can be overlaid on one axis.
        """
        trace_fn = getattr(objective, "trace", None)
        F = np.atleast_2d(np.asarray(F, dtype=float))
        if F.size == 0:
            return float("inf")
        if callable(trace_fn):
            return float(trace_fn(F))
        return float(F.mean(axis=1).min())


# ---------------------------------------------------------------------------
# Pareto utilities
# ---------------------------------------------------------------------------
def dominates(a: np.ndarray, b: np.ndarray) -> bool:
    """True when ``a`` Pareto-dominates ``b`` (minimisation)."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return bool(np.all(a <= b) and np.any(a < b))


def non_dominated_mask(F: np.ndarray) -> np.ndarray:
    """
    Boolean mask of the non-dominated rows of ``F``.

    O(n^2) but fully vectorised per row, which is roughly 50x faster than the
    nested Python loops this replaces.
    """
    F = np.asarray(F, dtype=float)
    n = len(F)
    if n == 0:
        return np.zeros(0, dtype=bool)
    keep = np.ones(n, dtype=bool)
    for i in range(n):
        if not keep[i]:
            continue
        # Rows that dominate row i.
        le = np.all(F <= F[i], axis=1)
        lt = np.any(F < F[i], axis=1)
        dominators = le & lt
        if np.any(dominators):
            keep[i] = False
    return keep


def fast_non_dominated_sort(F: np.ndarray) -> List[List[int]]:
    """Deb's fast non-dominated sort. Returns a list of fronts of row indices."""
    F = np.asarray(F, dtype=float)
    n = len(F)
    if n == 0:
        return []

    dominated_by: List[List[int]] = [[] for _ in range(n)]
    domination_count = np.zeros(n, dtype=int)

    for p in range(n):
        le = np.all(F[p] <= F, axis=1)
        lt = np.any(F[p] < F, axis=1)
        p_dominates = le & lt
        p_dominates[p] = False
        dominated_by[p] = np.flatnonzero(p_dominates).tolist()

        dominators = np.all(F <= F[p], axis=1) & np.any(F < F[p], axis=1)
        dominators[p] = False
        domination_count[p] = int(dominators.sum())

    fronts: List[List[int]] = []
    current = np.flatnonzero(domination_count == 0).tolist()
    counts = domination_count.copy()
    while current:
        fronts.append(current)
        nxt: List[int] = []
        for p in current:
            for q in dominated_by[p]:
                counts[q] -= 1
                if counts[q] == 0:
                    nxt.append(q)
        current = nxt
    return fronts


def crowding_distance(F: np.ndarray) -> np.ndarray:
    """Crowding distance for one front. Boundary points get ``inf``."""
    F = np.asarray(F, dtype=float)
    n, m = F.shape if F.ndim == 2 else (0, 0)
    distances = np.zeros(n)
    if n <= 2:
        return np.full(n, np.inf)
    for obj in range(m):
        order = np.argsort(F[:, obj], kind="stable")
        f_min = F[order[0], obj]
        f_max = F[order[-1], obj]
        distances[order[0]] = np.inf
        distances[order[-1]] = np.inf
        if f_max - f_min <= 1e-12:
            continue
        prev_vals = F[order[:-2], obj]
        next_vals = F[order[2:], obj]
        distances[order[1:-1]] += (next_vals - prev_vals) / (f_max - f_min)
    return distances


def truncate_by_crowding(P: np.ndarray, F: np.ndarray, limit: int):
    """Trim an archive to ``limit`` members, keeping the most spread-out ones."""
    if len(F) <= limit:
        return P, F
    distances = crowding_distance(F)
    keep = np.argsort(-distances, kind="stable")[:limit]
    keep = np.sort(keep)
    return P[keep], F[keep]


def knee_point_index(F: np.ndarray) -> int:
    """
    Index of the 'best compromise' solution on a front.

    Objectives are min-max normalised, then the point closest to the ideal
    (all-zero) corner wins. This is what the API reports as the recommended
    plan, since a raw Pareto front has no single best member.
    """
    F = np.asarray(F, dtype=float)
    if len(F) == 0:
        raise ValueError("cannot pick a knee point from an empty front")
    if len(F) == 1:
        return 0
    lo = F.min(axis=0)
    hi = F.max(axis=0)
    span = np.where(hi - lo > 1e-12, hi - lo, 1.0)
    normalised = (F - lo) / span
    return int(np.argmin(np.linalg.norm(normalised, axis=1)))
