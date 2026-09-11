"""
Quantum-inspired feature selection and hyperparameter tuning.

Fixes over the original:
  * **Contraction coefficient was inverted.** ``L = (1/alpha) * |x - mbest|``
    with ``alpha`` falling from 1.0 to 0.5 makes the step size *grow* from 1x to
    2x over the run, so the swarm diverged exactly when it should have been
    converging. QPSO wants a shrinking ``beta``.
  * **No evaluation cache.** The feature selector maps particles to a binary
    mask, and many particles collapse to the same mask — but every one of them
    triggered a fresh XGBoost fit. Default settings meant 600 model fits, most
    of them duplicates. Results are now memoised per mask.
  * ``gbest`` started as an all-zero vector, which decodes to "no features
    selected"; it is now seeded from the first real evaluation.
  * Both classes report a convergence history and honour a random seed.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)


class _QPSOSwarm:
    """Shared QPSO update rule for both selectors below."""

    def __init__(self, n_particles: int, n_dims: int, seed: Optional[int] = None) -> None:
        self.rng = np.random.default_rng(seed)
        self.n_particles = n_particles
        self.n_dims = n_dims
        self.particles = self.rng.random((n_particles, n_dims))
        self.pbest = self.particles.copy()
        self.pbest_fitness = np.full(n_particles, np.inf)
        self.gbest = self.particles[0].copy()
        self.gbest_fitness = np.inf

    def register(self, index: int, fitness: float) -> None:
        if fitness < self.pbest_fitness[index]:
            self.pbest_fitness[index] = fitness
            self.pbest[index] = self.particles[index].copy()
        if fitness < self.gbest_fitness:
            self.gbest_fitness = fitness
            self.gbest = self.particles[index].copy()

    def step(self, iteration: int, max_iterations: int) -> None:
        # beta shrinks 1.0 -> 0.4: wide exploration first, fine search later.
        beta = 1.0 - 0.6 * (iteration / max(max_iterations - 1, 1))
        mbest = self.pbest.mean(axis=0)
        phi = self.rng.random((self.n_particles, self.n_dims))
        attractor = phi * self.pbest + (1.0 - phi) * self.gbest
        u = np.clip(self.rng.random((self.n_particles, self.n_dims)), 1e-12, 1.0)
        L = beta * np.abs(self.particles - mbest)
        sign = np.where(self.rng.random((self.n_particles, self.n_dims)) > 0.5, 1.0, -1.0)
        self.particles = np.clip(attractor + sign * L * np.log(1.0 / u), 0.0, 1.0)


class QuantumFeatureSelector:
    """
    QPSO-driven binary feature selection.

    Fitness is ``-R2`` on a held-out split, with a small penalty per selected
    feature so that ties are broken toward smaller, cheaper models.
    """

    def __init__(
        self,
        n_features: int,
        n_particles: int = 15,
        max_iterations: int = 20,
        sparsity_penalty: float = 0.002,
        seed: Optional[int] = 42,
    ) -> None:
        if n_features < 1:
            raise ValueError("n_features must be at least 1")
        self.n_features = int(n_features)
        self.n_particles = int(n_particles)
        self.max_iterations = int(max_iterations)
        self.sparsity_penalty = float(sparsity_penalty)
        self.seed = seed
        self.convergence_history: List[float] = []
        self.cache_hits = 0
        self.evaluations = 0

    def _fitness(
        self, mask: np.ndarray, X_train, y_train, X_test, y_test, cache: Dict[Tuple[int, ...], float]
    ) -> float:
        key = tuple(int(b) for b in mask)
        if key in cache:
            self.cache_hits += 1
            return cache[key]

        self.evaluations += 1
        columns = mask.astype(bool)
        model = xgb.XGBRegressor(
            n_estimators=60,
            max_depth=3,
            learning_rate=0.15,
            n_jobs=-1,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train[:, columns], y_train)
        r2 = r2_score(y_test, model.predict(X_test[:, columns]))
        fitness = -r2 + self.sparsity_penalty * columns.sum()
        cache[key] = fitness
        return fitness

    def select_features(
        self, X: np.ndarray, y: np.ndarray, test_size: float = 0.2
    ) -> Dict[str, Any]:
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        if X.ndim != 2 or X.shape[1] != self.n_features:
            raise ValueError(f"X must be 2-D with {self.n_features} columns")
        if len(X) != len(y):
            raise ValueError("X and y must have the same number of rows")

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42
        )
        swarm = _QPSOSwarm(self.n_particles, self.n_features, self.seed)
        cache: Dict[Tuple[int, ...], float] = {}
        started = time.perf_counter()

        for iteration in range(self.max_iterations):
            for p in range(self.n_particles):
                mask = (swarm.particles[p] > 0.5).astype(int)
                if mask.sum() == 0:
                    # Never evaluate an empty feature set; force one column in.
                    mask[swarm.rng.integers(0, self.n_features)] = 1
                fitness = self._fitness(mask, X_train, y_train, X_test, y_test, cache)
                swarm.register(p, fitness)
            self.convergence_history.append(float(swarm.gbest_fitness))
            swarm.step(iteration, self.max_iterations)

        best_mask = (swarm.gbest > 0.5).astype(int)
        if best_mask.sum() == 0:  # pragma: no cover - defensive
            best_mask[0] = 1
        selected = np.flatnonzero(best_mask).tolist()
        best_r2 = -(swarm.gbest_fitness - self.sparsity_penalty * len(selected))

        logger.info(
            "feature selection: %d/%d features, R2=%.4f, %d fits (%d cache hits) in %.1fs",
            len(selected),
            self.n_features,
            best_r2,
            self.evaluations,
            self.cache_hits,
            time.perf_counter() - started,
        )
        return {
            "selected_indices": selected,
            "n_selected": len(selected),
            "best_r2": float(best_r2),
            "convergence_history": self.convergence_history,
            "model_fits": self.evaluations,
            "cache_hits": self.cache_hits,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }


class QuantumHyperparamTuner:
    """QPSO-driven hyperparameter search for XGBoost. Minimises validation RMSE."""

    BOUNDS: Dict[str, Tuple[float, float]] = {
        "n_estimators": (50.0, 500.0),
        "max_depth": (3.0, 12.0),
        "learning_rate": (0.01, 0.3),
        "min_child_weight": (1.0, 10.0),
        "subsample": (0.5, 1.0),
        "colsample_bytree": (0.5, 1.0),
    }
    INTEGER_KEYS = {"n_estimators", "max_depth", "min_child_weight"}

    def __init__(
        self, n_particles: int = 10, max_iterations: int = 12, seed: Optional[int] = 42
    ) -> None:
        self.n_particles = int(n_particles)
        self.max_iterations = int(max_iterations)
        self.seed = seed
        self.keys = list(self.BOUNDS.keys())
        self.dim = len(self.keys)
        self.convergence_history: List[float] = []
        self.evaluations = 0
        self.cache_hits = 0

    def _map_to_hyperparams(self, particle: np.ndarray) -> Dict[str, float]:
        params: Dict[str, float] = {}
        for i, key in enumerate(self.keys):
            low, high = self.BOUNDS[key]
            value = low + float(np.clip(particle[i], 0.0, 1.0)) * (high - low)
            params[key] = int(round(value)) if key in self.INTEGER_KEYS else round(value, 4)
        return params

    def tune(self, X_train, y_train, X_val, y_val) -> Dict[str, Any]:
        swarm = _QPSOSwarm(self.n_particles, self.dim, self.seed)
        cache: Dict[Tuple, float] = {}
        started = time.perf_counter()

        for iteration in range(self.max_iterations):
            for p in range(self.n_particles):
                params = self._map_to_hyperparams(swarm.particles[p])
                key = tuple(sorted(params.items()))
                if key in cache:
                    self.cache_hits += 1
                    rmse = cache[key]
                else:
                    self.evaluations += 1
                    model = xgb.XGBRegressor(
                        **params, n_jobs=-1, random_state=42, verbosity=0
                    )
                    model.fit(X_train, y_train)
                    rmse = float(np.sqrt(mean_squared_error(y_val, model.predict(X_val))))
                    cache[key] = rmse
                swarm.register(p, rmse)
            self.convergence_history.append(float(swarm.gbest_fitness))
            swarm.step(iteration, self.max_iterations)

        best_params = self._map_to_hyperparams(swarm.gbest)
        logger.info(
            "hyperparameter tuning: RMSE=%.4f with %s (%d fits, %d cache hits) in %.1fs",
            swarm.gbest_fitness,
            best_params,
            self.evaluations,
            self.cache_hits,
            time.perf_counter() - started,
        )
        return {
            "best_params": best_params,
            "best_rmse": float(swarm.gbest_fitness),
            "convergence_history": self.convergence_history,
            "model_fits": self.evaluations,
            "cache_hits": self.cache_hits,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
