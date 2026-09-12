"""
Scenario API.

The original router built one module-level ``ScenarioAnalyzer`` over a hard-coded
three-vessel "dummy_config", with no way for a caller to supply their own fleet,
and it mapped every failure — including genuine server errors — onto a 400.

Callers can now pass a fleet per request, or set a session fleet, and errors
carry accurate status codes.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import Depends, APIRouter
from auth.permissions import reference_data, require_module
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from ..core.errors import ValidationError
    from ..data.fuel_database import fuel_names, get_all_fuels
    from .analyzer import DEFAULT_FLEET_CONFIG, ScenarioAnalyzer
except ImportError:  # pragma: no cover
    from core.errors import ValidationError
    from data.fuel_database import fuel_names, get_all_fuels
    from scenario.analyzer import DEFAULT_FLEET_CONFIG, ScenarioAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/scenarios", tags=["Scenarios"])

_lock = threading.Lock()
_default_analyzer = ScenarioAnalyzer(DEFAULT_FLEET_CONFIG)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class VesselInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., ge=0)
    name: str = ""
    fuel_type: str = Field("HFO", description=f"One of: {', '.join(fuel_names())}")
    fuel_consumption: float = Field(100.0, ge=0, le=1_000_000, description="Tonnes per period")

    @field_validator("fuel_type")
    @classmethod
    def _known_fuel(cls, v: str) -> str:
        match = next((f for f in fuel_names() if f.lower() == v.strip().lower()), None)
        if match is None:
            raise ValueError(f"fuel_type must be one of: {', '.join(fuel_names())}")
        return match


class FleetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vessels: List[VesselInput] = Field(..., min_length=1, max_length=500)


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_fuel: str
    vessel_indices: Optional[List[int]] = Field(
        None, description="Zero-based indices to convert. Omit to convert the whole fleet."
    )
    fleet: Optional[FleetInput] = Field(
        None, description="Fleet to analyse. Omit to use the session fleet."
    )


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuel_options: List[str] = Field(..., min_length=1, max_length=20)
    fleet: Optional[FleetInput] = None


class ShorePowerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shore_power_pct: float = Field(50.0, ge=0, le=100)
    ports: Optional[List[str]] = None
    fleet: Optional[FleetInput] = None


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_year: int = Field(2035, ge=2025, le=2060)
    target_fuel: str = "LNG"
    start_year: Optional[int] = Field(None, ge=2000, le=2060)
    fleet: Optional[FleetInput] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _analyzer_for(fleet: Optional[FleetInput]) -> ScenarioAnalyzer:
    """Per-request analyzer when a fleet is supplied, otherwise the session one."""
    if fleet is None:
        with _lock:
            return _default_analyzer
    try:
        return ScenarioAnalyzer({"vessels": [v.model_dump() for v in fleet.vessels]})
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/fuels", dependencies=[Depends(reference_data())])
def list_fuels() -> List[Dict[str, Any]]:
    """The fuel reference table — the same data the optimizer uses."""
    return [fuel.to_dict() for fuel in get_all_fuels()]


@router.get("/fleet", dependencies=[Depends(require_module('scenarios'))])
def get_fleet() -> Dict[str, Any]:
    """The current session fleet and its base-case footprint."""
    with _lock:
        return _default_analyzer.fleet_summary()


@router.put("/fleet", dependencies=[Depends(require_module('scenarios'))])
def set_fleet(fleet: FleetInput) -> Dict[str, Any]:
    """Replace the session fleet used when a request omits ``fleet``."""
    global _default_analyzer
    try:
        analyzer = ScenarioAnalyzer({"vessels": [v.model_dump() for v in fleet.vessels]})
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    with _lock:
        _default_analyzer = analyzer
        return _default_analyzer.fleet_summary()


@router.post("/analyze", dependencies=[Depends(require_module('scenarios'))])
def run_scenario_analysis(request: AnalyzeRequest) -> Dict[str, Any]:
    """Analyse switching some or all of the fleet to a target fuel."""
    analyzer = _analyzer_for(request.fleet)
    try:
        result = analyzer.analyze_fuel_switch(request.target_fuel, request.vessel_indices)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return {"base": analyzer.base_result.to_dict(), "scenario": result.to_dict()}


@router.post("/compare", dependencies=[Depends(require_module('scenarios'))])
def compare_scenarios(request: CompareRequest) -> Dict[str, Any]:
    """Compare the base case against several fuel-switch scenarios."""
    analyzer = _analyzer_for(request.fleet)
    try:
        rows = analyzer.compare_scenarios(request.fuel_options)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    switched = [r for r in rows if r["scenario_name"] != "Base Scenario"]
    best_emissions = max(switched, key=lambda r: r["emission_reduction_pct"], default=None)
    cheapest_abatement = min(
        (r for r in switched if r.get("abatement_cost_usd_per_ton") is not None),
        key=lambda r: r["abatement_cost_usd_per_ton"],
        default=None,
    )
    return {
        "scenarios": rows,
        "best_for_emissions": best_emissions["fuel_type"] if best_emissions else None,
        "best_value_for_money": cheapest_abatement["fuel_type"] if cheapest_abatement else None,
    }


@router.post("/shore-power", dependencies=[Depends(require_module('scenarios'))])
def analyze_shore_power(request: ShorePowerRequest) -> Dict[str, Any]:
    """Emissions and cost impact of taking shore power at berth."""
    analyzer = _analyzer_for(request.fleet)
    try:
        return analyzer.analyze_shore_power(request.ports, request.shore_power_pct)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("/transition-plan", dependencies=[Depends(require_module('scenarios'))])
def transition_plan(request: TransitionRequest) -> Dict[str, Any]:
    """A year-by-year plan for converting the fleet to a target fuel."""
    analyzer = _analyzer_for(request.fleet)
    try:
        plan = analyzer.generate_transition_plan(
            target_year=request.target_year,
            target_fuel=request.target_fuel,
            start_year=request.start_year,
        )
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return {
        "target_fuel": request.target_fuel,
        "target_year": request.target_year,
        "phases": plan,
        "total_capex_usd": plan[-1]["cumulative_capex_usd"] if plan else 0.0,
        "final_co2_reduction_pct": plan[-1]["co2_reduction_pct"] if plan else 0.0,
    }
