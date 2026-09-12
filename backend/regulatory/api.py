"""
Regulatory compliance API.

Two regimes an operator is actually measured against, both of which change
what an optimal deployment looks like:

  * **MARPOL Annex VI emission control areas.** Inside one, fuel sulphur is
    capped at 0.10%, so a ship on HFO or VLSFO has to switch to distillate for
    that stretch. The optimiser prices that switch, so clean-fuel vessels
    quietly win the European lanes without anyone hard-coding a preference.

  * **The IMO Carbon Intensity Indicator.** Since 2023 every cargo ship over
    5,000 GT carries an A-E rating, and D three years running or E once forces
    a corrective action plan. This is the number a commercial operator is
    managed against.

Both are also served to the frontend so the map can draw the zones and the
plan table can carry a rating per vessel.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import Depends, APIRouter, Query
from auth.permissions import reference_data, require_module
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from ..core.errors import ValidationError
    from ..data.carbon_intensity import (
        CII_SHIP_TYPES,
        REDUCTION_FACTOR_PCT,
        assess_fleet,
        band_boundaries,
        reduction_factor_pct,
        reference_cii,
        reference_table,
        required_cii,
        ship_type_for,
    )
    from ..data.fleet_registry import VESSELS
    from ..data.sea_routes import (
        ECA_ZONES,
        GLOBAL_SULPHUR_CAP_PCT,
        LANE_ECA,
        sea_routes_summary,
    )
    from ..data.seasonality import basin_reference, monthly_profile
    from ..data.sea_state import build_alerts
    from ..data.fleet_registry import LANES
except ImportError:  # pragma: no cover
    from core.errors import ValidationError
    from data.carbon_intensity import (
        CII_SHIP_TYPES,
        REDUCTION_FACTOR_PCT,
        assess_fleet,
        band_boundaries,
        reduction_factor_pct,
        reference_cii,
        reference_table,
        required_cii,
        ship_type_for,
    )
    from data.fleet_registry import LANES, VESSELS
    from data.sea_routes import (
        ECA_ZONES,
        GLOBAL_SULPHUR_CAP_PCT,
        LANE_ECA,
        sea_routes_summary,
    )
    from data.seasonality import basin_reference, monthly_profile
    from data.sea_state import build_alerts

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/regulatory", tags=["Regulatory"])

MIN_YEAR, MAX_YEAR = 2023, 2040


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class VoyageRating(BaseModel):
    """One voyage to rate."""

    model_config = ConfigDict(extra="forbid")

    vessel_name: str = Field("", max_length=120)
    vessel_type: str = Field(..., description=f"One of: {', '.join(CII_SHIP_TYPES)}")
    dwt: float = Field(..., gt=0, le=600_000)
    co2_tons: float = Field(..., ge=0, le=5_000_000)
    distance_nm: float = Field(..., gt=0, le=50_000)

    @field_validator("vessel_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in CII_SHIP_TYPES:
            raise ValueError(
                f"vessel_type must be one of: {', '.join(CII_SHIP_TYPES)}"
            )
        return v


class RatingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voyages: List[VoyageRating] = Field(..., min_length=1, max_length=200)
    year: int = Field(2026, ge=MIN_YEAR, le=MAX_YEAR)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/eca-zones", dependencies=[Depends(reference_data())])
def get_eca_zones() -> Dict[str, Any]:
    """
    Emission control area outlines, and how much of each lane runs inside one.

    Outlines are indicative simplifications for map display and planning, not
    navigational boundaries; the authoritative coordinates live in MARPOL
    Annex VI. Two of the sixteen registry lanes are affected — the Rotterdam
    and Felixstowe runs, each spending roughly a third of the voyage inside
    the Mediterranean or North Sea SECA.
    """
    payload = sea_routes_summary()
    return {
        "global_sulphur_cap_pct": GLOBAL_SULPHUR_CAP_PCT,
        "eca_sulphur_limit_pct": 0.10,
        "zones": [zone.to_dict() for zone in ECA_ZONES],
        "lanes": [
            {"name": name, **profile} for name, profile in LANE_ECA.items()
        ],
        "affected_lane_count": sum(
            1 for p in LANE_ECA.values() if float(p["eca_fraction"]) > 0
        ),
        "disclaimer": payload["disclaimer"],
    }


@router.get("/routes", dependencies=[Depends(reference_data())])
def get_routes() -> Dict[str, Any]:
    """
    Sea-route geometry: ports, chokepoints and the waypoint path of each lane.

    This is what lets a client draw a voyage that goes through the Suez Canal
    rather than across the Sahara. Segment lengths are rescaled so they sum to
    the registry's published distance for the lane.
    """
    return sea_routes_summary()


@router.get("/cii-reference", dependencies=[Depends(reference_data())])
def get_cii_reference(
    year: int = Query(2026, ge=MIN_YEAR, le=MAX_YEAR),
) -> Dict[str, Any]:
    """
    The CII constants and, for every vessel in the registry, the line it has
    to get under this year.

    Published so a reviewer can check the arithmetic rather than take the
    rating on trust.
    """
    table = reference_table()
    table["year"] = year
    table["reduction_factor_pct"] = round(reduction_factor_pct(year), 2)
    table["adopted_reduction_factors"] = REDUCTION_FACTOR_PCT
    table["vessels"] = [
        {
            "name": v.name,
            "vessel_type": v.vessel_type,
            "dwt": v.dwt,
            "reference_cii": round(reference_cii(ship_type_for(v.vessel_type), v.dwt), 4),
            "required_cii": round(required_cii(ship_type_for(v.vessel_type), v.dwt, year), 4),
            "boundaries": band_boundaries(ship_type_for(v.vessel_type), v.dwt, year),
        }
        for v in VESSELS
        if ship_type_for(v.vessel_type) is not None
    ]
    table["unit"] = "gCO2 per dwt-nautical mile"
    return table


@router.post("/cii", dependencies=[Depends(require_module('compliance'))])
def rate_voyages(request: RatingRequest) -> Dict[str, Any]:
    """
    Rate a set of voyages A-E against the IMO carbon intensity requirement.

    Feed it the ``assignments`` array from an optimisation plan to see what
    that deployment does to the fleet's compliance position. The response
    carries its own caveats: CII is an annual indicator and rating a single
    voyage extrapolates it.
    """
    try:
        return assess_fleet(
            [v.model_dump() for v in request.voyages], year=request.year
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc


@router.get("/seasonality", dependencies=[Depends(reference_data())])
def get_seasonality(lane: Optional[str] = Query(None, max_length=120)) -> Dict[str, Any]:
    """
    Monthly weather multipliers by sea basin, and per lane when one is named.

    Indicative climatology rather than measured data — the shape is right, the
    values are not observations. It is what lets the optimiser answer "what
    does the south-west monsoon cost me on the Arabian Sea run".
    """
    payload = basin_reference()
    payload["lanes"] = [
        {
            "name": l.name,
            "basins": [{"basin": b, "share": w} for b, w in l.basins],
            "annual_mean_beaufort": l.weather_beaufort,
            "monthly": monthly_profile(l.basins),
        }
        for l in LANES
        if lane is None or l.name == lane
    ]
    if lane is not None and not payload["lanes"]:
        raise ValidationError(f"Unknown lane '{lane}'.")
    return payload


@router.get("/alerts", dependencies=[Depends(reference_data())])
def get_sea_state_alerts(
    month: Optional[int] = Query(None, ge=1, le=12, description="1-12. Defaults to now."),
    live: bool = Query(True, description="Query the marine forecast. False forces climatology."),
) -> Dict[str, Any]:
    """
    Lanes whose sea state warrants a warning, worst first.

    Three severities: `severe` at gale force and above, `rough` at near gale,
    and `unseasonal` for a lane that is not rough in absolute terms but is
    well above what it normally does this month — the case a planner misses,
    because the lane's annual mean looks perfectly fine.

    Reference data: any signed-in user, because the warning dot belongs in the
    header on every screen, not only for whoever holds Compliance.

    Figures come from a live marine forecast where one is reachable and from
    the bundled climatology where it is not — per lane, not all-or-nothing.
    Every alert carries its own `source`, and `live.mode` says whether the set
    as a whole is `observed`, `mixed` or `climatology`. A conference Wi-Fi
    failure degrades the numbers, never the page.

    Tides are absent on purpose. The response says so in `not_modelled` rather
    than quietly omitting them, because a caller asking for weather warnings
    deserves to know which hazards this can and cannot see.
    """
    # A month other than the current one is a planning question, and no feed
    # forecasts July from September — so an outlook is always climatology.
    use_live = live and month is None
    return build_alerts(LANES, month, live=use_live)
