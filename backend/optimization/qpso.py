"""
Quantum-behaved Particle Swarm Optimization (QPSO), single- and
multi-objective.

Sun, Feng & Xu's QPSO drops velocity entirely: each particle is a quantum
delta-potential well centred on a stochastic attractor ``p``, and its next
position is drawn from that well:

    x = p +/- (beta * |mbest - x|) * ln(1/u),   u ~ U(0,1)

Fixes over the original implementation:
  * ``beta`` now decays from 1.0 to 0.5 (the published schedule) instead of
    hitting exactly 0 on the last iteration, which froze the swarm
  * the multi-objective archive is bounded and pruned by crowding distance;
    before, it grew without limit and the O(n^2) filter made late iterations
    quadratically slower
  * archive leaders are picked by crowding distance rather than uniformly, so
    the front spreads out instead of clumping
  * the convergence trace records real hypervolume-proxy progress, not just
    the archive size
  * seedable RNG and vectorised population evaluation
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

try:
    from .base import (
        BaseSolver,
        OptimizeResult,
        crowding_distance,
        non_dominated_mask,
        truncate_by_crowding,
    )
except ImportError:  # pragma: no cover
    from base import (
        BaseSolver,
        OptimizeResult,
        crowding_distance,
        non_dominated_mask,
        truncate_by_crowding,
    )


class QPSO(BaseSolver):
    """Single-objective QPSO."""

    name = "qpso"

    def __init__(
        self,
        n_particles: int = 40,
        n_dimensions: int = 1,
        bounds: Optional[Sequence[Sequence[float]]] = None,
        max_iterations: int = 100,
        alpha_start: float = 1.0,
        alpha_end: float = 0.5,
        seed: Optional[int] = None,
        seed_solutions=None,
        **_ignored,
    ) -> None:
        if bounds is None:
            raise ValueError("bounds are required")
        super().__init__(n_dimensions, bounds, max_iterations, seed, seed_solutions)
        if n_particles < 2:
            raise ValueError("n_particles must be at least 2")
        self.n_particles = int(n_particles)
        self.alpha_start = float(alpha_start)
        self.alpha_end = float(alpha_end)

        self.positions = self._init_population(self.n_particles)
        self.pbest_positions = self.positions.copy()
        self.pbest_fitness = np.full(self.n_particles, np.inf)
        self.gbest_position = self.positions[0].copy()
        self.gbest_fitness = np.inf

    def _alpha(self, t: int) -> float:
        frac = t / max(self.max_iterations - 1, 1)
        return self.alpha_start - (self.alpha_start - self.alpha_end) * frac

    def optimize(self, objective: Callable[[np.ndarray], float]) -> OptimizeResult:
        history: List[float] = []

        for t in range(self.max_iterations):
            fitness = self._evaluate_population(objective, self.positions)

            improved = fitness < self.pbest_fitness
            self.pbest_positions[improved] = self.positions[improved]
            self.pbest_fitness[improved] = fitness[improved]

            best = int(np.argmin(self.pbest_fitness))
            if self.pbest_fitness[best] < self.gbest_fitness:
                self.gbest_fitness = float(self.pbest_fitness[best])
                self.gbest_position = self.pbest_positions[best].copy()

            mbest = self.pbest_positions.mean(axis=0)
            beta = self._alpha(t)

            phi = self.rng.random(self.positions.shape)
            attractor = phi * self.pbest_positions + (1.0 - phi) * self.gbest_position
            u = np.clip(self.rng.random(self.positions.shape), 1e-12, 1.0)
            L = beta * np.abs(mbest - self.positions)
            sign = np.where(self.rng.random(self.positions.shape) > 0.5, 1.0, -1.0)

            self.positions = self._clip(attractor + sign * L * np.log(1.0 / u))
            history.append(self.gbest_fitness)

        return OptimizeResult(
            algorithm=self.name,
            best_solution=self.gbest_position.copy(),
            best_fitness=float(self.gbest_fitness),
            history=[float(h) for h in history],
            n_evaluations=self._n_evaluations,
            meta={"n_particles": self.n_particles, "seed": self.seed},
        )


class MultiObjectiveQPSO(BaseSolver):
    """QPSO with an external, crowding-pruned Pareto archive (MOQPSO)."""

    name = "qpso"

    def __init__(
        self,
        n_particles: int = 60,
        n_dimensions: int = 1,
        bounds: Optional[Sequence[Sequence[float]]] = None,
        max_iterations: int = 100,
        alpha_start: float = 1.0,
        alpha_end: float = 0.5,
        archive_size: int = 100,
        seed: Optional[int] = None,
        seed_solutions=None,
        **_ignored,
    ) -> None:
        if bounds is None:
            raise ValueError("bounds are required")
        super().__init__(n_dimensions, bounds, max_iterations, seed, seed_solutions)
        if n_particles < 2:
            raise ValueError("n_particles must be at least 2")
        self.n_particles = int(n_particles)
        self.alpha_start = float(alpha_start)
        self.alpha_end = float(alpha_end)
        self.archive_size = max(int(archive_size), 10)

        self.positions = self._init_population(self.n_particles)
        self.pbest_positions = self.positions.copy()
        self.pbest_fitness: Optional[np.ndarray] = None
        self.archive_positions = np.empty((0, self.n_dimensions))
        self.archive_objectives = np.empty((0, 0))

    # -- archive -----------------------------------------------------------
    def _update_archive(self, P: np.ndarray, F: np.ndarray) -> None:
        if self.archive_objectives.size:
            allP = np.vstack([self.archive_positions, P])
            allF = np.vstack([self.archive_objectives, F])
        else:
            allP, allF = P.copy(), F.copy()

        # Drop exact duplicates first; they inflate the O(n^2) filter.
        _, unique_idx = np.unique(np.round(allF, 6), axis=0, return_index=True)
        unique_idx = np.sort(unique_idx)
        allP, allF = allP[unique_idx], allF[unique_idx]

        keep = non_dominated_mask(allF)
        allP, allF = allP[keep], allF[keep]
        self.archive_positions, self.archive_objectives = truncate_by_crowding(
            allP, allF, self.archive_size
        )

    def _pick_leaders(self, n: int) -> np.ndarray:
        """Roulette-select archive leaders, favouring sparse regions."""
        size = len(self.archive_positions)
        if size == 0:
            return self.pbest_positions[:n]
        distances = crowding_distance(self.archive_objectives)
        finite = distances[np.isfinite(distances)]
        cap = finite.max() if finite.size else 1.0
        weights = np.where(np.isfinite(distances), distances, cap * 2.0) + 1e-9
        weights = weights / weights.sum()
        idx = self.rng.choice(size, size=n, p=weights)
        return self.archive_positions[idx]

    # -- diversity ---------------------------------------------------------
    def _mutate(self, iteration: int) -> None:
        """
        Coello's MOPSO mutation operator, with a decaying rate.

        Without it the swarm collapses onto a handful of neighbouring plans and
        the "Pareto front" is three points in a cluster rather than a usable
        trade-off curve. The rate falls from 50% of particles to zero over the
        run, so early iterations explore and late ones refine.
        """
        rate = 0.5 * (1.0 - iteration / max(self.max_iterations - 1, 1)) ** 1.5
        if rate <= 0.0:
            return
        chosen = self.rng.random(self.n_particles) < rate
        if not np.any(chosen):
            return

        # Perturb a shrinking window around each selected particle's position.
        width = self.span * rate
        noise = self.rng.uniform(-1.0, 1.0, (int(chosen.sum()), self.n_dimensions)) * width
        self.positions[chosen] = self._clip(self.positions[chosen] + noise)

    # -- main loop ---------------------------------------------------------
    def optimize(self, objective: Callable[[np.ndarray], np.ndarray]) -> OptimizeResult:
        history: List[float] = []

        F = self._evaluate_population(objective, self.positions)
        F = np.atleast_2d(F)
        self.pbest_fitness = F.copy()
        self._update_archive(self.positions, F)

        for t in range(self.max_iterations):
            F = np.atleast_2d(self._evaluate_population(objective, self.positions))

            # Personal best update under Pareto dominance, with a coin flip
            # for mutually non-dominated pairs (standard MOPSO practice).
            better = np.all(F <= self.pbest_fitness, axis=1) & np.any(F < self.pbest_fitness, axis=1)
            worse = np.all(self.pbest_fitness <= F, axis=1) & np.any(self.pbest_fitness < F, axis=1)
            tie = ~better & ~worse & (self.rng.random(len(F)) > 0.5)
            replace = better | tie
            self.pbest_positions[replace] = self.positions[replace]
            self.pbest_fitness[replace] = F[replace]

            self._update_archive(self.positions, F)

            mbest = self.pbest_positions.mean(axis=0)
            beta = self.alpha_start - (self.alpha_start - self.alpha_end) * (
                t / max(self.max_iterations - 1, 1)
            )

            leaders = self._pick_leaders(self.n_particles)
            phi = self.rng.random(self.positions.shape)
            attractor = phi * self.pbest_positions + (1.0 - phi) * leaders
            u = np.clip(self.rng.random(self.positions.shape), 1e-12, 1.0)
            L = beta * np.abs(mbest - self.positions)
            sign = np.where(self.rng.random(self.positions.shape) > 0.5, 1.0, -1.0)

            self.positions = self._clip(attractor + sign * L * np.log(1.0 / u))
            self._mutate(t)

            # Best scalarised value on the archive — the same quantity the
            # single-objective solvers report, so the curves are comparable.
            best_so_far = self._trace(objective, self.archive_objectives)
            history.append(min(best_so_far, history[-1]) if history else best_so_far)

        front = [
            (self.archive_positions[i].copy(), self.archive_objectives[i].copy())
            for i in range(len(self.archive_positions))
        ]
        return OptimizeResult(
            algorithm=self.name,
            pareto_front=front,
            history=[float(h) for h in history],
            n_evaluations=self._n_evaluations,
            meta={
                "n_particles": self.n_particles,
                "archive_size": len(front),
                "seed": self.seed,
            },
        )
