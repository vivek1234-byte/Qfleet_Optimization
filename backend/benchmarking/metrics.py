"""
Quality indicators for comparing multi-objective solvers.

The original module silently returned ``0.0`` for hypervolume whenever pymoo
was missing, which is indistinguishable from a genuinely empty front, and its
``spread`` returned only the standard deviation of nearest-neighbour distances
while computing (and discarding) the mean. Both now have honest, self-contained
implementations, and every function states its assumptions.

All indicators assume **minimisation**.
"""
from __future__ import annotations

import itertools
import logging
from typing import Dict, List, Optional, Sequence, Union

import numpy as np

logger = logging.getLogger(__name__)


def _as_front(front) -> np.ndarray:
    F = np.atleast_2d(np.asarray(front, dtype=float))
    if F.size == 0:
        return np.empty((0, 0))
    return F[np.all(np.isfinite(F), axis=1)]


def reference_point(fronts: Sequence[np.ndarray], margin: float = 0.1) -> np.ndarray:
    """
    A shared nadir-based reference point for hypervolume.

    Hypervolume is only comparable across algorithms when they share a
    reference point, so callers should compute one from *all* fronts being
    compared and pass it to every :func:`hypervolume` call.
    """
    stacked = [np.atleast_2d(np.asarray(f, dtype=float)) for f in fronts if np.size(f)]
    if not stacked:
        raise ValueError("cannot build a reference point from empty fronts")
    allF = np.vstack(stacked)
    worst = allF.max(axis=0)
    best = allF.min(axis=0)
    span = np.where(worst - best > 1e-12, worst - best, np.abs(worst) + 1.0)
    return worst + margin * span


def _hypervolume_exact_2d(F: np.ndarray, ref: np.ndarray) -> float:
    """Exact 2-D hypervolume by sweeping the sorted front."""
    order = np.argsort(F[:, 0], kind="stable")
    F = F[order]
    volume = 0.0
    prev_y = ref[1]
    for x, y in F:
        if y >= prev_y:
            continue
        volume += (ref[0] - x) * (prev_y - y)
        prev_y = y
    return float(volume)


def _hypervolume_monte_carlo(F: np.ndarray, ref: np.ndarray, n_samples: int = 200_000) -> float:
    """Monte-Carlo hypervolume for 3+ objectives when pymoo is unavailable."""
    lo = F.min(axis=0)
    box = ref - lo
    if np.any(box <= 0):
        return 0.0
    rng = np.random.default_rng(12345)  # fixed, so the metric is reproducible
    samples = rng.uniform(lo, ref, size=(n_samples, F.shape[1]))
    # A sample counts if any front point dominates (weakly) it.
    dominated = np.zeros(n_samples, dtype=bool)
    for point in F:
        dominated |= np.all(samples >= point, axis=1)
    return float(dominated.mean() * np.prod(box))


def hypervolume(pareto_front, reference_point_: Optional[Sequence[float]] = None) -> float:
    """
    Hypervolume indicator — larger is better.

    Uses pymoo when installed, an exact sweep for two objectives, and a
    deterministic Monte-Carlo estimate otherwise. Points that do not dominate
    the reference point are discarded rather than contributing negative volume.
    """
    F = _as_front(pareto_front)
    if F.size == 0:
        return 0.0
    ref = (
        np.asarray(reference_point_, dtype=float)
        if reference_point_ is not None
        else reference_point([F])
    )
    if ref.shape[0] != F.shape[1]:
        raise ValueError("reference point dimensionality must match the front")

    F = F[np.all(F < ref, axis=1)]
    if F.size == 0:
        return 0.0

    try:
        from pymoo.indicators.hv import HV  # type: ignore

        return float(HV(ref_point=ref)(F))
    except Exception as exc:  # pragma: no cover - depends on optional dep
        logger.debug("pymoo hypervolume unavailable (%s); using fallback", exc)

    if F.shape[1] == 2:
        return _hypervolume_exact_2d(F, ref)
    return _hypervolume_monte_carlo(F, ref)


def igd(pareto_front, true_front) -> float:
    """
    Inverted Generational Distance — smaller is better.

    Mean distance from every reference point to its nearest approximation
    point. Requires a reference front; when comparing several algorithms with
    no analytical optimum, use the merged non-dominated set of all their
    results (see :func:`combined_reference_front`).
    """
    F = _as_front(pareto_front)
    R = _as_front(true_front)
    if F.size == 0 or R.size == 0:
        return float("inf")
    distances = np.linalg.norm(R[:, None, :] - F[None, :, :], axis=2)
    return float(distances.min(axis=1).mean())


def igd_plus(pareto_front, true_front) -> float:
    """IGD+ — weakly Pareto-compliant variant of IGD. Smaller is better."""
    F = _as_front(pareto_front)
    R = _as_front(true_front)
    if F.size == 0 or R.size == 0:
        return float("inf")
    diff = np.maximum(F[None, :, :] - R[:, None, :], 0.0)
    return float(np.linalg.norm(diff, axis=2).min(axis=1).mean())


def gd(pareto_front, true_front) -> float:
    """Generational Distance — smaller is better."""
    F = _as_front(pareto_front)
    R = _as_front(true_front)
    if F.size == 0 or R.size == 0:
        return float("inf")
    distances = np.linalg.norm(F[:, None, :] - R[None, :, :], axis=2)
    return float(distances.min(axis=1).mean())


def spacing(pareto_front) -> float:
    """
    Schott's spacing metric — smaller means more evenly distributed.

    This is the standard deviation of nearest-neighbour distances, normalised
    by their mean so fronts on different scales stay comparable.
    """
    F = _as_front(pareto_front)
    if len(F) < 2:
        return 0.0
    distances = np.linalg.norm(F[:, None, :] - F[None, :, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    nearest = distances.min(axis=1)
    mean = nearest.mean()
    if mean <= 1e-12:
        return 0.0
    return float(nearest.std() / mean)


def spread(pareto_front) -> float:
    """
    Deb's spread (Delta) — smaller means better coverage and distribution.

    Delta = (d_f + d_l + sum|d_i - d_mean|) / (d_f + d_l + (N-1) * d_mean),
    where d_f and d_l are the distances to the extreme solutions. The previous
    implementation returned only ``std(nearest neighbour distance)``, which is
    a different (and unnormalised) quantity.
    """
    F = _as_front(pareto_front)
    n = len(F)
    if n < 2:
        return 0.0

    # Order along the first objective for a well-defined chain.
    F = F[np.argsort(F[:, 0], kind="stable")]
    consecutive = np.linalg.norm(np.diff(F, axis=0), axis=1)
    d_mean = consecutive.mean()

    lo, hi = F.min(axis=0), F.max(axis=0)
    d_f = float(np.linalg.norm(F[0] - lo))
    d_l = float(np.linalg.norm(F[-1] - hi))

    denominator = d_f + d_l + (n - 1) * d_mean
    if denominator <= 1e-12:
        return 0.0
    numerator = d_f + d_l + float(np.abs(consecutive - d_mean).sum())
    return float(numerator / denominator)


def combined_reference_front(fronts: Sequence[np.ndarray]) -> np.ndarray:
    """Merged non-dominated set of several fronts — a proxy true front."""
    stacked = [np.atleast_2d(np.asarray(f, dtype=float)) for f in fronts if np.size(f)]
    if not stacked:
        return np.empty((0, 0))
    allF = np.vstack(stacked)
    keep = np.ones(len(allF), dtype=bool)
    for i in range(len(allF)):
        if not keep[i]:
            continue
        dominators = np.all(allF <= allF[i], axis=1) & np.any(allF < allF[i], axis=1)
        if np.any(dominators):
            keep[i] = False
    return allF[keep]


def convergence_metric(history: Sequence[float]) -> Dict[str, Union[float, int]]:
    """
    Summarise a convergence trace: where it ended, how fast it got there.

    ``iterations_to_90pct`` is the first iteration reaching 90% of the total
    improvement — a fair speed comparison between algorithms that converge to
    different final values.
    """
    values = [float(v) for v in history if np.isfinite(v)]
    if not values:
        return {
            "final_value": 0.0,
            "initial_value": 0.0,
            "total_improvement": 0.0,
            "iterations": 0,
            "iterations_to_90pct": 0,
            "rate_of_improvement": 0.0,
        }

    initial, final = values[0], values[-1]
    improvement = initial - final
    target = initial - 0.9 * improvement

    iterations_to_90pct = len(values)
    for i, val in enumerate(values):
        if val <= target:
            iterations_to_90pct = i + 1
            break

    return {
        "final_value": final,
        "initial_value": initial,
        "total_improvement": improvement,
        "iterations": len(values),
        "iterations_to_90pct": int(iterations_to_90pct),
        "rate_of_improvement": improvement / len(values) if values else 0.0,
    }
