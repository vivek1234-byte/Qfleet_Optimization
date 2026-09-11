"""
IMO operational Carbon Intensity Indicator (CII).

Since 1 January 2023 every cargo ship of 5,000 GT and above has had to report
an attained annual CII and carry a rating from A to E. A ship rated D three
years running, or E once, must submit a corrective action plan. That makes CII
the single number a commercial operator is actually managed against, which is
why it belongs in a fleet optimiser rather than a compliance spreadsheet.

The arithmetic:

    attained CII = total CO2 (g) / (capacity x distance sailed (nm))
    reference CII = a x capacity ^ (-c)                   [MEPC.353(78)]
    required CII = (1 - Z/100) x reference CII            [MEPC.338(76)]
    rating boundary k = d_k x required CII                [MEPC.354(78)]

``capacity`` is deadweight for bulk carriers and tankers and, for container
ships, 70% of deadweight. Z is the annual reduction factor against the 2019
baseline: 5% in 2023 rising to 11% in 2026.

Two honest caveats, both surfaced in the API response:

  * CII is an **annual** indicator computed from a whole year of reported
    operational data. Rating a single voyage, as this module does when handed
    one leg of a deployment plan, is an extrapolation — useful for comparing
    two plans against each other, not a substitute for the regulatory
    calculation.
  * The correction factors and voyage exclusions in MEPC.355(78) (ice class,
    ship-to-ship transfer, port stays and so on) are not applied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class CiiShipType:
    """Reference-line constants and rating boundaries for one ship type."""

    key: str
    label: str
    #: Reference line CII_ref = a * capacity ** -c, from MEPC.353(78).
    a: float
    c: float
    #: Capacity basis: "dwt", or "dwt x 0.7" for container ships.
    capacity_basis: str
    #: dd vectors from MEPC.354(78): boundaries between A/B, B/C, C/D, D/E
    #: as multiples of the required CII.
    dd: Tuple[float, float, float, float]
    #: Deadweight above which the reference line is capped.
    capacity_cap: Optional[float] = None


CII_SHIP_TYPES: Dict[str, CiiShipType] = {
    "Bulk Carrier": CiiShipType(
        key="bulk_carrier",
        label="Bulk carrier",
        a=4745.0,
        c=0.622,
        capacity_basis="dwt",
        dd=(0.86, 0.94, 1.06, 1.18),
        capacity_cap=279_000.0,
    ),
    "Tanker": CiiShipType(
        key="tanker",
        label="Tanker",
        a=5247.0,
        c=0.610,
        capacity_basis="dwt",
        dd=(0.82, 0.93, 1.08, 1.28),
    ),
    "Container": CiiShipType(
        key="container_ship",
        label="Container ship",
        a=1984.0,
        c=0.489,
        capacity_basis="dwt x 0.7",
        dd=(0.83, 0.94, 1.07, 1.19),
    ),
}

#: Annual reduction factor Z, % below the 2019 reference line.
REDUCTION_FACTOR_PCT: Dict[int, float] = {
    2023: 5.0,
    2024: 7.0,
    2025: 9.0,
    2026: 11.0,
}

#: Phase 2 (2027-2030) factors are still to be agreed at MEPC; extrapolating
#: the 2% a year trend is a planning assumption, not regulation.
ASSUMED_TREND_PCT_PER_YEAR = 2.0

RATING_BANDS = ("A", "B", "C", "D", "E")

RATING_MEANING: Dict[str, str] = {
    "A": "Major superior performance.",
    "B": "Minor superior performance.",
    "C": "Moderate. Meets the required carbon intensity.",
    "D": "Minor inferior. Three consecutive years of D requires a corrective action plan.",
    "E": "Inferior. A single year at E requires a corrective action plan.",
}


def ship_type_for(vessel_type: str) -> Optional[CiiShipType]:
    """Map a registry vessel class onto a CII ship type."""
    return CII_SHIP_TYPES.get(vessel_type)


def reduction_factor_pct(year: int) -> float:
    """Z for a year, extrapolating past 2026 on the agreed trend."""
    year = int(year)
    if year in REDUCTION_FACTOR_PCT:
        return REDUCTION_FACTOR_PCT[year]
    if year < min(REDUCTION_FACTOR_PCT):
        return 0.0
    latest = max(REDUCTION_FACTOR_PCT)
    return REDUCTION_FACTOR_PCT[latest] + (year - latest) * ASSUMED_TREND_PCT_PER_YEAR


def capacity_for(ship_type: CiiShipType, dwt: float) -> float:
    """The capacity term in the CII denominator."""
    dwt = float(dwt)
    if ship_type.capacity_cap is not None:
        dwt = min(dwt, ship_type.capacity_cap)
    return dwt * 0.7 if ship_type.capacity_basis == "dwt x 0.7" else dwt


def reference_cii(ship_type: CiiShipType, dwt: float) -> float:
    """CII_ref for this ship, gCO2 per dwt-nautical mile."""
    capacity = capacity_for(ship_type, dwt)
    if capacity <= 0:
        return 0.0
    return ship_type.a * capacity ** (-ship_type.c)


def required_cii(ship_type: CiiShipType, dwt: float, year: int) -> float:
    """The line this ship has to get under in ``year``."""
    return reference_cii(ship_type, dwt) * (1.0 - reduction_factor_pct(year) / 100.0)


def rate(attained: float, required: float, ship_type: CiiShipType) -> str:
    """Band A-E for an attained CII against its requirement."""
    if required <= 0:
        return "E"
    d1, d2, d3, d4 = ship_type.dd
    ratio = attained / required
    if ratio <= d1:
        return "A"
    if ratio <= d2:
        return "B"
    if ratio <= d3:
        return "C"
    if ratio <= d4:
        return "D"
    return "E"


def band_boundaries(ship_type: CiiShipType, dwt: float, year: int) -> Dict[str, float]:
    """The four rating boundaries in gCO2/dwt-nm, for plotting."""
    req = required_cii(ship_type, dwt, year)
    d1, d2, d3, d4 = ship_type.dd
    return {
        "A_B": round(req * d1, 4),
        "B_C": round(req * d2, 4),
        "C_D": round(req * d3, 4),
        "D_E": round(req * d4, 4),
    }


def assess_voyage(
    *,
    vessel_name: str,
    vessel_type: str,
    dwt: float,
    co2_tons: float,
    distance_nm: float,
    year: int = 2026,
) -> Dict[str, object]:
    """
    Rate one voyage as if it were the ship's whole year.

    The extrapolation is the point: a plan that puts a vessel on a slow,
    well-loaded leg produces a better number than one that sprints it half
    empty, and that difference is exactly what the optimiser is trading.
    """
    ship_type = ship_type_for(vessel_type)
    if ship_type is None:
        return {
            "vessel_name": vessel_name,
            "vessel_type": vessel_type,
            "rated": False,
            "reason": f"No CII reference line for vessel type '{vessel_type}'.",
        }

    capacity = capacity_for(ship_type, dwt)
    denominator = capacity * float(distance_nm)
    if denominator <= 0:
        return {
            "vessel_name": vessel_name,
            "vessel_type": vessel_type,
            "rated": False,
            "reason": "Capacity and distance must both be positive.",
        }

    attained = (float(co2_tons) * 1_000_000.0) / denominator  # tonnes -> grams
    required = required_cii(ship_type, dwt, year)
    band = rate(attained, required, ship_type)

    return {
        "vessel_name": vessel_name,
        "vessel_type": vessel_type,
        "rated": True,
        "ship_type": ship_type.label,
        "dwt": round(float(dwt), 1),
        "capacity_used": round(capacity, 1),
        "capacity_basis": ship_type.capacity_basis,
        "year": int(year),
        "reduction_factor_pct": round(reduction_factor_pct(year), 2),
        "attained_cii": round(attained, 4),
        "required_cii": round(required, 4),
        "reference_cii": round(reference_cii(ship_type, dwt), 4),
        "ratio": round(attained / required, 4) if required > 0 else None,
        "rating": band,
        "rating_meaning": RATING_MEANING[band],
        "boundaries": band_boundaries(ship_type, dwt, year),
        "unit": "gCO2 per dwt-nautical mile",
        "co2_tons": round(float(co2_tons), 3),
        "distance_nm": round(float(distance_nm), 1),
    }


def assess_fleet(voyages: Sequence[Dict[str, object]], year: int = 2026) -> Dict[str, object]:
    """Rate a whole deployment plan and summarise the distribution."""
    results: List[Dict[str, object]] = []
    for v in voyages:
        results.append(
            assess_voyage(
                vessel_name=str(v.get("vessel_name", "")),
                vessel_type=str(v.get("vessel_type", "")),
                dwt=float(v.get("dwt", 0.0)),
                co2_tons=float(v.get("co2_tons", 0.0)),
                distance_nm=float(v.get("distance_nm", 0.0)),
                year=year,
            )
        )

    rated = [r for r in results if r.get("rated")]
    distribution = {band: 0 for band in RATING_BANDS}
    for r in rated:
        distribution[str(r["rating"])] += 1

    compliant = sum(distribution[b] for b in ("A", "B", "C"))
    total_co2 = sum(float(r["co2_tons"]) for r in rated)
    total_dwt_nm = sum(float(r["capacity_used"]) * float(r["distance_nm"]) for r in rated)

    return {
        "year": int(year),
        "reduction_factor_pct": round(reduction_factor_pct(year), 2),
        "vessels": results,
        "rated_count": len(rated),
        "distribution": distribution,
        "compliant_count": compliant,
        "compliant_pct": round(100.0 * compliant / len(rated), 1) if rated else 0.0,
        "at_risk": [
            {"vessel_name": r["vessel_name"], "rating": r["rating"], "ratio": r["ratio"]}
            for r in rated
            if r["rating"] in ("D", "E")
        ],
        "fleet_attained_cii": (
            round(total_co2 * 1_000_000.0 / total_dwt_nm, 4) if total_dwt_nm > 0 else None
        ),
        "caveats": [
            "CII is an annual indicator computed from a full year of reported operational "
            "data. Rating a single voyage extrapolates it, which is valid for comparing two "
            "plans against each other but is not the regulatory calculation.",
            "Correction factors and voyage exclusions under MEPC.355(78) are not applied.",
            "Reduction factors beyond 2026 are an extrapolation of the agreed trend, not "
            "adopted regulation.",
        ],
    }


def reference_table() -> Dict[str, object]:
    """The constants themselves, so a reviewer can check the arithmetic."""
    return {
        "ship_types": [
            {
                "vessel_type": vessel_type,
                "label": st.label,
                "a": st.a,
                "c": st.c,
                "capacity_basis": st.capacity_basis,
                "capacity_cap": st.capacity_cap,
                "dd_vector": list(st.dd),
                "boundary_labels": ["A/B", "B/C", "C/D", "D/E"],
            }
            for vessel_type, st in CII_SHIP_TYPES.items()
        ],
        "reduction_factor_pct": REDUCTION_FACTOR_PCT,
        "assumed_trend_pct_per_year": ASSUMED_TREND_PCT_PER_YEAR,
        "rating_meaning": RATING_MEANING,
        "formulae": {
            "attained": "CII = total CO2 (g) / (capacity x distance sailed (nm))",
            "reference": "CII_ref = a x capacity ^ (-c)",
            "required": "CII_req = (1 - Z/100) x CII_ref",
            "boundary": "band boundary k = d_k x CII_req",
        },
        "sources": [
            "MEPC.352(78) - CII guidelines",
            "MEPC.353(78) - reference lines",
            "MEPC.354(78) - rating boundaries (dd vectors)",
            "MEPC.338(76) - reduction factors",
        ],
    }
