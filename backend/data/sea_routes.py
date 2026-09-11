"""
Sea-route geometry and MARPOL Annex VI emission control areas.

This module is the single source of truth for *where* a lane actually goes.
The registry knows a lane is 6,300 nautical miles; this knows it runs down the
Arabian Sea, through Bab-el-Mandeb, up the Red Sea, through the Suez Canal,
across the Mediterranean and out past Gibraltar. That matters for two reasons
beyond drawing a pretty line:

  * the fraction of a voyage spent inside an Emission Control Area determines
    whether a ship can legally burn its cheap fuel there, and
  * the basins a lane crosses determine how the monsoon hits it.

Waypoints are hand-placed sea positions in [latitude, longitude] degrees,
checked against a coastline render so no leg crosses land. Segment lengths are
great-circle; the sum is close to but not exactly the registry's published
distance, so callers that need positions should rescale (see
``lane_geometry``).

ECA outlines are **indicative** simplifications for planning illustration and
map display. They are not navigational boundaries — the authoritative
coordinates are in MARPOL Annex VI and the relevant IMO resolutions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

try:
    from .fleet_registry import LANES, LaneSpec
except ImportError:  # pragma: no cover - direct script execution
    from data.fleet_registry import LANES, LaneSpec

Coord = Tuple[float, float]  # (lat, lon)


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
PORT_POSITIONS: Dict[str, Coord] = {
    "Nhava Sheva": (18.95, 72.95),
    "Mumbai": (18.94, 72.84),
    "Mundra": (22.74, 69.70),
    "Kandla": (23.02, 70.22),
    "Chennai": (13.09, 80.29),
    "Visakhapatnam": (17.69, 83.30),
    "Paradip": (20.26, 86.68),
    "Kochi": (9.97, 76.26),
    "Haldia": (22.03, 88.09),
    "Mormugao": (15.40, 73.80),
    "Singapore": (1.26, 103.83),
    "Rotterdam": (51.95, 4.14),
    "Felixstowe": (51.96, 1.35),
    "Jebel Ali": (25.01, 55.06),
    "Colombo": (6.95, 79.84),
    "Shanghai": (31.23, 121.80),
    "Port Klang": (3.00, 101.39),
    "Qingdao": (36.07, 120.32),
    "Jeddah": (21.48, 39.18),
    "Durban": (-29.87, 31.03),
    "Yangon": (16.77, 96.17),
    "Dar es Salaam": (-6.82, 39.29),
    "Jakarta": (-6.10, 106.88),
    "Jinzhou": (40.80, 121.05),
}

#: Chokepoints worth naming on a chart. Position is the transit waypoint.
CHOKEPOINTS: List[Dict[str, object]] = [
    {"name": "Suez Canal", "lat": 30.50, "lon": 32.35},
    {"name": "Bab-el-Mandeb", "lat": 12.60, "lon": 43.40},
    {"name": "Strait of Hormuz", "lat": 26.30, "lon": 56.50},
    {"name": "Malacca Strait", "lat": 3.50, "lon": 99.50},
    {"name": "Gibraltar", "lat": 35.95, "lon": -5.60},
    {"name": "Dover Strait", "lat": 50.90, "lon": 1.50},
    {"name": "Mozambique Channel", "lat": -18.00, "lon": 41.50},
    {"name": "Sunda Strait", "lat": -5.90, "lon": 105.60},
]


# ---------------------------------------------------------------------------
# Reusable legs
# ---------------------------------------------------------------------------
_ARABIAN_SEA_W: List[Coord] = [(21.0, 66.0), (16.0, 60.0), (13.5, 52.0)]
_RED_SEA: List[Coord] = [
    (12.6, 43.4),
    (15.5, 41.4),
    (20.0, 38.5),
    (25.0, 36.0),
    (27.6, 34.2),
    (29.4, 32.6),
]
_SUEZ_TO_GIBRALTAR: List[Coord] = [
    (31.3, 32.3),
    (33.2, 28.0),
    (34.6, 22.0),
    (36.3, 15.0),
    (37.4, 10.0),
    (37.6, 4.0),
    (36.6, -1.0),
    (35.95, -5.6),
]
_GIBRALTAR_TO_DOVER: List[Coord] = [
    (36.4, -9.4),
    (41.0, -10.2),
    (45.5, -8.6),
    (48.4, -6.0),
    (49.9, -2.5),
    (50.6, 0.6),
    (50.95, 1.6),
]
# Adam's Bridge closes the Palk Strait to deep-draught ships, so everything
# bound east rounds Dondra Head.
_DONDRA_TO_MALACCA: List[Coord] = [
    (5.6, 80.8),
    (5.8, 88.0),
    (5.9, 94.0),
    (5.4, 97.6),
    (3.6, 100.2),
    (2.0, 102.4),
]
_MALACCA_TO_EAST_CHINA: List[Coord] = [
    (1.4, 104.2),
    (4.5, 106.5),
    (10.0, 109.0),
    (15.5, 112.0),
    (20.5, 115.5),
    (24.5, 119.5),
    (28.0, 122.5),
]

#: Intermediate sea waypoints per lane, keyed by the registry lane name.
LANE_WAYPOINTS: Dict[str, List[Coord]] = {
    "JNPT – Singapore": [(14.5, 72.0), (8.5, 75.0), *_DONDRA_TO_MALACCA],
    "Mundra – Rotterdam": [
        *_ARABIAN_SEA_W,
        *_RED_SEA,
        *_SUEZ_TO_GIBRALTAR,
        *_GIBRALTAR_TO_DOVER,
        (51.5, 3.0),
    ],
    "JNPT – Jebel Ali": [(20.5, 68.5), (23.5, 62.5), (25.2, 58.0), (26.3, 56.5), (25.9, 55.6)],
    "Chennai – Colombo": [(10.5, 81.5), (7.5, 82.3), (5.6, 81.2), (5.5, 79.9)],
    "Mundra – Shanghai": [
        (20.5, 67.5),
        (13.0, 69.5),
        (8.0, 74.5),
        *_DONDRA_TO_MALACCA,
        *_MALACCA_TO_EAST_CHINA,
        (30.5, 123.0),
    ],
    "Visakhapatnam – Port Klang": [
        (14.5, 85.5),
        (9.0, 90.5),
        (6.2, 95.5),
        (5.3, 97.8),
        (3.8, 100.0),
    ],
    "Paradip – Qingdao": [
        (18.0, 88.0),
        (11.5, 92.5),
        (6.5, 96.0),
        (5.2, 97.8),
        (2.2, 102.2),
        *_MALACCA_TO_EAST_CHINA,
        (31.5, 124.0),
        (34.5, 123.0),
    ],
    "Kandla – Jeddah": [
        *_ARABIAN_SEA_W,
        (12.4, 45.0),
        (12.6, 43.4),
        (15.5, 41.3),
        (18.5, 40.0),
    ],
    "Mumbai – Durban": [
        (15.0, 70.0),
        (8.0, 66.0),
        (1.0, 61.0),
        (-6.0, 54.0),
        (-13.0, 46.5),
        (-18.5, 41.8),
        (-24.0, 37.0),
        (-28.0, 33.0),
    ],
    "Kochi – Jeddah": [
        (9.0, 72.0),
        (11.0, 64.0),
        (12.6, 55.0),
        (12.4, 45.5),
        (12.6, 43.4),
        (16.0, 41.0),
        (19.5, 39.7),
    ],
    "Haldia – Yangon": [(20.6, 88.3), (18.0, 89.5), (15.5, 92.5), (14.8, 95.0), (15.6, 95.9)],
    "Kandla – Dar es Salaam": [
        (20.5, 66.5),
        (13.5, 60.0),
        (6.0, 55.0),
        (-1.0, 49.0),
        (-5.5, 42.5),
    ],
    "Chennai – Jakarta": [
        (9.5, 83.5),
        (6.0, 90.0),
        (5.7, 94.5),
        (5.4, 97.6),
        (3.6, 100.2),
        (2.0, 102.4),
        (1.1, 104.4),
        (-1.5, 105.6),
        (-4.6, 106.1),
    ],
    "Mormugao – Jinzhou": [
        (13.5, 72.8),
        (8.0, 76.5),
        *_DONDRA_TO_MALACCA,
        *_MALACCA_TO_EAST_CHINA,
        (31.5, 124.0),
        (35.0, 123.5),
        (38.0, 122.0),
    ],
    "JNPT – Felixstowe": [
        (16.0, 69.5),
        *_ARABIAN_SEA_W[1:],
        *_RED_SEA,
        *_SUEZ_TO_GIBRALTAR,
        *_GIBRALTAR_TO_DOVER,
        (51.7, 2.1),
    ],
    "Visakhapatnam – Singapore": [
        (14.5, 86.0),
        (9.5, 91.0),
        (6.3, 95.5),
        (5.3, 97.8),
        (3.6, 100.2),
        (2.0, 102.4),
    ],
}


# ---------------------------------------------------------------------------
# Emission Control Areas (MARPOL Annex VI)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class EcaZone:
    """
    One emission control area.

    ``polygon`` is an indicative outline in (lat, lon), closed implicitly.
    ``sulphur_limit_pct`` is the fuel sulphur cap inside the area; the global
    cap outside every ECA has been 0.50% m/m since 1 January 2020.
    """

    name: str
    short_name: str
    pollutants: Tuple[str, ...]
    sulphur_limit_pct: float
    in_force_since: str
    polygon: Tuple[Coord, ...]
    note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "short_name": self.short_name,
            "pollutants": list(self.pollutants),
            "sulphur_limit_pct": self.sulphur_limit_pct,
            "in_force_since": self.in_force_since,
            "polygon": [[lat, lon] for lat, lon in self.polygon],
            "note": self.note,
        }


#: Global sulphur cap outside any ECA, % m/m, since 1 Jan 2020 (IMO 2020).
GLOBAL_SULPHUR_CAP_PCT = 0.50

ECA_ZONES: List[EcaZone] = [
    EcaZone(
        name="Baltic Sea Emission Control Area",
        short_name="Baltic SECA",
        pollutants=("SOx", "NOx"),
        sulphur_limit_pct=0.10,
        in_force_since="2006 (SOx), 2021 (NOx, new builds)",
        polygon=(
            (65.9, 22.5), (63.5, 21.0), (60.5, 19.2), (59.6, 22.8), (60.0, 28.2),
            (59.4, 28.0), (57.8, 24.0), (55.8, 21.0), (54.5, 19.5), (54.4, 14.2),
            (54.1, 11.0), (55.5, 10.3), (57.6, 10.6), (58.9, 11.2), (59.3, 17.5),
            (61.5, 18.0), (63.6, 19.5), (65.9, 22.5),
        ),
    ),
    EcaZone(
        name="North Sea Emission Control Area",
        short_name="North Sea SECA",
        pollutants=("SOx", "NOx"),
        sulphur_limit_pct=0.10,
        in_force_since="2007 (SOx), 2021 (NOx, new builds)",
        polygon=(
            (62.0, -4.0), (62.0, 5.0), (57.8, 8.2), (55.0, 8.3), (53.5, 6.5),
            (51.8, 4.0), (51.0, 2.0), (50.0, -1.5), (48.5, -5.0), (48.5, -6.5),
            (50.5, -5.5), (53.5, -6.5), (58.0, -5.5), (62.0, -4.0),
        ),
        note="Includes the English Channel.",
    ),
    EcaZone(
        name="Mediterranean Sea Emission Control Area",
        short_name="Mediterranean SECA",
        pollutants=("SOx",),
        sulphur_limit_pct=0.10,
        in_force_since="1 May 2025",
        polygon=(
            (35.95, -5.6), (36.5, -2.0), (38.5, 0.5), (42.5, 3.2), (43.6, 7.5),
            (44.2, 12.3), (45.7, 13.6), (42.0, 18.5), (40.0, 19.2), (38.0, 21.0),
            (39.5, 25.0), (41.0, 28.9), (36.5, 35.8), (34.5, 35.9), (31.3, 34.2),
            (31.2, 32.3), (32.8, 22.0), (30.3, 19.2), (33.5, 11.5), (37.2, 9.8),
            (37.0, 3.0), (35.9, -2.0), (35.95, -5.6),
        ),
        note="Entered force 1 May 2025 under MEPC.361(79).",
    ),
    EcaZone(
        name="North American Emission Control Area",
        short_name="North American ECA",
        pollutants=("SOx", "NOx", "PM"),
        sulphur_limit_pct=0.10,
        in_force_since="2012",
        polygon=(
            (60.0, -140.0), (48.5, -129.0), (32.5, -122.5), (30.0, -118.0),
            (22.9, -110.0), (22.9, -100.0), (25.5, -94.0), (30.0, -88.0),
            (24.0, -81.5), (28.0, -76.5), (35.0, -72.0), (42.0, -64.0),
            (47.0, -55.0), (52.0, -52.0), (56.0, -58.0), (52.0, -66.0),
            (46.0, -63.0), (44.0, -68.0), (40.0, -72.0), (30.0, -80.5),
            (25.0, -80.2), (29.0, -90.0), (26.0, -97.0), (22.0, -106.0),
            (32.0, -117.0), (48.0, -124.5), (58.0, -136.0), (60.0, -140.0),
        ),
        note="Roughly 200 nm off the US and Canadian coasts. No registry lane enters it.",
    ),
    EcaZone(
        name="United States Caribbean Sea Emission Control Area",
        short_name="US Caribbean ECA",
        pollutants=("SOx", "NOx", "PM"),
        sulphur_limit_pct=0.10,
        in_force_since="2014",
        polygon=(
            (21.5, -69.0), (21.5, -63.0), (16.0, -63.0), (16.0, -69.0), (21.5, -69.0),
        ),
        note="Puerto Rico and the US Virgin Islands. No registry lane enters it.",
    ),
]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
EARTH_RADIUS_NM = 3440.065


def haversine_nm(a: Coord, b: Coord) -> float:
    """Great-circle distance between two (lat, lon) points, nautical miles."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(min(1.0, math.sqrt(h)))


def point_in_polygon(point: Coord, polygon: Sequence[Coord]) -> bool:
    """
    Ray casting in (lon, lat) space.

    Equirectangular rather than spherical, which is accurate enough for zones
    this size and keeps the test cheap enough to run along every leg of every
    lane. None of the ECAs cross the antimeridian, so no wrap handling.
    """
    lat, lon = point
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        lat_i, lon_i = polygon[i]
        lat_j, lon_j = polygon[j]
        if (lat_i > lat) != (lat_j > lat):
            x = lon_i + (lat - lat_i) * (lon_j - lon_i) / (lat_j - lat_i)
            if lon < x:
                inside = not inside
        j = i
    return inside


def zone_containing(point: Coord) -> Optional[EcaZone]:
    """The first ECA containing ``point``, or None."""
    for zone in ECA_ZONES:
        if point_in_polygon(point, zone.polygon):
            return zone
    return None


def lane_points(lane: LaneSpec) -> List[Coord]:
    """Origin, sea waypoints, destination — the full polyline for a lane."""
    origin = PORT_POSITIONS.get(lane.origin)
    destination = PORT_POSITIONS.get(lane.destination)
    if origin is None or destination is None:
        return []
    return [origin, *LANE_WAYPOINTS.get(lane.name, []), destination]


def lane_geometry(lane: LaneSpec) -> Dict[str, object]:
    """
    Drawable, measurable geometry for a lane.

    Segment lengths are rescaled so they sum to the registry's published sea
    distance. The drawn polyline is a simplification of the real routing, so
    without this a vessel's screen position and its progress percentage would
    slowly disagree over a long voyage.
    """
    points = lane_points(lane)
    if len(points) < 2:
        return {}

    raw = [haversine_nm(points[i - 1], points[i]) for i in range(1, len(points))]
    drawn = sum(raw)
    scale = (lane.distance_nm / drawn) if drawn > 0 else 1.0

    cumulative = [0.0]
    for nm in raw:
        cumulative.append(cumulative[-1] + nm * scale)

    return {
        "points": [[lat, lon] for lat, lon in points],
        "segment_nm": [round(nm * scale, 2) for nm in raw],
        "cumulative_nm": [round(c, 2) for c in cumulative],
        "drawn_nm": round(drawn, 1),
        "scale_correction": round(scale, 4),
    }


def _densify(a: Coord, b: Coord, step_nm: float = 40.0) -> List[Coord]:
    """Sample points along a leg so a short ECA crossing is not stepped over."""
    length = haversine_nm(a, b)
    n = max(1, int(math.ceil(length / step_nm)))
    return [
        (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n + 1)
    ]


def lane_eca_profile(lane: LaneSpec, step_nm: float = 40.0) -> Dict[str, object]:
    """
    How much of a lane runs inside an emission control area.

    Every leg is sampled at roughly ``step_nm`` intervals and each sample is
    tested against the zone outlines; the fraction of sampled distance inside
    a zone is the answer. This is an estimate from simplified outlines — good
    enough to say "about a fifth of the Rotterdam run is inside a SECA", not
    good enough for a bunker plan.
    """
    points = lane_points(lane)
    if len(points) < 2:
        return {"eca_fraction": 0.0, "eca_nm": 0.0, "zones": []}

    inside_nm = 0.0
    total_nm = 0.0
    zones: Dict[str, float] = {}

    for i in range(1, len(points)):
        for sample in _densify(points[i - 1], points[i], step_nm)[:-1]:
            # Each sample stands for one step of distance along the leg.
            leg_nm = haversine_nm(points[i - 1], points[i])
            n_steps = max(1, int(math.ceil(leg_nm / step_nm)))
            span = leg_nm / n_steps
            total_nm += span
            zone = zone_containing(sample)
            if zone is not None:
                inside_nm += span
                zones[zone.short_name] = zones.get(zone.short_name, 0.0) + span

    if total_nm <= 0:
        return {"eca_fraction": 0.0, "eca_nm": 0.0, "zones": []}

    fraction = inside_nm / total_nm
    # Report against the registry's published distance, not the drawn one.
    scale = lane.distance_nm / total_nm
    return {
        "eca_fraction": round(fraction, 4),
        "eca_nm": round(inside_nm * scale, 1),
        "zones": [
            {"zone": name, "nm": round(nm * scale, 1)}
            for name, nm in sorted(zones.items(), key=lambda kv: -kv[1])
        ],
    }


#: ECA exposure per lane, computed once at import.
LANE_ECA: Dict[str, Dict[str, object]] = {
    lane.name: lane_eca_profile(lane) for lane in LANES
}


def eca_fraction_for(lane_name: str) -> float:
    """Fraction of a named lane that lies inside an ECA, 0-1."""
    profile = LANE_ECA.get(lane_name)
    return float(profile["eca_fraction"]) if profile else 0.0


def sea_routes_summary() -> Dict[str, object]:
    """Everything the API exposes about route geometry and ECAs."""
    return {
        "ports": [
            {"name": name, "lat": lat, "lon": lon} for name, (lat, lon) in PORT_POSITIONS.items()
        ],
        "chokepoints": CHOKEPOINTS,
        "global_sulphur_cap_pct": GLOBAL_SULPHUR_CAP_PCT,
        "eca_zones": [zone.to_dict() for zone in ECA_ZONES],
        "lanes": [
            {
                "name": lane.name,
                **lane_geometry(lane),
                **LANE_ECA[lane.name],
            }
            for lane in LANES
        ],
        "disclaimer": (
            "ECA outlines are indicative simplifications for planning illustration and "
            "map display, not navigational boundaries. The authoritative coordinates are "
            "in MARPOL Annex VI and the relevant IMO resolutions."
        ),
    }
