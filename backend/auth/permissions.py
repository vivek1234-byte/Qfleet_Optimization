"""
Per-employee module access.

The role decides *whether* someone is an administrator; this decides *which
operational screens* a non-administrator may open. An administrator always has
everything and cannot be restricted — otherwise an admin could lock the last
admin out of the Employees page and leave the deployment unadministrable.

The stored value is a comma-separated list of module keys on
``employees.permissions``. **Empty means "the role default", not "nothing"** —
existing rows predate this column, and reading a NULL as "no access" would
have silently locked out every account already in the database the moment the
migration ran. An administrator who genuinely wants to grant nothing beyond
the dashboard grants exactly ``dashboard``.

Enforcement lives in ``require_module`` and is wired onto the data routers.
The navigation filter in the frontend is a courtesy; this is the boundary.
"""
from __future__ import annotations

from typing import Iterable

from core.errors import PermissionError_
from db.models import Employee, Role

# The catalogue. `key` is the contract shared with the frontend's nav model —
# changing one means changing `frontend/src/lib/nav.js` in the same commit.
MODULES: tuple[dict[str, str], ...] = (
    {"key": "dashboard", "label": "Dashboard", "blurb": "Fleet at a glance"},
    {"key": "simulator", "label": "Fleet Digital Twin", "blurb": "Live fleet simulation"},
    {"key": "optimize", "label": "Fleet Optimizer", "blurb": "Deployment planning"},
    {"key": "predict", "label": "Fuel Prediction", "blurb": "Voyage fuel model"},
    {"key": "compliance", "label": "Compliance", "blurb": "CII ratings and ECA zones"},
    {"key": "fleet", "label": "Fleet & Lanes", "blurb": "Vessel and route registry"},
    {"key": "sandbox", "label": "What-if Sandbox", "blurb": "Live scenario levers"},
    {"key": "scenarios", "label": "Scenarios", "blurb": "Fuel transition planning"},
    {"key": "benchmarks", "label": "Benchmarks", "blurb": "Solver evidence"},
)

MODULE_KEYS: frozenset[str] = frozenset(m["key"] for m in MODULES)

# What an employee gets when nobody has said otherwise. Deliberately the set
# the product shipped with, so introducing this feature took nothing away from
# anyone; an administrator removes access explicitly.
DEFAULT_EMPLOYEE_MODULES: tuple[str, ...] = (
    "dashboard",
    "simulator",
    "optimize",
    "predict",
    "compliance",
    "fleet",
)

# Modules that have never been open to employees. Listing them here rather
# than relying on the default set means a hand-edited `permissions` row cannot
# hand out an admin-only screen.
ADMIN_ONLY_MODULES: frozenset[str] = frozenset({"sandbox", "scenarios", "benchmarks"})


def normalise(keys: Iterable[str] | None) -> list[str]:
    """Clean a caller-supplied list: known keys only, de-duplicated, ordered."""
    if keys is None:
        return []
    wanted = {str(k).strip().lower() for k in keys if str(k).strip()}
    unknown = wanted - MODULE_KEYS
    if unknown:
        raise ValueError(f"Unknown module(s): {', '.join(sorted(unknown))}")
    # Catalogue order, so the stored string is stable and diffable.
    return [m["key"] for m in MODULES if m["key"] in wanted]


def encode(keys: Iterable[str] | None) -> str:
    """List → the string stored on the row."""
    return ",".join(normalise(keys))


def decode(raw: str | None) -> list[str]:
    """
    The stored string → list, ignoring anything no longer in the catalogue.

    Lenient on read and strict on write: a module removed from the product
    should not make every employee row that mentions it unreadable.
    """
    if not raw:
        return []
    return [m["key"] for m in MODULES if m["key"] in {p.strip().lower() for p in raw.split(",")}]


def allowed_modules(employee: Employee) -> list[str]:
    """
    Every module this person may open.

    Administrators get the whole catalogue — the role is the grant, and there
    is no way to configure it away. For everyone else: their explicit list if
    they have one, otherwise the default set, with admin-only screens removed
    either way.
    """
    if employee.role == Role.ADMIN.value:
        return [m["key"] for m in MODULES]

    explicit = decode(getattr(employee, "permissions", None))
    granted = explicit or list(DEFAULT_EMPLOYEE_MODULES)
    return [k for k in granted if k not in ADMIN_ONLY_MODULES]


def has_module(employee: Employee, key: str) -> bool:
    return key in allowed_modules(employee)


def reference_data():
    """
    A dependency for endpoints every signed-in user may read.

    Some routes serve catalogues rather than a feature: the fuel database, the
    vessel and lane registry, ECA zone geometry, the CII reference curves, the
    seasonality table. Four different screens draw on them — the digital twin
    needs the fuel list for its legend, the map needs ECA geometry whichever
    page it is on — so gating them by the module that happens to own their
    router locks people out of screens they were granted.

    They still require a session. What they do not require is a particular
    module, because they describe the world rather than the fleet's plan.
    """
    from fastapi import Depends

    from .deps import get_current_employee

    def _guard(employee: Employee = Depends(get_current_employee)) -> Employee:
        return employee

    return _guard


def require_module(*keys: str):
    """
    A dependency that 403s unless the caller may open **any** of ``keys``.

    Several modules share a backend router — the dashboard, the digital twin,
    the optimizer and the sandbox all post to ``/api/optimization`` — so the
    check is "any of", not "all of". Splitting those endpoints per screen
    would mean four near-identical solver routes; gating on the union is the
    honest description of what the router serves.
    """
    unknown = set(keys) - MODULE_KEYS
    if unknown:  # pragma: no cover - a wiring mistake, caught at import time
        raise ValueError(f"require_module got unknown key(s): {sorted(unknown)}")

    from fastapi import Depends  # local import: keeps this module importable bare

    from .deps import get_current_employee

    def _guard(employee: Employee = Depends(get_current_employee)) -> Employee:
        permitted = set(allowed_modules(employee))
        if permitted.isdisjoint(keys):
            labels = [m["label"] for m in MODULES if m["key"] in keys]
            raise PermissionError_(
                "You do not have access to "
                + (" or ".join(labels) if labels else "this module")
                + ". Ask an administrator to grant it."
            )
        return employee

    return _guard
