"""
Fuel-transition scenario analysis.

The previous version carried its own fuel table with different names (``MGO``
where the rest of the system used ``VLSFO``) and different units, so the same
fleet produced different emissions depending on which module you asked. It also
assumed HFO as the energy-equivalence reference for *every* switch, which
double-counts whenever a vessel is already on something else, and hard-coded
2024 as "now".

Everything here now derives from :mod:`data.fuel_database`.
"""
from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence

try:
    from ..data.fuel_database import (
        DEFAULT_FUEL,
        FuelType,
        fuel_names,
        get_all_fuels,
        require_fuel,
    )
except ImportError:  # pragma: no cover
    from data.fuel_database import (
        DEFAULT_FUEL,
        FuelType,
        fuel_names,
        get_all_fuels,
        require_fuel,
    )

logger = logging.getLogger(__name__)

#: Retrofit capital cost per vessel, USD, by target fuel.
RETROFIT_COST_USD = {
    "HFO": 0.0,
    "VLSFO": 0.0,
    "MGO": 250_000.0,
    "LNG": 12_000_000.0,
    "Methanol": 8_500_000.0,
    "Ammonia": 16_000_000.0,
    "Hydrogen": 22_000_000.0,
}
#: Share of a voyage's emissions that occur at berth, available to shore power.
PORT_EMISSION_SHARE = 0.20


@dataclass
class Vessel:
    """One ship in the scenario fleet."""

    id: int
    name: str = ""
    fuel_type: str = DEFAULT_FUEL
    fuel_consumption: float = 100.0  # tonnes per planning period

    def __post_init__(self) -> None:
        require_fuel(self.fuel_type)  # raises on an unknown fuel
        if self.fuel_consumption < 0:
            raise ValueError("fuel_consumption must not be negative")
        if not self.name:
            self.name = f"Vessel {self.id}"


@dataclass
class ScenarioResult:
    """Outcome of one fuel scenario, always relative to the base fleet."""

    scenario_name: str
    fuel_type: str
    total_fuel_tons: float
    total_energy_gj: float
    total_emissions_co2: float
    total_sox_tons: float
    total_nox_tons: float
    total_cost_usd: float
    retrofit_capex_usd: float
    feasibility: float
    emission_reduction_pct: float
    cost_change_pct: float
    vessels_switched: int = 0
    abatement_cost_usd_per_ton: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        for key, value in data.items():
            if isinstance(value, float):
                data[key] = round(value, 4)
        return data


class ScenarioAnalyzer:
    """Compares fuel-switching and shore-power scenarios against a base fleet."""

    def __init__(self, base_fleet_config: Optional[Dict[str, Any]] = None) -> None:
        config = base_fleet_config or {}
        self.vessels: List[Vessel] = self._parse_vessels(config.get("vessels", []))
        if not self.vessels:
            raise ValueError("A scenario fleet needs at least one vessel")
        self.base_result = self._evaluate("Base Scenario", self.vessels, is_base=True)

    # -- fleet parsing -----------------------------------------------------
    @staticmethod
    def _parse_vessels(raw: Sequence[Any]) -> List[Vessel]:
        vessels: List[Vessel] = []
        for i, item in enumerate(raw):
            if isinstance(item, Vessel):
                vessels.append(item)
                continue
            if not isinstance(item, dict):
                raise ValueError(f"vessel #{i} must be an object")
            vessels.append(
                Vessel(
                    id=int(item.get("id", i)),
                    name=str(item.get("name", "") or ""),
                    fuel_type=str(item.get("fuel_type", DEFAULT_FUEL)),
                    fuel_consumption=float(item.get("fuel_consumption", 100.0)),
                )
            )
        return vessels

    @property
    def fuel_properties(self) -> Dict[str, Dict[str, Any]]:
        """Fuel table, in the shape the API exposes."""
        return {f.name: f.to_dict() for f in get_all_fuels()}

    # -- evaluation --------------------------------------------------------
    def _evaluate(
        self,
        name: str,
        vessels: Sequence[Vessel],
        *,
        is_base: bool = False,
        target_fuel: Optional[str] = None,
        retrofit_capex: float = 0.0,
        feasibility: float = 1.0,
        vessels_switched: int = 0,
        notes: str = "",
    ) -> ScenarioResult:
        total_fuel = total_energy = total_co2 = total_sox = total_nox = total_cost = 0.0

        for vessel in vessels:
            fuel: FuelType = require_fuel(vessel.fuel_type)
            tons = vessel.fuel_consumption
            energy_mj = tons * 1000.0 * fuel.energy_density_mj_per_kg

            total_fuel += tons
            total_energy += energy_mj / 1000.0  # GJ
            total_co2 += tons * fuel.co2_tons_per_ton_fuel
            total_sox += tons * fuel.sox_tons_per_ton_fuel
            total_nox += tons * fuel.nox_tons_per_ton_fuel
            total_cost += tons * fuel.cost_per_ton

        result = ScenarioResult(
            scenario_name=name,
            fuel_type=target_fuel or (vessels[0].fuel_type if vessels else DEFAULT_FUEL),
            total_fuel_tons=total_fuel,
            total_energy_gj=total_energy,
            total_emissions_co2=total_co2,
            total_sox_tons=total_sox,
            total_nox_tons=total_nox,
            total_cost_usd=total_cost,
            retrofit_capex_usd=retrofit_capex,
            feasibility=feasibility,
            emission_reduction_pct=0.0,
            cost_change_pct=0.0,
            vessels_switched=vessels_switched,
            notes=notes,
        )

        if not is_base and getattr(self, "base_result", None) is not None:
            base = self.base_result
            if base.total_emissions_co2 > 0:
                result.emission_reduction_pct = (
                    (base.total_emissions_co2 - total_co2) / base.total_emissions_co2 * 100.0
                )
            if base.total_cost_usd > 0:
                result.cost_change_pct = (
                    (total_cost - base.total_cost_usd) / base.total_cost_usd * 100.0
                )
            # Marginal abatement cost: extra spend per tonne of CO2 avoided,
            # including amortised retrofit capex over a 15-year vessel life.
            co2_saved = base.total_emissions_co2 - total_co2
            if co2_saved > 1e-9:
                extra_opex = total_cost - base.total_cost_usd
                annualised_capex = retrofit_capex / 15.0
                result.abatement_cost_usd_per_ton = (extra_opex + annualised_capex) / co2_saved

        return result

    # -- scenarios ---------------------------------------------------------
    def analyze_fuel_switch(
        self,
        target_fuel: str,
        vessel_indices: Optional[List[int]] = None,
    ) -> ScenarioResult:
        """
        Switch some or all vessels to ``target_fuel`` on an energy-equivalent basis.

        Each vessel's new tonnage is scaled by *its own* current fuel's energy
        density, not by HFO's, so switching a fleet that already runs mixed
        fuels gives the right answer.
        """
        target = require_fuel(target_fuel)

        if vessel_indices is not None:
            invalid = [i for i in vessel_indices if not 0 <= i < len(self.vessels)]
            if invalid:
                raise ValueError(
                    f"vessel_indices out of range: {invalid} (fleet has {len(self.vessels)} vessels)"
                )
            selected = set(vessel_indices)
        else:
            selected = set(range(len(self.vessels)))

        new_vessels: List[Vessel] = []
        switched = 0
        for i, vessel in enumerate(self.vessels):
            if i not in selected or vessel.fuel_type == target.name:
                new_vessels.append(vessel)
                continue
            current = require_fuel(vessel.fuel_type)
            # Same energy delivered, different mass and engine efficiency.
            energy_ratio = current.energy_density_mj_per_kg / target.energy_density_mj_per_kg
            efficiency_ratio = target.sfc_multiplier / current.sfc_multiplier
            new_tons = vessel.fuel_consumption * energy_ratio * efficiency_ratio
            new_vessels.append(
                Vessel(
                    id=vessel.id,
                    name=vessel.name,
                    fuel_type=target.name,
                    fuel_consumption=new_tons,
                )
            )
            switched += 1

        capex = RETROFIT_COST_USD.get(target.name, 5_000_000.0) * switched
        # Feasibility blends bunkering availability with technology readiness.
        feasibility = round(target.availability_score * 0.5 + target.readiness_score * 0.5, 3)

        return self._evaluate(
            f"Switch to {target.display_name}",
            new_vessels,
            target_fuel=target.name,
            retrofit_capex=capex,
            feasibility=feasibility,
            vessels_switched=switched,
            notes=target.notes,
        )

    def compare_scenarios(self, fuel_options: Sequence[str]) -> List[Dict[str, Any]]:
        """Base case plus one scenario per requested fuel."""
        if not fuel_options:
            raise ValueError("fuel_options must not be empty")
        unknown = [f for f in fuel_options if f not in self.fuel_properties]
        if unknown:
            raise ValueError(
                f"Unknown fuel(s): {', '.join(unknown)}. Available: {', '.join(fuel_names())}"
            )
        rows = [self.base_result.to_dict()]
        for fuel in fuel_options:
            rows.append(self.analyze_fuel_switch(fuel).to_dict())
        return rows

    def analyze_shore_power(
        self, ports: Optional[Sequence[str]] = None, shore_power_pct: float = 50.0
    ) -> Dict[str, Any]:
        """Emissions and cost impact of taking shore power at berth."""
        if not 0.0 <= shore_power_pct <= 100.0:
            raise ValueError("shore_power_pct must be between 0 and 100")

        base_emissions = self.base_result.total_emissions_co2
        port_emissions = base_emissions * PORT_EMISSION_SHARE
        avoided = port_emissions * (shore_power_pct / 100.0)

        # Fuel not burned at berth, and the electricity bought instead.
        fuel_share = self.base_result.total_fuel_tons * PORT_EMISSION_SHARE * (shore_power_pct / 100.0)
        bunker_saved = self.base_result.total_cost_usd * PORT_EMISSION_SHARE * (shore_power_pct / 100.0)
        # ~4.2 MWh of shore power replaces a tonne of marine fuel at berth.
        electricity_cost = fuel_share * 4_200.0 * 0.14

        return {
            "ports": list(ports or []),
            "shore_power_pct": shore_power_pct,
            "port_emissions_co2_tons": round(port_emissions, 3),
            "avoided_co2_tons": round(avoided, 3),
            "avoided_pct_of_fleet": round(
                (avoided / base_emissions * 100.0) if base_emissions else 0.0, 3
            ),
            "fuel_saved_tons": round(fuel_share, 3),
            "bunker_cost_saved_usd": round(bunker_saved, 2),
            "electricity_cost_usd": round(electricity_cost, 2),
            "net_cost_change_usd": round(electricity_cost - bunker_saved, 2),
        }

    def generate_transition_plan(
        self,
        target_year: int = 2035,
        target_fuel: str = "LNG",
        start_year: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        A year-by-year fleet transition plan.

        ``start_year`` defaults to the current year rather than the hard-coded
        2024 the original used, which silently produced an eleven-year plan in
        2035.
        """
        target = require_fuel(target_fuel)
        start = start_year if start_year is not None else _dt.date.today().year
        if target_year <= start:
            raise ValueError(f"target_year must be later than {start}")

        years = target_year - start
        fleet_size = len(self.vessels)
        plan: List[Dict[str, Any]] = []

        for step in range(1, years + 1):
            year = start + step
            pct = min(100.0, step / years * 100.0)
            vessels_converted = int(round(fleet_size * pct / 100.0))
            scenario = self.analyze_fuel_switch(
                target.name, vessel_indices=list(range(vessels_converted))
            )
            plan.append(
                {
                    "year": year,
                    "target_pct_green_fuel": round(pct, 1),
                    "vessels_converted": vessels_converted,
                    "cumulative_capex_usd": round(scenario.retrofit_capex_usd, 2),
                    "annual_co2_tons": round(scenario.total_emissions_co2, 2),
                    "co2_reduction_pct": round(scenario.emission_reduction_pct, 2),
                    "annual_fuel_cost_usd": round(scenario.total_cost_usd, 2),
                    "milestone": (
                        f"Phase {step}: {vessels_converted}/{fleet_size} vessels on "
                        f"{target.display_name} ({pct:.0f}%)"
                    ),
                }
            )
        return plan

    def fleet_summary(self) -> Dict[str, Any]:
        mix: Dict[str, int] = {}
        for vessel in self.vessels:
            mix[vessel.fuel_type] = mix.get(vessel.fuel_type, 0) + 1
        return {
            "vessel_count": len(self.vessels),
            "fuel_mix": mix,
            "vessels": [asdict(v) for v in self.vessels],
            "base": self.base_result.to_dict(),
        }


# A representative mixed fleet drawn from the registry. Consumption is tonnes
# per planning period (a month of typical trading for each class).
DEFAULT_FLEET_CONFIG: Dict[str, Any] = {
    "vessels": [
        {"id": 1, "name": "MV Sagar Pratap",   "fuel_type": "VLSFO", "fuel_consumption": 1_450},
        {"id": 2, "name": "MV Mundra Pioneer", "fuel_type": "VLSFO", "fuel_consumption": 1_820},
        {"id": 3, "name": "MV Desh Vaibhav",   "fuel_type": "HFO",   "fuel_consumption": 620},
        {"id": 4, "name": "MV Jag Arnav",      "fuel_type": "HFO",   "fuel_consumption": 480},
        {"id": 5, "name": "MT Nilgiri Spirit", "fuel_type": "MGO",   "fuel_consumption": 890},
        {"id": 6, "name": "MT Aravalli Pride", "fuel_type": "VLSFO", "fuel_consumption": 1_120},
        {"id": 7, "name": "MV Kaveri Express", "fuel_type": "LNG",   "fuel_consumption": 940},
    ]
}
