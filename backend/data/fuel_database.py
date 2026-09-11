"""
Marine fuel reference data — the single source of truth for the whole platform.

Previously the optimizer and the scenario analyzer each carried their own fuel
table with different fuel names (VLSFO vs MGO) and incompatible units
(gCO2/MJ vs tCO2/t-fuel), so the two modules disagreed about the same fleet.
Everything now derives from one table:

    tCO2 per tonne of fuel = emission_factor_gco2_per_mj * energy_density_mj_per_kg / 1000
    USD  per tonne of fuel = cost_per_gj * energy_density_mj_per_kg

Emission factors are tank-to-wake CO2-equivalent figures in the range used by
IMO MEPC guidance; costs are indicative 2024-25 bunker prices. They are
defaults, not gospel — override them per deployment if you have real bunker
data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class FuelType:
    """Physical, economic and readiness properties of a marine fuel."""

    name: str
    display_name: str
    #: Tank-to-wake CO2-equivalent, grams per megajoule of fuel energy.
    emission_factor_gco2_per_mj: float
    #: Indicative bunker price, USD per gigajoule of energy.
    cost_per_gj: float
    #: Lower heating value, megajoules per kilogram.
    energy_density_mj_per_kg: float
    #: 0-1 score for bunkering-network availability today.
    availability_score: float
    #: SOx emissions, grams per megajoule.
    sox_factor: float = 0.0
    #: NOx emissions, grams per megajoule.
    nox_factor: float = 0.0
    #: 0-1 score for technology / vessel-retrofit readiness.
    readiness_score: float = 1.0
    #: Relative specific fuel consumption vs. a conventional HFO engine.
    sfc_multiplier: float = 1.0
    notes: str = ""

    # ---- derived views ---------------------------------------------------
    @property
    def co2_tons_per_ton_fuel(self) -> float:
        """Tonnes of CO2e released per tonne of fuel burned."""
        return self.emission_factor_gco2_per_mj * self.energy_density_mj_per_kg / 1000.0

    @property
    def cost_per_ton(self) -> float:
        """USD per tonne of fuel."""
        return self.cost_per_gj * self.energy_density_mj_per_kg

    @property
    def sox_tons_per_ton_fuel(self) -> float:
        return self.sox_factor * self.energy_density_mj_per_kg / 1000.0

    @property
    def nox_tons_per_ton_fuel(self) -> float:
        return self.nox_factor * self.energy_density_mj_per_kg / 1000.0

    @property
    def is_zero_carbon(self) -> bool:
        return self.emission_factor_gco2_per_mj <= 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "emission_factor_gco2_per_mj": round(self.emission_factor_gco2_per_mj, 3),
            "cost_per_gj": round(self.cost_per_gj, 3),
            "energy_density_mj_per_kg": round(self.energy_density_mj_per_kg, 3),
            "availability_score": round(self.availability_score, 3),
            "readiness_score": round(self.readiness_score, 3),
            "sox_factor": round(self.sox_factor, 4),
            "nox_factor": round(self.nox_factor, 4),
            "sfc_multiplier": round(self.sfc_multiplier, 3),
            "co2_tons_per_ton_fuel": round(self.co2_tons_per_ton_fuel, 4),
            "cost_per_ton": round(self.cost_per_ton, 2),
            "is_zero_carbon": self.is_zero_carbon,
            "notes": self.notes,
        }


HFO = FuelType(
    name="HFO",
    display_name="Heavy Fuel Oil",
    emission_factor_gco2_per_mj=77.4,
    cost_per_gj=12.0,
    energy_density_mj_per_kg=40.2,
    availability_score=1.00,
    sox_factor=2.00,
    nox_factor=5.00,
    readiness_score=1.00,
    sfc_multiplier=1.00,
    notes="Baseline fuel. Requires scrubbers to meet the global sulphur cap.",
)

VLSFO = FuelType(
    name="VLSFO",
    display_name="Very Low Sulphur Fuel Oil",
    emission_factor_gco2_per_mj=72.6,
    cost_per_gj=14.6,
    energy_density_mj_per_kg=41.0,
    availability_score=0.95,
    sox_factor=0.50,
    nox_factor=4.50,
    readiness_score=1.00,
    sfc_multiplier=1.00,
    notes="IMO 2020 compliant without a scrubber.",
)

MGO = FuelType(
    name="MGO",
    display_name="Marine Gas Oil",
    emission_factor_gco2_per_mj=74.5,
    cost_per_gj=18.7,
    energy_density_mj_per_kg=42.7,
    availability_score=0.98,
    sox_factor=0.30,
    nox_factor=4.20,
    readiness_score=1.00,
    sfc_multiplier=0.97,
    notes="Distillate fuel, widely available, used in emission control areas.",
)

LNG = FuelType(
    name="LNG",
    display_name="Liquefied Natural Gas",
    emission_factor_gco2_per_mj=56.1,
    cost_per_gj=12.3,
    energy_density_mj_per_kg=48.6,
    availability_score=0.70,
    sox_factor=0.00,
    nox_factor=1.00,
    readiness_score=0.85,
    sfc_multiplier=0.89,
    notes="Mature dual-fuel technology; methane slip is excluded from this factor.",
)

METHANOL = FuelType(
    name="Methanol",
    display_name="Methanol",
    emission_factor_gco2_per_mj=67.5,
    cost_per_gj=20.1,
    energy_density_mj_per_kg=19.9,
    availability_score=0.50,
    sox_factor=0.00,
    nox_factor=0.80,
    readiness_score=0.70,
    sfc_multiplier=1.11,
    notes="Low tank volume penalty vs. hydrogen; green methanol is near zero WtW.",
)

AMMONIA = FuelType(
    name="Ammonia",
    display_name="Green Ammonia",
    emission_factor_gco2_per_mj=0.0,
    cost_per_gj=40.0,
    energy_density_mj_per_kg=18.6,
    availability_score=0.15,
    sox_factor=0.00,
    nox_factor=1.00,
    readiness_score=0.40,
    sfc_multiplier=1.06,
    notes="Zero carbon at the stack; NOx after-treatment and toxicity handling required.",
)

HYDROGEN = FuelType(
    name="Hydrogen",
    display_name="Green Hydrogen",
    emission_factor_gco2_per_mj=0.0,
    cost_per_gj=20.8,
    energy_density_mj_per_kg=120.0,
    availability_score=0.20,
    sox_factor=0.00,
    nox_factor=0.00,
    readiness_score=0.30,
    sfc_multiplier=0.94,
    notes="Highest energy per kg but very low energy per m3; large tank penalty.",
)

FUEL_DATABASE: Dict[str, FuelType] = {
    f.name: f for f in (HFO, VLSFO, MGO, LNG, METHANOL, AMMONIA, HYDROGEN)
}

#: Case-insensitive lookup index.
_FUEL_INDEX: Dict[str, str] = {name.lower(): name for name in FUEL_DATABASE}

DEFAULT_FUEL = "HFO"


def fuel_names() -> List[str]:
    """Canonical fuel names, in presentation order."""
    return list(FUEL_DATABASE.keys())


def get_fuel(name: str) -> Optional[FuelType]:
    """Look a fuel up by name, case-insensitively. Returns ``None`` if unknown."""
    if not name:
        return None
    canonical = _FUEL_INDEX.get(str(name).strip().lower())
    return FUEL_DATABASE.get(canonical) if canonical else None


def require_fuel(name: str) -> FuelType:
    """Look a fuel up, raising :class:`ValueError` when it does not exist."""
    fuel = get_fuel(name)
    if fuel is None:
        raise ValueError(
            f"Unknown fuel '{name}'. Available fuels: {', '.join(fuel_names())}"
        )
    return fuel


def get_all_fuels() -> List[FuelType]:
    return list(FUEL_DATABASE.values())


def resolve_fuels(names: Optional[List[str]]) -> List[FuelType]:
    """
    Turn a list of user-supplied fuel names into FuelType objects.

    Empty or ``None`` means "every fuel". Unknown names raise ValueError so the
    caller can return a helpful 4xx rather than silently optimising the wrong
    fleet.
    """
    if not names:
        return get_all_fuels()
    resolved, seen = [], set()
    for raw in names:
        fuel = require_fuel(raw)
        if fuel.name not in seen:
            seen.add(fuel.name)
            resolved.append(fuel)
    return resolved


# ---------------------------------------------------------------------------
# Energy / emission / cost helpers
# ---------------------------------------------------------------------------
def energy_from_mass(fuel_name: str, tons: float) -> float:
    """Energy in MJ contained in ``tons`` tonnes of the named fuel."""
    fuel = require_fuel(fuel_name)
    return tons * 1000.0 * fuel.energy_density_mj_per_kg


def calculate_co2_emissions(fuel_name: str, energy_mj: float) -> float:
    """CO2e in **grams** for a given amount of fuel energy in MJ."""
    return require_fuel(fuel_name).emission_factor_gco2_per_mj * energy_mj


def calculate_fuel_cost(fuel_name: str, energy_mj: float) -> float:
    """Fuel cost in USD for a given amount of fuel energy in MJ."""
    return require_fuel(fuel_name).cost_per_gj * (energy_mj / 1000.0)


def emissions_from_mass(fuel_name: str, tons: float) -> Dict[str, float]:
    """CO2/SOx/NOx in tonnes for ``tons`` tonnes of fuel burned."""
    fuel = require_fuel(fuel_name)
    return {
        "co2_tons": tons * fuel.co2_tons_per_ton_fuel,
        "sox_tons": tons * fuel.sox_tons_per_ton_fuel,
        "nox_tons": tons * fuel.nox_tons_per_ton_fuel,
    }


def cost_from_mass(fuel_name: str, tons: float) -> float:
    """Bunker cost in USD for ``tons`` tonnes of fuel."""
    return tons * require_fuel(fuel_name).cost_per_ton
