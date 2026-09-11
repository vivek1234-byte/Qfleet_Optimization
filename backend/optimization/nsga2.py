"""
NSGA-II — the classical multi-objective baseline.

Fixes over the original implementation:
  * **Mutation did nothing.** The polynomial-mutation loop wrote to the loop
    variable (``for c in [c1, c2]: c = c + delta * ...``), which rebinds the
    name and discards the result. The offspring were pure crossover, so the
    algorithm could not escape the initial population's support.
  * Mutation was gated by a single coin flip for the entire vector rather than
    per gene, and the perturbation ignored the distance to each bound.
  * The environmental-selection loop indexed ``combined_fronts[i]`` without a
    length guard and raised ``IndexError`` whenever the fronts filled the new
    population exactly.
  * Crowding distance was recomputed with a Python triple loop; it is now
    vectorised in :mod:`optimization.base`.
  * SBX now uses proper distribution indices and per-gene bound handling.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence

import numpy as np

try:
    from .base import (
        BaseSolver,
        OptimizeResult,
        crowding_distance,
        fast_non_dominated_sort,
    )
except ImportError:  # pragma: no cover
    from base import BaseSolver, OptimizeResult, crowding_distance, fast_non_dominated_sort


class NSGA2(BaseSolver):
    name = "nsga2"

    def __init__(
        self,
        pop_size: int = 60,
        n_dimensions: int = 1,
        bounds: Optional[Sequence[Sequence[float]]] = None,
        max_generations: int = 100,
        n_objectives: int = 3,
        crossover_prob: float = 0.9,
        eta_crossover: float = 20.0,
        mutation_prob: Optional[float] = None,
        eta_mutation: float = 20.0,
        seed: Optional[int] = None,
        seed_solutions=None,
        **_ignored,
    ) -> None:
        if bounds is None:
            raise ValueError("bounds are required")
        super().__init__(n_dimensions, bounds, max_generations, seed, seed_solutions)
        if pop_size < 4:
            raise ValueError("pop_size must be at least 4")
        # An even population keeps the pairwise crossover simple.
        self.pop_size = int(pop_size) + (int(pop_size) % 2)
        self.max_generations = int(max_generations)
        self.n_objectives = int(n_objectives)
        self.crossover_prob = float(crossover_prob)
        self.eta_crossover = float(eta_crossover)
        self.mutation_prob = (
            float(mutation_prob) if mutation_prob is not None else 1.0 / self.n_dimensions
        )
        self.eta_mutation = float(eta_mutation)

        self.population = self._init_population(self.pop_size)
        self.fitness: Optional[np.ndarray] = None

    # -- variation ---------------------------------------------------------
    def _sbx(self, parents: np.ndarray) -> np.ndarray:
        """Simulated binary crossover, vectorised over parent pairs."""
        p1 = parents[0::2]
        p2 = parents[1::2]
        n_pairs, n_dim = p1.shape

        u = self.rng.random((n_pairs, n_dim))
        beta = np.where(
            u <= 0.5,
            (2.0 * u) ** (1.0 / (self.eta_crossover + 1.0)),
            (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (self.eta_crossover + 1.0)),
        )
        do_crossover = self.rng.random((n_pairs, 1)) < self.crossover_prob
        # Per-gene 50% swap, as in Deb's reference implementation.
        gene_mask = self.rng.random((n_pairs, n_dim)) < 0.5
        active = do_crossover & gene_mask

        c1 = np.where(active, 0.5 * ((1 + beta) * p1 + (1 - beta) * p2), p1)
        c2 = np.where(active, 0.5 * ((1 - beta) * p1 + (1 + beta) * p2), p2)

        offspring = np.empty_like(parents)
        offspring[0::2] = c1
        offspring[1::2] = c2
        return offspring

    def _polynomial_mutation(self, X: np.ndarray) -> np.ndarray:
        """Polynomial mutation. This is the operator the original code lost."""
        X = X.copy()
        mutate = self.rng.random(X.shape) < self.mutation_prob
        if not np.any(mutate):
            return X

        u = self.rng.random(X.shape)
        # Distance to each bound, normalised.
        delta1 = (X - self.lower) / self.span
        delta2 = (self.upper - X) / self.span
        mut_pow = 1.0 / (self.eta_mutation + 1.0)

        deltaq = np.where(
            u <= 0.5,
            (2.0 * u + (1.0 - 2.0 * u) * (1.0 - delta1) ** (self.eta_mutation + 1.0)) ** mut_pow - 1.0,
            1.0
            - (
                2.0 * (1.0 - u)
                + 2.0 * (u - 0.5) * (1.0 - delta2) ** (self.eta_mutation + 1.0)
            )
            ** mut_pow,
        )
        X = np.where(mutate, X + deltaq * self.span, X)
        return self._clip(X)

    def _tournament(self, ranks: np.ndarray, distances: np.ndarray) -> np.ndarray:
        """Binary crowded-comparison tournament selection."""
        a = self.rng.integers(0, self.pop_size, self.pop_size)
        b = self.rng.integers(0, self.pop_size, self.pop_size)
        a_wins = (ranks[a] < ranks[b]) | ((ranks[a] == ranks[b]) & (distances[a] > distances[b]))
        winners = np.where(a_wins, a, b)
        return self.population[winners]

    # -- main loop ---------------------------------------------------------
    def optimize(self, objectives_func: Callable[[np.ndarray], np.ndarray]) -> OptimizeResult:
        history: List[float] = []

        self.fitness = np.atleast_2d(self._evaluate_population(objectives_func, self.population))

        for _ in range(self.max_generations):
            fronts = fast_non_dominated_sort(self.fitness)
            ranks = np.zeros(len(self.population))
            distances = np.zeros(len(self.population))
            for rank, front in enumerate(fronts):
                idx = np.array(front, dtype=int)
                ranks[idx] = rank
                distances[idx] = crowding_distance(self.fitness[idx])
            # inf breaks the comparison arithmetic; map it to a large finite value.
            finite = distances[np.isfinite(distances)]
            cap = (finite.max() if finite.size else 1.0) * 2.0 + 1.0
            distances = np.where(np.isfinite(distances), distances, cap)

            parents = self._tournament(ranks, distances)
            offspring = self._clip(self._sbx(parents))
            offspring = self._polynomial_mutation(offspring)
            offspring_fitness = np.atleast_2d(
                self._evaluate_population(objectives_func, offspring)
            )

            combined_pop = np.vstack([self.population, offspring])
            combined_fit = np.vstack([self.fitness, offspring_fitness])
            combined_fronts = fast_non_dominated_sort(combined_fit)

            selected: List[int] = []
            for front in combined_fronts:
                if len(selected) + len(front) <= self.pop_size:
                    selected.extend(front)
                    if len(selected) == self.pop_size:
                        break
                else:
                    # Partial front: keep the most spread-out members.
                    idx = np.array(front, dtype=int)
                    dist = crowding_distance(combined_fit[idx])
                    order = np.argsort(-dist, kind="stable")
                    remaining = self.pop_size - len(selected)
                    selected.extend(idx[order[:remaining]].tolist())
                    break

            # Defensive: pad if the fronts somehow under-filled the population.
            while len(selected) < self.pop_size:
                selected.append(int(self.rng.integers(0, len(combined_pop))))

            chosen = np.array(selected[: self.pop_size], dtype=int)
            self.population = combined_pop[chosen]
            self.fitness = combined_fit[chosen]

            best_so_far = self._trace(objectives_func, self.fitness)
            history.append(min(best_so_far, history[-1]) if history else best_so_far)

        final_fronts = fast_non_dominated_sort(self.fitness)
        best_front = np.array(final_fronts[0], dtype=int) if final_fronts else np.array([], dtype=int)
        pareto = [
            (self.population[i].copy(), self.fitness[i].copy()) for i in best_front
        ]

        return OptimizeResult(
            algorithm=self.name,
            pareto_front=pareto,
            history=[float(h) for h in history],
            n_evaluations=self._n_evaluations,
            meta={"pop_size": self.pop_size, "front_size": len(pareto), "seed": self.seed},
        )
