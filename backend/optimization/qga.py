"""
Quantum Genetic Algorithm (QGA).

Each individual is a register of qubits ``|psi> = alpha|0> + beta|1>``.
Measuring collapses the register to a bit string, which is decoded to real
values via Gray coding; a rotation gate then nudges every qubit toward the
best measurement seen so far.

Fixes over the original implementation:
  * the rotation gate was a Python double loop over ``pop_size * total_qubits``
    (~100k iterations per generation); it is now a single vectorised update
  * ``theta`` used ``sign(alpha * beta)``, which is 0 whenever a qubit has
    collapsed to a basis state, permanently freezing it. The standard lookup
    table is used instead, with the sign taken from the quadrant
  * amplitudes are renormalised every generation, so numerical drift cannot
    make ``alpha^2 + beta^2`` wander away from 1
  * Gray coding removes the Hamming cliffs of plain binary decoding
  * a catastrophe operator re-diffuses the population when it stagnates
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence

import numpy as np

try:
    from .base import BaseSolver, OptimizeResult
except ImportError:  # pragma: no cover
    from base import BaseSolver, OptimizeResult


class QGA(BaseSolver):
    name = "qga"

    def __init__(
        self,
        pop_size: int = 40,
        n_qubits_per_var: int = 10,
        n_variables: int = 1,
        bounds: Optional[Sequence[Sequence[float]]] = None,
        max_generations: int = 100,
        theta_start: float = 0.05 * np.pi,
        theta_end: float = 0.005 * np.pi,
        stagnation_limit: int = 25,
        seed: Optional[int] = None,
        seed_solutions=None,
        **_ignored,
    ) -> None:
        if bounds is None:
            raise ValueError("bounds are required")
        super().__init__(n_variables, bounds, max_generations, seed, seed_solutions)
        if pop_size < 2:
            raise ValueError("pop_size must be at least 2")
        if not 1 <= n_qubits_per_var <= 24:
            raise ValueError("n_qubits_per_var must be between 1 and 24")

        self.pop_size = int(pop_size)
        self.n_qubits_per_var = int(n_qubits_per_var)
        self.n_variables = int(n_variables)
        self.total_qubits = self.n_variables * self.n_qubits_per_var
        self.max_generations = int(max_generations)
        self.theta_start = float(theta_start)
        self.theta_end = float(theta_end)
        self.stagnation_limit = int(stagnation_limit)

        # Every qubit starts in an equal superposition.
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        self.alpha = np.full((self.pop_size, self.total_qubits), inv_sqrt2)
        self.beta = np.full((self.pop_size, self.total_qubits), inv_sqrt2)

        self.best_solution: Optional[np.ndarray] = None
        self.best_fitness = float("inf")
        self._best_bits = np.zeros(self.total_qubits)

        self._max_int = float((1 << self.n_qubits_per_var) - 1)
        self._powers = (1 << np.arange(self.n_qubits_per_var)[::-1]).astype(float)

        # Warm start: bias the registers toward a known-good solution so the
        # search begins from the baseline plan rather than from noise.
        if len(self.seed_solutions):
            self._best_bits = self._encode_bits(self.seed_solutions[0])
            self.quantum_rotation_gate(
                np.zeros((self.pop_size, self.total_qubits)),
                self._best_bits,
                self.theta_start * 2.0,
            )

    # -- encoding ----------------------------------------------------------
    def _encode_bits(self, x: np.ndarray) -> np.ndarray:
        """Real vector -> Gray-coded bit string (inverse of :meth:`decode`)."""
        x = np.clip(np.asarray(x, dtype=float), self.lower, self.upper)
        fraction = (x - self.lower) / self.span
        integers = np.rint(fraction * self._max_int).astype(np.int64)
        gray = integers ^ (integers >> 1)
        shifts = np.arange(self.n_qubits_per_var)[::-1]
        bits = ((gray[:, None] >> shifts[None, :]) & 1).astype(float)
        return bits.reshape(-1)

    # -- quantum operators -------------------------------------------------
    def measure(self) -> np.ndarray:
        """Collapse every register to a bit string."""
        r = self.rng.random((self.pop_size, self.total_qubits))
        return (r > self.alpha ** 2).astype(float)

    def _gray_to_binary(self, bits: np.ndarray) -> np.ndarray:
        """Vectorised Gray -> binary conversion along the last axis."""
        out = np.empty_like(bits)
        out[..., 0] = bits[..., 0]
        for k in range(1, bits.shape[-1]):
            out[..., k] = np.logical_xor(out[..., k - 1], bits[..., k])
        return out

    def decode(self, bits: np.ndarray) -> np.ndarray:
        """Bit strings -> real decision vectors inside the bounds."""
        reshaped = bits.reshape(len(bits), self.n_variables, self.n_qubits_per_var)
        binary = self._gray_to_binary(reshaped)
        integers = binary @ self._powers
        fraction = integers / self._max_int
        return self.lower[None, :] + fraction * self.span[None, :]

    def quantum_rotation_gate(self, bits: np.ndarray, best_bits: np.ndarray, theta_mag: float) -> None:
        """
        Rotate every qubit toward the best-known bit string.

        Vectorised form of the standard QGA lookup table: rotate positively
        when the individual reads 0 where the best reads 1, negatively in the
        mirror case, and not at all when they agree.
        """
        best = best_bits[None, :]
        direction = np.zeros_like(self.alpha)
        direction[(bits == 0) & (best == 1)] = 1.0
        direction[(bits == 1) & (best == 0)] = -1.0

        # Quadrant sign: rotating toward |1> means growing beta, which needs
        # the opposite sense in the second and fourth quadrants.
        quadrant = np.where(self.alpha * self.beta >= 0, 1.0, -1.0)
        theta = direction * theta_mag * quadrant

        cos_t, sin_t = np.cos(theta), np.sin(theta)
        new_alpha = self.alpha * cos_t - self.beta * sin_t
        new_beta = self.alpha * sin_t + self.beta * cos_t

        norm = np.sqrt(new_alpha ** 2 + new_beta ** 2)
        norm = np.where(norm < 1e-12, 1.0, norm)
        self.alpha = new_alpha / norm
        self.beta = new_beta / norm

        # Keep a little superposition alive so a qubit can always flip back.
        self.alpha = np.clip(self.alpha, -0.9995, 0.9995)
        self.beta = np.sign(self.beta) * np.sqrt(np.maximum(1.0 - self.alpha ** 2, 0.0))

    def _catastrophe(self) -> None:
        """Re-diffuse the worst half of the population after stagnation."""
        inv_sqrt2 = 1.0 / np.sqrt(2.0)
        half = self.pop_size // 2
        victims = self.rng.choice(self.pop_size, size=half, replace=False)
        self.alpha[victims] = inv_sqrt2
        self.beta[victims] = inv_sqrt2

    # -- main loop ---------------------------------------------------------
    def optimize(self, objective: Callable[[np.ndarray], float]) -> OptimizeResult:
        history: List[float] = []
        stagnant = 0

        for generation in range(self.max_generations):
            bits = self.measure()
            if generation == 0 and len(self.seed_solutions):
                # Force one individual to collapse onto the warm-start string,
                # so the incumbent starts at the baseline instead of at noise.
                bits[0] = self._best_bits
            values = self.decode(bits)
            fitness = self._evaluate_population(objective, values)

            best = int(np.argmin(fitness))
            if fitness[best] < self.best_fitness:
                self.best_fitness = float(fitness[best])
                self.best_solution = values[best].copy()
                self._best_bits = bits[best].copy()
                stagnant = 0
            else:
                stagnant += 1

            history.append(self.best_fitness)

            frac = generation / max(self.max_generations - 1, 1)
            theta_mag = self.theta_start - (self.theta_start - self.theta_end) * frac
            self.quantum_rotation_gate(bits, self._best_bits, theta_mag)

            if stagnant >= self.stagnation_limit:
                self._catastrophe()
                stagnant = 0

        if self.best_solution is None:  # pragma: no cover - defensive
            self.best_solution = self.lower.copy()

        return OptimizeResult(
            algorithm=self.name,
            best_solution=self.best_solution.copy(),
            best_fitness=float(self.best_fitness),
            history=[float(h) for h in history],
            n_evaluations=self._n_evaluations,
            meta={
                "pop_size": self.pop_size,
                "n_qubits_per_var": self.n_qubits_per_var,
                "seed": self.seed,
            },
        )
