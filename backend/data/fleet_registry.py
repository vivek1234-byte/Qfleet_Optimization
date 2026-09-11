"""
Realistic fleet and trade-lane registry.

The problem builder used to invent vessels called CON-001 on a lane called
"Asia - Europe #2". To a maritime jury that reads as a toy. This module holds a
curated set of plausible Indian-flag vessels and the trade lanes India's ports
actually serve, with sea distances that match published port-to-port tables to
within a few percent.

Vessel names are fictional (Indian shipping naming conventions, no real IMO
numbers). Distances are nautical miles by the customary routing — Suez for
Europe, Malacca for East Asia. Weather is the typical annual-mean Beaufort for
the lane; the Arabian Sea and Bay of Bengal run rougher during the south-west
monsoon, which the higher baselines on those lanes reflect.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class VesselSpec:
    name: str
    vessel_type: str
    dwt: float
    rated_power_kw: float
    design_speed_knots: float
    min_speed_knots: float
    max_speed_knots: float
    tank_volume_m3: float
    hotel_load_kw: float
    home_port: str
    built: int
    flag: str = "India"


@dataclass(frozen=True)
class LaneSpec:
    name: str
    origin: str
    origin_code: str
    destination: str
    destination_code: str
    distance_nm: float
    weather_beaufort: float
    max_transit_days: float
    cargo: str
    shore_power_available: bool
    #: Relative trade volume, used to weight demand across the fleet.
    demand_weight: float
    via: str = ""


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------
# Three classes matching the optimiser's physics assumptions:
#   Container  — 14–24 kn, high installed power, biggest bunker tanks
#   Bulk       — 11–15 kn, low power, long port stays
#   Tanker     — 12–17 kn, mid power
VESSELS: List[VesselSpec] = [
    # -- Container ---------------------------------------------------------
    VesselSpec("MV Sagar Pratap",      "Container",     92_000, 44_000, 20.5, 14.0, 23.0, 7_800, 1_450, "JNPT (Nhava Sheva)", 2016),
    VesselSpec("MV Kaveri Express",    "Container",     68_500, 34_500, 19.5, 13.5, 22.0, 6_200, 1_250, "Chennai",            2014),
    VesselSpec("MV Mundra Pioneer",    "Container",    118_000, 56_000, 21.0, 14.5, 24.0, 9_400, 1_700, "Mundra",             2019),
    VesselSpec("MV Godavari Star",     "Container",     54_000, 28_000, 19.0, 13.0, 21.5, 5_100, 1_100, "Visakhapatnam",      2011),
    VesselSpec("MV Vindhya Voyager",   "Container",     84_000, 40_000, 20.0, 14.0, 22.5, 7_100, 1_380, "JNPT (Nhava Sheva)", 2017),
    VesselSpec("MV Konkan Trader",     "Container",     61_000, 31_000, 19.0, 13.5, 21.5, 5_600, 1_180, "Mumbai",             2013),
    VesselSpec("MV Malabar Crest",     "Container",    104_000, 50_000, 21.0, 14.5, 23.5, 8_600, 1_600, "Kochi",              2020),
    VesselSpec("MV Hooghly Horizon",   "Container",     49_500, 26_000, 18.5, 13.0, 21.0, 4_700, 1_050, "Haldia",             2010),
    # -- Bulk carriers -----------------------------------------------------
    VesselSpec("MV Desh Vaibhav",      "Bulk Carrier",  82_000, 12_500, 14.0, 10.5, 15.5, 3_900, 780,   "Paradip",            2015),
    VesselSpec("MV Jag Arnav",         "Bulk Carrier",  58_000,  9_800, 14.0, 10.5, 15.0, 3_100, 700,   "Visakhapatnam",      2012),
    VesselSpec("MV Mahanadi Bulker",   "Bulk Carrier",  75_500, 11_600, 14.0, 10.5, 15.5, 3_600, 760,   "Paradip",            2018),
    VesselSpec("MV Narmada Carrier",   "Bulk Carrier",  93_000, 13_800, 14.5, 11.0, 16.0, 4_300, 820,   "Kandla",             2017),
    VesselSpec("MV Chambal Bulker",    "Bulk Carrier",  46_000,  8_200, 13.5, 10.0, 14.5, 2_700, 640,   "Mormugao",           2009),
    VesselSpec("MV Sindhu Sagar",      "Bulk Carrier",  64_000, 10_400, 14.0, 10.5, 15.0, 3_300, 720,   "Mundra",             2014),
    # -- Tankers -----------------------------------------------------------
    VesselSpec("MT Nilgiri Spirit",    "Tanker",       115_000, 17_500, 15.0, 11.5, 16.5, 4_800, 950,   "Kandla",             2016),
    VesselSpec("MT Aravalli Pride",    "Tanker",       158_000, 22_000, 15.5, 12.0, 17.0, 5_900, 1_080, "Mumbai",             2019),
    VesselSpec("MT Deccan Glory",      "Tanker",        74_000, 13_200, 15.0, 11.5, 16.0, 3_700, 860,   "Kochi",              2013),
    VesselSpec("MT Satpura Sun",       "Tanker",       105_000, 16_400, 15.0, 11.5, 16.5, 4_500, 920,   "Visakhapatnam",      2015),
    VesselSpec("MT Brahmaputra Wave",  "Tanker",        49_000, 10_200, 14.5, 11.0, 15.5, 2_900, 780,   "Haldia",             2011),
    VesselSpec("MT Western Ghats",     "Tanker",       142_000, 20_500, 15.5, 12.0, 17.0, 5_500, 1_040, "Mundra",             2018),
]

# ---------------------------------------------------------------------------
# Trade lanes
# ---------------------------------------------------------------------------
LANES: List[LaneSpec] = [
    LaneSpec("JNPT – Singapore",        "Nhava Sheva", "INNSA", "Singapore",     "SGSIN", 2_450, 4.4, 10.0, "Containers",          True,  1.35),
    LaneSpec("Mundra – Rotterdam",      "Mundra",      "INMUN", "Rotterdam",     "NLRTM", 6_300, 4.1, 26.0, "Containers",          True,  1.20, via="Suez"),
    LaneSpec("JNPT – Jebel Ali",        "Nhava Sheva", "INNSA", "Jebel Ali",     "AEJEA", 1_180, 3.8,  6.0, "Containers",          True,  1.30),
    LaneSpec("Chennai – Colombo",       "Chennai",     "INMAA", "Colombo",       "LKCMB",   580, 3.9,  4.0, "Transhipment boxes",  True,  1.10),
    LaneSpec("Mundra – Shanghai",       "Mundra",      "INMUN", "Shanghai",      "CNSHA", 4_650, 4.6, 20.0, "Containers",          True,  1.05, via="Malacca"),
    LaneSpec("Visakhapatnam – Port Klang", "Visakhapatnam", "INVTZ", "Port Klang", "MYPKG", 1_650, 4.3,  8.0, "Steel & containers", True,  0.95),
    LaneSpec("Paradip – Qingdao",       "Paradip",     "INPRT", "Qingdao",       "CNTAO", 3_900, 4.7, 18.0, "Iron ore",            False, 1.15, via="Malacca"),
    LaneSpec("Kandla – Jeddah",         "Kandla",      "INIXY", "Jeddah",        "SAJED", 1_720, 4.0,  8.5, "Crude & products",    False, 1.00),
    LaneSpec("Mumbai – Durban",         "Mumbai",      "INBOM", "Durban",        "ZADUR", 4_250, 4.9, 19.0, "Containers",          True,  0.85),
    LaneSpec("Kochi – Jeddah",          "Kochi",       "INCOK", "Jeddah",        "SAJED", 2_050, 4.2,  9.5, "Products",            False, 0.80),
    LaneSpec("Haldia – Yangon",         "Haldia",      "INHAL", "Yangon",        "MMRGN",   800, 4.5,  5.0, "Bulk & general",      False, 0.70),
    LaneSpec("Kandla – Dar es Salaam",  "Kandla",      "INIXY", "Dar es Salaam", "TZDAR", 2_650, 4.6, 12.0, "Bulk fertiliser",     False, 0.75),
    LaneSpec("Chennai – Jakarta",       "Chennai",     "INMAA", "Jakarta",       "IDJKT", 1_900, 4.1,  9.0, "Containers",          True,  0.90),
    LaneSpec("Mormugao – Jinzhou",      "Mormugao",    "INMRM", "Jinzhou",       "CNJIN", 5_100, 4.8, 22.0, "Iron ore",            False, 0.95, via="Malacca"),
    LaneSpec("JNPT – Felixstowe",       "Nhava Sheva", "INNSA", "Felixstowe",    "GBFXT", 6_450, 4.2, 26.5, "Containers",          True,  1.10, via="Suez"),
    LaneSpec("Visakhapatnam – Singapore", "Visakhapatnam", "INVTZ", "Singapore", "SGSIN", 1_950, 4.3,  9.0, "Containers",          True,  1.00),
]


def vessel_names() -> List[str]:
    return [v.name for v in VESSELS]


def lane_names() -> List[str]:
    return [l.name for l in LANES]


def registry_summary() -> Dict[str, object]:
    """Everything the API exposes about the registry."""
    return {
        "vessel_count": len(VESSELS),
        "lane_count": len(LANES),
        "vessels": [
            {
                "name": v.name,
                "vessel_type": v.vessel_type,
                "dwt": v.dwt,
                "rated_power_kw": v.rated_power_kw,
                "design_speed_knots": v.design_speed_knots,
                "speed_range_knots": [v.min_speed_knots, v.max_speed_knots],
                "tank_volume_m3": v.tank_volume_m3,
                "home_port": v.home_port,
                "built": v.built,
                "flag": v.flag,
            }
            for v in VESSELS
        ],
        "lanes": [
            {
                "name": l.name,
                "origin": l.origin,
                "origin_code": l.origin_code,
                "destination": l.destination,
                "destination_code": l.destination_code,
                "distance_nm": l.distance_nm,
                "via": l.via or None,
                "typical_beaufort": l.weather_beaufort,
                "max_transit_days": l.max_transit_days,
                "cargo": l.cargo,
                "shore_power_available": l.shore_power_available,
            }
            for l in LANES
        ],
    }
