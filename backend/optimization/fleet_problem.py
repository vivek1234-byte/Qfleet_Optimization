"""
The fleet optimization problem.

The previous version hard-coded a 1000 nm voyage for every vessel, ignored the
selected fuel entirely, and folded a single raw penalty into all three
objectives, which collapsed the Pareto front. This module replaces it with a
genuine model:

* per-vessel propulsion power from a cubic speed-power law
* specific fuel consumption adjusted for the chosen fuel
* weather and cargo-load correction factors
* port hotel load offset by shore power
* CO2 / SOx / NOx and cost taken from the shared fuel database
* constraints for route coverage, speed envelope, fuel availability, vessel
  range and schedule, each scaled per objective

Everything is vectorised over the whole population, so a 200-particle,
400-iteration run evaluates in seconds instead of minutes.

Decision vector, 4 genes per vessel::

    [route_index, speed_knots, fuel_index, shore_power_pct] * n_vessels
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

try:  # package import
    from ..data.fleet_registry import LANES, VESSELS
    from ..data.fuel_database import FuelType, get_all_fuels, get_fuel, resolve_fuels
    from ..data.carbon_intensity import assess_fleet, assess_voyage
    from ..data.sea_routes import eca_fraction_for
    from ..data.seasonality import MONTH_NAMES, season_label, seasonal_factor
except ImportError:  # pragma: no cover - direct script execution
    from data.fleet_registry import LANES, VESSELS
    from data.fuel_database import FuelType, get_all_fuels, get_fuel, resolve_fuels
    from data.carbon_intensity import assess_fleet, assess_voyage
    from data.sea_routes import eca_fraction_for
    from data.seasonality import MONTH_NAMES, season_label, seasonal_factor

OBJECTIVE_NAMES = ("fuel_consumption_tons", "co2_emissions_tons", "operational_cost_usd")
OBJECTIVE_LABELS = ("Fuel (t)", "CO2e (t)", "Cost (USD)")

#: Baseline specific fuel consumption of a modern two-stroke, g/kWh.
BASE_SFC_G_PER_KWH = 175.0
#: Electricity price for shore power, USD per kWh.
SHORE_POWER_USD_PER_KWH = 0.14
#: Crew, maintenance and charter cost per vessel per day at sea.
VESSEL_OPEX_USD_PER_DAY = 9_500.0
#: Carbon price applied to CO2e in the cost objective, USD per tonne.
DEFAULT_CARBON_PRICE_USD_PER_TON = 0.0
#: Flat cost, as a fraction of the reference plan, for being infeasible at all.
FEASIBILITY_BARRIER = 0.15
#: Additional cost per unit of normalised constraint violation.
VIOLATION_WEIGHT = 5.0
#: Fuel sulphur cap inside an Emission Control Area, % m/m (MARPOL Annex VI).
ECA_SULPHUR_LIMIT_PCT = 0.10
#: The fuel a non-compliant ship switches to on entering an ECA. Distillate is
#: the usual answer for a ship without scrubbers.
ECA_COMPLIANT_FUEL = "MGO"


@dataclass(frozen=True)
class VesselProfile:
    """A single ship in the fleet."""

    vessel_id: int
    name: str
    vessel_type: str
    dwt: float
    rated_power_kw: float
    design_speed_knots: float
    min_speed_knots: float
    max_speed_knots: float
    cargo_load_pct: float
    hotel_load_kw: float
    tank_volume_m3: float
    port_hours: float = 36.0
    home_port: str = ""
    built: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vessel_id": self.vessel_id,
            "name": self.name,
            "vessel_type": self.vessel_type,
            "home_port": self.home_port,
            "built": self.built,
            "dwt": round(self.dwt, 1),
            "rated_power_kw": round(self.rated_power_kw, 1),
            "design_speed_knots": round(self.design_speed_knots, 2),
            "min_speed_knots": round(self.min_speed_knots, 2),
            "max_speed_knots": round(self.max_speed_knots, 2),
            "cargo_load_pct": round(self.cargo_load_pct, 1),
            "hotel_load_kw": round(self.hotel_load_kw, 1),
            "port_hours": round(self.port_hours, 1),
        }


@dataclass(frozen=True)
class RouteProfile:
    """A trade lane the fleet has to serve."""

    route_id: int
    name: str
    distance_nm: float
    weather_beaufort: float
    #: Cargo tonnage that must be moved on this lane in the planning window.
    demand_tons: float
    #: Latest acceptable transit time, days.
    max_transit_days: float
    shore_power_available: bool = True
    origin: str = ""
    destination: str = ""
    via: str = ""
    cargo: str = ""
    #: Registry lane this route was drawn from, before any "#2" suffix.
    lane_name: str = ""
    #: Share of the voyage inside an Emission Control Area, 0-1.
    eca_fraction: float = 0.0
    #: Annual-mean Beaufort before the seasonal multiplier was applied.
    base_beaufort: float = 0.0
    #: Seasonal multiplier actually in force for this run.
    season_factor: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "route_id": self.route_id,
            "name": self.name,
            "lane_name": self.lane_name or self.name,
            "origin": self.origin,
            "destination": self.destination,
            "via": self.via or None,
            "cargo": self.cargo,
            "distance_nm": round(self.distance_nm, 1),
            "weather_beaufort": round(self.weather_beaufort, 2),
            "base_beaufort": round(self.base_beaufort, 2),
            "season_factor": round(self.season_factor, 3),
            "demand_tons": round(self.demand_tons, 1),
            "max_transit_days": round(self.max_transit_days, 2),
            "shore_power_available": self.shore_power_available,
            "eca_fraction": round(self.eca_fraction, 4),
        }


# ---------------------------------------------------------------------------
# Deterministic fleet / network generation
# ---------------------------------------------------------------------------
# Vessels and lanes come from data/fleet_registry.py — a curated set of
# plausible Indian-flag ships and the trade lanes India's ports actually serve.
# Generation is still deterministic per seed: the seed picks which registry
# entries are used and in what order, plus the small per-run variation in
# cargo load and port stay that keeps repeated demos from looking identical.
#
# Asking for more vessels or lanes than the registry holds wraps around with a
# roman-numeral suffix (e.g. "MV Sagar Pratap II") so large stress tests still
# work without inventing meaningless placeholder names.

_ROMAN = ["", " II", " III", " IV", " V", " VI", " VII", " VIII"]


def _suffix(index: int, size: int) -> str:
    round_ = index // size
    return _ROMAN[round_] if round_ < len(_ROMAN) else f" #{round_ + 1}"


def build_fleet(n_vessels: int, seed: int = 42) -> List[VesselProfile]:
    """Draw ``n_vessels`` ships from the registry, reproducibly for a seed."""
    rng = np.random.default_rng(seed)
    # A seeded permutation so different seeds yield different fleets, while the
    # same seed always yields the same one. A balanced class mix is kept by
    # permuting within type groups and interleaving.
    by_type: Dict[str, List[int]] = {}
    for idx, spec in enumerate(VESSELS):
        by_type.setdefault(spec.vessel_type, []).append(idx)
    order: List[int] = []
    groups = [list(rng.permutation(v)) for v in by_type.values()]
    while any(groups):
        for g in groups:
            if g:
                order.append(int(g.pop(0)))

    fleet: List[VesselProfile] = []
    for i in range(n_vessels):
        spec = VESSELS[order[i % len(order)]]
        fleet.append(
            VesselProfile(
                vessel_id=i,
                name=f"{spec.name}{_suffix(i, len(order))}",
                vessel_type=spec.vessel_type,
                dwt=float(spec.dwt),
                rated_power_kw=float(spec.rated_power_kw),
                design_speed_knots=float(spec.design_speed_knots),
                min_speed_knots=float(spec.min_speed_knots),
                max_speed_knots=float(spec.max_speed_knots),
                cargo_load_pct=float(rng.uniform(60.0, 98.0)),
                hotel_load_kw=float(spec.hotel_load_kw),
                tank_volume_m3=float(spec.tank_volume_m3),
                port_hours=float(rng.uniform(28.0, 56.0)),
                home_port=spec.home_port,
                built=spec.built,
            )
        )
    return fleet


def build_routes(
    n_routes: int, n_vessels: int, seed: int = 42, month: Optional[int] = None
) -> List[RouteProfile]:
    """
    Draw ``n_routes`` trade lanes from the registry with demand scaled to the fleet.

    ``month`` applies the seasonal weather multiplier for each lane's basins.
    Omit it for the annual mean, which is what the registry stores.
    """
    rng = np.random.default_rng(seed + 1)
    # Busiest lanes first so a small demo network is JNPT–Singapore and
    # JNPT–Jebel Ali rather than Haldia–Yangon.
    ranked = sorted(range(len(LANES)), key=lambda i: -LANES[i].demand_weight)

    # Total demand is set so a well-assigned fleet can just about cover it.
    per_vessel_capacity = 55_000.0
    total_demand = per_vessel_capacity * n_vessels * 0.75
    chosen = [LANES[ranked[i % len(ranked)]] for i in range(n_routes)]
    weights = np.array([l.demand_weight for l in chosen]) * rng.uniform(0.9, 1.1, size=n_routes)
    weights = weights / weights.sum()

    routes: List[RouteProfile] = []
    for i, lane in enumerate(chosen):
        season = seasonal_factor(lane.basins, month) if month else 1.0
        base = float(lane.weather_beaufort * rng.uniform(0.92, 1.08))
        routes.append(
            RouteProfile(
                route_id=i,
                name=f"{lane.name}{_suffix(i, len(ranked))}",
                distance_nm=float(lane.distance_nm),
                weather_beaufort=float(np.clip(base * season, 1.0, 9.0)),
                base_beaufort=float(np.clip(base, 1.0, 9.0)),
                season_factor=float(season),
                demand_tons=float(total_demand * weights[i]),
                max_transit_days=float(lane.max_transit_days),
                shore_power_available=lane.shore_power_available,
                origin=lane.origin,
                destination=lane.destination,
                via=lane.via,
                cargo=lane.cargo,
                lane_name=lane.name,
                eca_fraction=eca_fraction_for(lane.name),
            )
        )
    return routes


# ---------------------------------------------------------------------------
# The problem
# ---------------------------------------------------------------------------
class FleetOptimizationProblem:
    """
    Multi-objective fleet deployment problem.

    Objectives, all minimised:
      0. total fuel burned, tonnes
      1. total CO2-equivalent, tonnes
      2. total operational cost, USD
    """

    n_objectives = 3
    genes_per_vessel = 4

    def __init__(
        self,
        n_vessels: int = 10,
        n_routes: int = 5,
        fuel_types: Optional[Sequence[str]] = None,
        *,
        vessels: Optional[List[VesselProfile]] = None,
        routes: Optional[List[RouteProfile]] = None,
        seed: int = 42,
        carbon_price_usd_per_ton: float = DEFAULT_CARBON_PRICE_USD_PER_TON,
        enforce_demand: bool = True,
        month: Optional[int] = None,
        speed_cap_knots: Optional[float] = None,
    ) -> None:
        if n_vessels < 1:
            raise ValueError("n_vessels must be at least 1")
        if n_routes < 1:
            raise ValueError("n_routes must be at least 1")

        self.month = int(month) if month else None
        #: Compliance year the CII rating is measured against.
        self.cii_year = 2026
        self.vessels = vessels if vessels is not None else build_fleet(n_vessels, seed)
        self.routes = (
            routes
            if routes is not None
            else build_routes(n_routes, n_vessels, seed, month=self.month)
        )
        self.n_vessels = len(self.vessels)
        self.n_routes = len(self.routes)
        self.fuels: List[FuelType] = list(resolve_fuels(list(fuel_types) if fuel_types else None))
        if not self.fuels:
            self.fuels = get_all_fuels()
        self.fuel_types = [f.name for f in self.fuels]
        self.n_fuels = len(self.fuels)
        self.seed = seed
        self.carbon_price_usd_per_ton = float(carbon_price_usd_per_ton)
        self.enforce_demand = enforce_demand
        # A fleet-wide speed limit, as a regulator or a charterer would impose
        # one. Never pushed below a vessel's minimum manoeuvring speed, which
        # would make the problem infeasible rather than slow.
        self.speed_cap_knots = float(speed_cap_knots) if speed_cap_knots else None
        self.n_dimensions = self.n_vessels * self.genes_per_vessel

        self._precompute()

    # -- setup ------------------------------------------------------------
    def _precompute(self) -> None:
        """Cache every per-vessel / per-route / per-fuel array once."""
        v = self.vessels
        self._rated_kw = np.array([x.rated_power_kw for x in v], dtype=float)
        self._design_v = np.array([x.design_speed_knots for x in v], dtype=float)
        self._vmin = np.array([x.min_speed_knots for x in v], dtype=float)
        self._vmax = np.array([x.max_speed_knots for x in v], dtype=float)
        if self.speed_cap_knots is not None:
            self._vmax = np.maximum(
                np.minimum(self._vmax, self.speed_cap_knots), self._vmin + 0.1
            )
        self._load = np.array([x.cargo_load_pct for x in v], dtype=float)
        self._hotel_kw = np.array([x.hotel_load_kw for x in v], dtype=float)
        self._port_h = np.array([x.port_hours for x in v], dtype=float)
        self._tank_m3 = np.array([x.tank_volume_m3 for x in v], dtype=float)
        self._capacity = np.array([x.dwt * 0.92 for x in v], dtype=float)

        r = self.routes
        self._distance = np.array([x.distance_nm for x in r], dtype=float)
        self._beaufort = np.array([x.weather_beaufort for x in r], dtype=float)
        self._demand = np.array([x.demand_tons for x in r], dtype=float)
        self._max_transit_h = np.array([x.max_transit_days * 24.0 for x in r], dtype=float)
        self._shore_ok = np.array([1.0 if x.shore_power_available else 0.0 for x in r])
        self._eca_frac = np.array([x.eca_fraction for x in r], dtype=float)

        f = self.fuels
        self._f_energy = np.array([x.energy_density_mj_per_kg for x in f], dtype=float)
        self._f_ef = np.array([x.emission_factor_gco2_per_mj for x in f], dtype=float)
        self._f_cost_gj = np.array([x.cost_per_gj for x in f], dtype=float)
        self._f_sfc_mult = np.array([x.sfc_multiplier for x in f], dtype=float)
        self._f_avail = np.array([x.availability_score for x in f], dtype=float)
        self._f_readiness = np.array([x.readiness_score for x in f], dtype=float)
        self._f_sulphur = np.array([x.sulphur_pct for x in f], dtype=float)
        # A ship burning fuel above the 0.10% ECA cap has to switch to
        # distillate for the controlled part of the voyage. Price the switch
        # rather than forbidding the fuel: that is what operators actually do,
        # and it leaves the solver a real trade-off instead of a wall.
        #
        # The switch fuel comes from the full database, not from this run's
        # chosen subset. A ship that has settled on HFO as its strategic fuel
        # still buys distillate for the Channel, so restricting the solver to
        # HFO must not make the premium quietly vanish.
        compliant = get_fuel(ECA_COMPLIANT_FUEL) or min(
            get_all_fuels(), key=lambda x: x.sulphur_pct
        )
        self._eca_fuel_name = compliant.name
        self._eca_fuel_cost_gj = float(compliant.cost_per_gj)
        self._eca_fuel_ef = float(compliant.emission_factor_gco2_per_mj)
        self._f_needs_switch = (self._f_sulphur > ECA_SULPHUR_LIMIT_PCT + 1e-9).astype(float)
        # Volumetric energy density (MJ/m3) drives the range constraint.
        density_kg_m3 = np.array(
            [
                {"HFO": 991, "VLSFO": 950, "MGO": 890, "LNG": 450, "Methanol": 792,
                 "Ammonia": 682, "Hydrogen": 71}.get(x.name, 900)
                for x in f
            ],
            dtype=float,
        )
        self._f_mj_per_m3 = self._f_energy * density_kg_m3

        # Reference magnitudes used to scale constraint penalties per objective,
        # so a violation costs a comparable amount in each dimension.
        ref = self._reference_solution_objectives()
        self._penalty_scale = np.maximum(ref, 1.0)

        self._bounds = self._build_bounds()

    def _reference_solution_objectives(self) -> np.ndarray:
        """Objectives of a naive round-robin, design-speed, cheapest-fuel plan."""
        route_idx = np.arange(self.n_vessels) % self.n_routes
        speed = self._design_v.copy()
        fuel_idx = np.zeros(self.n_vessels, dtype=int)
        shore = np.zeros(self.n_vessels)
        obj, _ = self._objectives_from_decisions(
            route_idx[None, :], speed[None, :], fuel_idx[None, :], shore[None, :]
        )
        return obj[0]

    def _build_bounds(self) -> np.ndarray:
        bounds = np.zeros((self.n_dimensions, 2), dtype=float)
        for i in range(self.n_vessels):
            base = i * self.genes_per_vessel
            bounds[base] = (0.0, max(self.n_routes - 1, 0) + 0.499)
            bounds[base + 1] = (self._vmin[i], self._vmax[i])
            bounds[base + 2] = (0.0, max(self.n_fuels - 1, 0) + 0.499)
            bounds[base + 3] = (0.0, 100.0)
        return bounds

    @property
    def bounds(self) -> np.ndarray:
        """``(n_dimensions, 2)`` array of lower/upper bounds."""
        return self._bounds

    # -- encoding ---------------------------------------------------------
    def _split(self, X: np.ndarray):
        """Split a population matrix into route / speed / fuel / shore arrays."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.shape[1] != self.n_dimensions:
            raise ValueError(
                f"Expected {self.n_dimensions} decision variables, got {X.shape[1]}"
            )
        G = X.reshape(X.shape[0], self.n_vessels, self.genes_per_vessel)
        route_idx = np.clip(np.rint(G[:, :, 0]), 0, self.n_routes - 1).astype(int)
        speed = G[:, :, 1]
        fuel_idx = np.clip(np.rint(G[:, :, 2]), 0, self.n_fuels - 1).astype(int)
        shore = np.clip(G[:, :, 3], 0.0, 100.0)
        return route_idx, speed, fuel_idx, shore

    def decode_solution(self, x: np.ndarray) -> Dict[str, Any]:
        """Human-readable decoding of a single decision vector."""
        route_idx, speed, fuel_idx, shore = self._split(np.asarray(x, dtype=float))
        assignment = np.zeros((self.n_vessels, self.n_routes))
        assignment[np.arange(self.n_vessels), route_idx[0]] = 1
        return {
            "vessel_assignment": assignment,
            "route_index": route_idx[0],
            "speed": np.clip(speed[0], self._vmin, self._vmax),
            "fuel_selection": fuel_idx[0],
            "shore_power_pct": shore[0],
        }

    def encode_solution(self, decisions: Dict[str, Any]) -> np.ndarray:
        """Inverse of :meth:`decode_solution`."""
        x = np.zeros(self.n_dimensions)
        assignment = np.asarray(decisions.get("vessel_assignment"))
        route_index = decisions.get("route_index")
        for i in range(self.n_vessels):
            if route_index is not None:
                route = int(route_index[i])
            elif assignment is not None and assignment.size:
                hits = np.flatnonzero(assignment[i] == 1)
                route = int(hits[0]) if hits.size else 0
            else:
                route = 0
            base = i * self.genes_per_vessel
            x[base] = route
            x[base + 1] = float(decisions["speed"][i])
            x[base + 2] = float(decisions["fuel_selection"][i])
            x[base + 3] = float(decisions["shore_power_pct"][i])
        return x

    # -- physics ----------------------------------------------------------
    def _voyage_terms(self, route_idx, speed, fuel_idx, shore):
        """Per-vessel voyage physics for a whole population at once."""
        speed = np.clip(speed, self._vmin[None, :], self._vmax[None, :])
        distance = self._distance[route_idx]
        beaufort = self._beaufort[route_idx]
        shore_allowed = shore * self._shore_ok[route_idx]

        sea_hours = distance / np.maximum(speed, 1e-6)

        # Cubic speed-power law, capped at installed power.
        power_kw = self._rated_kw[None, :] * (speed / self._design_v[None, :]) ** 3
        power_kw = np.minimum(power_kw, self._rated_kw[None, :])

        weather_factor = 1.0 + 0.02 * np.power(beaufort, 1.5)
        load_factor = np.power(self._load[None, :] / 100.0, 0.7)

        sfc = BASE_SFC_G_PER_KWH * self._f_sfc_mult[fuel_idx]
        # kg/h -> tonnes over the voyage
        sea_fuel_t = (power_kw * sfc / 1e6) * sea_hours * weather_factor * load_factor

        # Port hotel load, offset by whatever shore power the berth supports.
        port_kwh = self._hotel_kw[None, :] * self._port_h[None, :]
        port_from_shore_kwh = port_kwh * (shore_allowed / 100.0)
        port_from_fuel_kwh = port_kwh - port_from_shore_kwh
        aux_sfc = BASE_SFC_G_PER_KWH * 1.15 * self._f_sfc_mult[fuel_idx]
        port_fuel_t = port_from_fuel_kwh * aux_sfc / 1e6

        fuel_t = sea_fuel_t + port_fuel_t
        energy_mj = fuel_t * 1000.0 * self._f_energy[fuel_idx]

        # Emission Control Areas. A fuel above the 0.10% sulphur cap is illegal
        # inside one, so the ship switches to distillate for that share of the
        # voyage: that energy is priced and emits at the switch fuel's rate,
        # the rest at the chosen fuel's. A ship already on LNG, methanol or
        # ammonia pays nothing here, which is the whole point — the Rotterdam
        # and Felixstowe lanes quietly favour clean fuel without anyone having
        # to hard-code that preference.
        eca_share = self._eca_frac[route_idx] * self._f_needs_switch[fuel_idx]
        switched_mj = energy_mj * eca_share
        native_mj = energy_mj - switched_mj

        co2_t = (native_mj * self._f_ef[fuel_idx] + switched_mj * self._eca_fuel_ef) / 1e6
        bunker_usd = (
            native_mj * self._f_cost_gj[fuel_idx] + switched_mj * self._eca_fuel_cost_gj
        ) / 1000.0
        shore_usd = port_from_shore_kwh * SHORE_POWER_USD_PER_KWH
        total_hours = sea_hours + self._port_h[None, :]
        opex_usd = (total_hours / 24.0) * VESSEL_OPEX_USD_PER_DAY
        carbon_usd = co2_t * self.carbon_price_usd_per_ton

        return {
            "speed": speed,
            "sea_hours": sea_hours,
            "total_hours": total_hours,
            "power_kw": power_kw,
            "fuel_t": fuel_t,
            "energy_mj": energy_mj,
            "co2_t": co2_t,
            "cost_usd": bunker_usd + shore_usd + opex_usd + carbon_usd,
            "bunker_usd": bunker_usd,
            "shore_usd": shore_usd,
            "eca_share": eca_share,
            "eca_switch_mj": switched_mj,
            "opex_usd": opex_usd,
            "shore_allowed": shore_allowed,
            "distance": distance,
        }

    def _objectives_from_decisions(self, route_idx, speed, fuel_idx, shore):
        terms = self._voyage_terms(route_idx, speed, fuel_idx, shore)
        objectives = np.stack(
            [
                terms["fuel_t"].sum(axis=1),
                terms["co2_t"].sum(axis=1),
                terms["cost_usd"].sum(axis=1),
            ],
            axis=1,
        )
        return objectives, terms

    # -- constraints -------------------------------------------------------
    def _violations(self, route_idx, speed, fuel_idx, shore, terms) -> np.ndarray:
        """Total normalised constraint violation per solution (0 = feasible)."""
        n_pop = route_idx.shape[0]
        violation = np.zeros(n_pop)

        # 1. Speed envelope. The bounds keep this at zero for well-formed
        #    solutions, but algorithms may hand us out-of-range vectors.
        below = np.maximum(self._vmin[None, :] - speed, 0.0)
        above = np.maximum(speed - self._vmax[None, :], 0.0)
        violation += ((below + above) / self._design_v[None, :]).sum(axis=1)

        # 2. Route demand coverage: assigned capacity must meet lane demand.
        if self.enforce_demand:
            onehot = np.zeros((n_pop, self.n_vessels, self.n_routes))
            pop_ix = np.repeat(np.arange(n_pop), self.n_vessels)
            ves_ix = np.tile(np.arange(self.n_vessels), n_pop)
            onehot[pop_ix, ves_ix, route_idx.ravel()] = 1.0
            supplied = np.einsum("pvr,v->pr", onehot, self._capacity)
            shortfall = np.maximum(self._demand[None, :] - supplied, 0.0)
            violation += (shortfall / np.maximum(self._demand[None, :], 1.0)).sum(axis=1)

        # 3. Schedule: the voyage must fit inside the lane's transit window.
        late = np.maximum(terms["total_hours"] - self._max_transit_h[route_idx], 0.0)
        violation += (late / self._max_transit_h[route_idx]).sum(axis=1)

        # 4. Range: the bunker tank must hold the voyage's fuel.
        volume_needed_m3 = terms["fuel_t"] * 1000.0 * self._f_energy[fuel_idx] / np.maximum(
            self._f_mj_per_m3[fuel_idx], 1e-6
        )
        over_tank = np.maximum(volume_needed_m3 - self._tank_m3[None, :], 0.0)
        violation += (over_tank / self._tank_m3[None, :]).sum(axis=1)

        # 5. Bunkering availability: a scarce fuel cannot serve the whole fleet.
        for f in range(self.n_fuels):
            share = (fuel_idx == f).mean(axis=1)
            cap = self._f_avail[f] * self._f_readiness[f]
            violation += np.maximum(share - cap, 0.0) * 2.0

        return violation

    # -- public evaluation API --------------------------------------------
    def evaluate_batch(self, X: np.ndarray) -> np.ndarray:
        """Evaluate a population. Returns ``(n_pop, 3)`` penalised objectives."""
        route_idx, speed, fuel_idx, shore = self._split(X)
        objectives, terms = self._objectives_from_decisions(route_idx, speed, fuel_idx, shore)
        violation = self._violations(route_idx, speed, fuel_idx, shore, terms)
        # A flat barrier plus a linear term. The barrier matters: with a purely
        # linear penalty a slightly infeasible plan (skipping one route, say)
        # scores better than any feasible one, because dropping a voyage saves
        # more than the small violation costs. The barrier makes feasibility
        # strictly preferable, and the slope still guides the search back.
        infeasible = (violation > 0.0).astype(float)
        magnitude = FEASIBILITY_BARRIER * infeasible + VIOLATION_WEIGHT * violation
        penalty = magnitude[:, None] * self._penalty_scale[None, :]
        return objectives + penalty

    def evaluate(self, x: np.ndarray) -> np.ndarray:
        """Evaluate one decision vector. Returns a length-3 objective array."""
        return self.evaluate_batch(np.atleast_2d(x))[0]

    def evaluate_raw(self, x: np.ndarray) -> np.ndarray:
        """Objectives **without** the constraint penalty (for reporting)."""
        route_idx, speed, fuel_idx, shore = self._split(np.atleast_2d(x))
        objectives, _ = self._objectives_from_decisions(route_idx, speed, fuel_idx, shore)
        return objectives[0]

    def evaluate_detailed(self, X: np.ndarray):
        """
        Raw objectives and constraint violations for a whole population.

        Reporting uses the raw numbers (a plan's real fuel bill does not
        include a solver penalty) while feasibility is reported separately, so
        an infeasible plan can never masquerade as a cheap one.
        """
        route_idx, speed, fuel_idx, shore = self._split(X)
        objectives, terms = self._objectives_from_decisions(route_idx, speed, fuel_idx, shore)
        violations = self._violations(route_idx, speed, fuel_idx, shore, terms)
        return objectives, violations

    def normalise(self, F: np.ndarray) -> np.ndarray:
        """Scale objectives by the reference plan so they are comparable."""
        return np.asarray(F, dtype=float) / self._penalty_scale

    def check_constraints(self, x: np.ndarray) -> float:
        """Scalar constraint violation for one solution (0 means feasible)."""
        route_idx, speed, fuel_idx, shore = self._split(np.atleast_2d(x))
        _, terms = self._objectives_from_decisions(route_idx, speed, fuel_idx, shore)
        return float(self._violations(route_idx, speed, fuel_idx, shore, terms)[0])

    def is_feasible(self, x: np.ndarray, tol: float = 1e-9) -> bool:
        return self.check_constraints(x) <= tol

    # -- scalarisation for single-objective algorithms ---------------------
    def scalar_weights(self, weights: Optional[Sequence[float]] = None) -> np.ndarray:
        w = np.array(weights if weights is not None else (1 / 3, 1 / 3, 1 / 3), dtype=float)
        if w.size != self.n_objectives:
            raise ValueError(f"weights must have {self.n_objectives} entries")
        total = w.sum()
        return w / total if total > 0 else np.full(self.n_objectives, 1 / self.n_objectives)

    def scalar_objective(self, weights: Optional[Sequence[float]] = None):
        """
        Build a scalar fitness function for PSO / QPSO / QGA.

        Objectives are normalised by the reference plan first, so cost (USD,
        ~1e7) does not swamp fuel (tonnes, ~1e4).
        """
        w = self.scalar_weights(weights)
        scale = self._penalty_scale

        def fitness(x: np.ndarray) -> float:
            return float(np.dot(self.evaluate(x) / scale, w))

        def fitness_batch(X: np.ndarray) -> np.ndarray:
            return (self.evaluate_batch(X) / scale[None, :]) @ w

        fitness.batch = fitness_batch  # type: ignore[attr-defined]
        return fitness

    # -- reporting ---------------------------------------------------------
    def describe_solution(self, x: np.ndarray) -> Dict[str, Any]:
        """Full, presentation-ready breakdown of a single solution."""
        route_idx, speed, fuel_idx, shore = self._split(np.atleast_2d(x))
        objectives, terms = self._objectives_from_decisions(route_idx, speed, fuel_idx, shore)
        violation = float(self._violations(route_idx, speed, fuel_idx, shore, terms)[0])

        assignments = []
        for i, vessel in enumerate(self.vessels):
            route = self.routes[int(route_idx[0, i])]
            fuel = self.fuels[int(fuel_idx[0, i])]
            assignments.append(
                {
                    "vessel_id": vessel.vessel_id,
                    "vessel_name": vessel.name,
                    "vessel_type": vessel.vessel_type,
                    "route_id": route.route_id,
                    "route_name": route.name,
                    "speed_knots": round(float(terms["speed"][0, i]), 2),
                    "fuel_type": fuel.name,
                    "shore_power_pct": round(float(terms["shore_allowed"][0, i]), 1),
                    "distance_nm": round(float(terms["distance"][0, i]), 1),
                    "voyage_days": round(float(terms["total_hours"][0, i]) / 24.0, 2),
                    "fuel_tons": round(float(terms["fuel_t"][0, i]), 2),
                    "co2_tons": round(float(terms["co2_t"][0, i]), 2),
                    "cost_usd": round(float(terms["cost_usd"][0, i]), 2),
                    "dwt": round(float(vessel.dwt), 1),
                    "eca_fraction": round(float(route.eca_fraction), 4),
                    "eca_switch_share": round(float(terms["eca_share"][0, i]), 4),
                    "eca_compliant_fuel": bool(fuel.eca_compliant),
                    "weather_beaufort": round(float(route.weather_beaufort), 2),
                    "cii": assess_voyage(
                        vessel_name=vessel.name,
                        vessel_type=vessel.vessel_type,
                        dwt=vessel.dwt,
                        co2_tons=float(terms["co2_t"][0, i]),
                        distance_nm=float(terms["distance"][0, i]),
                        year=self.cii_year,
                    ),
                }
            )

        fuel_mix: Dict[str, int] = {}
        for i in range(self.n_vessels):
            key = self.fuels[int(fuel_idx[0, i])].name
            fuel_mix[key] = fuel_mix.get(key, 0) + 1

        route_load: Dict[str, Dict[str, float]] = {}
        for r, route in enumerate(self.routes):
            mask = route_idx[0] == r
            route_load[route.name] = {
                "vessels_assigned": int(mask.sum()),
                "capacity_tons": round(float(self._capacity[mask].sum()), 1),
                "demand_tons": round(float(route.demand_tons), 1),
                "covered": bool(self._capacity[mask].sum() >= route.demand_tons),
            }

        return {
            "objectives": {
                "fuel_consumption_tons": round(float(objectives[0, 0]), 2),
                "co2_emissions_tons": round(float(objectives[0, 1]), 2),
                "operational_cost_usd": round(float(objectives[0, 2]), 2),
            },
            "cost_breakdown": {
                "bunker_usd": round(float(terms["bunker_usd"].sum()), 2),
                "shore_power_usd": round(float(terms["shore_usd"].sum()), 2),
                "vessel_opex_usd": round(float(terms["opex_usd"].sum()), 2),
            },
            "constraint_violation": round(violation, 6),
            "feasible": violation <= 1e-9,
            "average_speed_knots": round(float(terms["speed"].mean()), 2),
            "average_shore_power_pct": round(float(terms["shore_allowed"].mean()), 1),
            "fuel_mix": fuel_mix,
            "route_coverage": route_load,
            "assignments": assignments,
            "compliance": {
                "eca_switch_fuel": self._eca_fuel_name,
                "eca_sulphur_limit_pct": ECA_SULPHUR_LIMIT_PCT,
                "vessels_needing_switch": int(
                    sum(1 for a in assignments if a["eca_switch_share"] > 0)
                ),
                "eca_switched_energy_mj": round(float(terms["eca_switch_mj"].sum()), 1),
                "cii": assess_fleet(assignments, year=self.cii_year),
            },
            "season": {
                "month": self.month,
                "month_name": MONTH_NAMES[self.month - 1] if self.month else None,
                "label": season_label(self.month) if self.month else "Annual mean",
                "mean_factor": round(
                    float(np.mean([r.season_factor for r in self.routes])), 3
                ),
            },
        }

    def baseline_vector(self) -> np.ndarray:
        """
        A naive but *feasible* reference plan: conventional fuel, no shore
        power, design speed, and a greedy route assignment that covers demand.

        A round-robin assignment at design speed (what this used to be) misses
        route demand and blows transit windows, so the baseline itself was
        penalised. Comparing an optimised plan against a penalised baseline
        inflates the reported savings, which is why the assignment below is
        greedy rather than positional.
        """
        cheap_fuel = int(np.argmin(self._f_cost_gj)) if self.n_fuels else 0
        route_of = np.full(self.n_vessels, -1, dtype=int)
        speed = self._design_v.copy()

        # Largest ships first, hardest lanes first.
        vessels_by_size = np.argsort(-self._capacity, kind="stable").tolist()
        routes_by_demand = np.argsort(-self._demand, kind="stable").tolist()

        def transit_speed(vessel: int, route: int) -> Optional[float]:
            """Slowest design-or-faster speed that still meets the window."""
            window_h = self._max_transit_h[route] - self._port_h[vessel]
            if window_h <= 0:
                return None
            needed = self._distance[route] / window_h
            if needed > self._vmax[vessel]:
                return None
            return float(np.clip(max(self._design_v[vessel], needed), self._vmin[vessel], self._vmax[vessel]))

        remaining = list(vessels_by_size)
        for r in routes_by_demand:
            covered = 0.0
            still_unassigned = []
            for v in remaining:
                if covered >= self._demand[r]:
                    still_unassigned.append(v)
                    continue
                v_speed = transit_speed(v, r)
                if v_speed is None:
                    still_unassigned.append(v)
                    continue
                route_of[v] = r
                speed[v] = v_speed
                covered += self._capacity[v]
            remaining = still_unassigned

        # Anything left over goes to the shortest lane it can actually serve.
        for v in remaining:
            for r in np.argsort(self._distance, kind="stable"):
                v_speed = transit_speed(v, int(r))
                if v_speed is not None:
                    route_of[v] = int(r)
                    speed[v] = v_speed
                    break
            if route_of[v] < 0:  # no lane fits; take the shortest and run flat out
                r = int(np.argmin(self._distance))
                route_of[v] = r
                speed[v] = self._vmax[v]

        return self.encode_solution(
            {
                "route_index": route_of,
                "speed": speed,
                "fuel_selection": np.full(self.n_vessels, cheap_fuel, dtype=int),
                "shore_power_pct": np.zeros(self.n_vessels),
            }
        )

    def baseline(self) -> Dict[str, Any]:
        """The naive plan every optimised result is compared against (cached)."""
        cached = getattr(self, "_baseline_cache", None)
        if cached is None:
            x = self.baseline_vector()
            cached = self.describe_solution(x)
            cached["decision_vector"] = x.tolist()
            self._baseline_cache = cached
        return cached

    def summary(self) -> Dict[str, Any]:
        return {
            "n_vessels": self.n_vessels,
            "n_routes": self.n_routes,
            "n_dimensions": self.n_dimensions,
            "n_objectives": self.n_objectives,
            "fuel_types": self.fuel_types,
            "objective_names": list(OBJECTIVE_NAMES),
            "objective_labels": list(OBJECTIVE_LABELS),
            "carbon_price_usd_per_ton": self.carbon_price_usd_per_ton,
            "vessels": [v.to_dict() for v in self.vessels],
            "routes": [r.to_dict() for r in self.routes],
        }
