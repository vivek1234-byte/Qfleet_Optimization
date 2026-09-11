"""
Standard Particle Swarm Optimization — the classical baseline the
quantum-inspired solvers are measured against.

Fixes over the original implementation:
  * velocity clamping, so particles cannot fly arbitrarily far in one step
  * linearly decreasing inertia weight (0.9 -> 0.4), the standard schedule
  * ``gbest`` is initialised before it is used instead of being ``None``
  * bounce-back on the bounds instead of a bare clip, which otherwise pins
    the whole swarm to the box corners
  * seedable RNG and a uniform :class:`OptimizeResult`
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

import numpy as np

try:
    from .base import BaseSolver, OptimizeResult
except ImportError:  # pragma: no cover
    from base import BaseSolver, OptimizeResult


class PSO(BaseSolver):
    name = "pso"

    def __init__(
        self,
        n_particles: int = 40,
        n_dimensions: int = 1,
        bounds: Optional[Sequence[Sequence[float]]] = None,
        max_iterations: int = 100,
        w: float = 0.72,
        c1: float = 1.49,
        c2: float = 1.49,
        w_start: float = 0.9,
        w_end: float = 0.4,
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
        self.w = float(w)
        self.c1 = float(c1)
        self.c2 = float(c2)
        self.w_start = float(w_start)
        self.w_end = float(w_end)
        self.v_max = 0.2 * self.span

        self.positions = self._init_population(self.n_particles)
        self.velocities = self.rng.uniform(-1, 1, self.positions.shape) * self.v_max
        self.pbest_positions = self.positions.copy()
        self.pbest_fitness = np.full(self.n_particles, np.inf)
        self.gbest_position = self.positions[0].copy()
        self.gbest_fitness = np.inf

    def optimize(self, objective: Callable[[np.ndarray], float]) -> OptimizeResult:
        history = []

        for t in range(self.max_iterations):
            fitness = self._evaluate_population(objective, self.positions)

            improved = fitness < self.pbest_fitness
            self.pbest_positions[improved] = self.positions[improved]
            self.pbest_fitness[improved] = fitness[improved]

            best = int(np.argmin(self.pbest_fitness))
            if self.pbest_fitness[best] < self.gbest_fitness:
                self.gbest_fitness = float(self.pbest_fitness[best])
                self.gbest_position = self.pbest_positions[best].copy()

            # Linearly decreasing inertia: explore early, exploit late.
            w = self.w_start - (self.w_start - self.w_end) * (t / max(self.max_iterations - 1, 1))

            r1 = self.rng.random(self.positions.shape)
            r2 = self.rng.random(self.positions.shape)
            self.velocities = (
                w * self.velocities
                + self.c1 * r1 * (self.pbest_positions - self.positions)
                + self.c2 * r2 * (self.gbest_position - self.positions)
            )
            self.velocities = np.clip(self.velocities, -self.v_max, self.v_max)

            self.positions = self.positions + self.velocities

            # Bounce off the walls and kill the offending velocity component,
            # so particles do not stack up on the boundary.
            below = self.positions < self.lower
            above = self.positions > self.upper
            self.positions = np.where(below, self.lower + (self.lower - self.positions) * 0.5, self.positions)
            self.positions = np.where(above, self.upper - (self.positions - self.upper) * 0.5, self.positions)
            self.positions = self._clip(self.positions)
            self.velocities[below | above] *= -0.5

            history.append(self.gbest_fitness)

        return OptimizeResult(
            algorithm=self.name,
            best_solution=self.gbest_position.copy(),
            best_fitness=float(self.gbest_fitness),
            history=[float(h) for h in history],
            n_evaluations=self._n_evaluations,
            meta={"n_particles": self.n_particles, "seed": self.seed},
        )
