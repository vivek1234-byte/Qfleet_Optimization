"""
Seasonal weather by sea basin.

The registry carries one annual-mean Beaufort per lane, which is fine for an
average year and useless for the question an Indian operator actually asks:
what does the south-west monsoon do to my Arabian Sea schedule? These
multipliers scale a lane's baseline sea state month by month, weighted by how
much of the lane lies in each basin.

The numbers are indicative climatology — the shape is right (SW monsoon peaks
in the Arabian Sea in July, the North Atlantic is roughest in January, the
South China Sea gets the NE monsoon in winter and typhoons in late summer),
the precise values are not measurements. Do not quote them as observed data.
Replace them with ERA5 or a commercial met feed for anything operational.
"""
from __future__ import annotations

from typing import Dict, Iterable, Sequence, Tuple

MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

#: Multiplier on a lane's annual-mean Beaufort, index 0 = January.
BASIN_MONTHLY_FACTOR: Dict[str, Tuple[float, ...]] = {
    # South-west monsoon, June to September, is the dominant signal.
    "Arabian Sea": (0.85, 0.82, 0.80, 0.85, 1.00, 1.35, 1.45, 1.40, 1.15, 0.90, 0.88, 0.86),
    # Same monsoon, blunted, plus a post-monsoon cyclone season.
    "Bay of Bengal": (0.85, 0.82, 0.85, 0.92, 1.05, 1.25, 1.30, 1.28, 1.15, 1.10, 1.05, 0.90),
    # Sheltered and consistently light.
    "Red Sea": (1.05, 1.00, 0.95, 0.90, 0.85, 0.85, 0.85, 0.88, 0.90, 0.95, 1.00, 1.05),
    # Winter gales; a calm summer.
    "Mediterranean": (1.20, 1.18, 1.10, 0.98, 0.88, 0.82, 0.80, 0.84, 0.94, 1.05, 1.15, 1.22),
    # The roughest water any of these lanes touch.
    "NE Atlantic": (1.35, 1.30, 1.20, 1.02, 0.90, 0.80, 0.78, 0.84, 0.96, 1.12, 1.28, 1.40),
    # NE monsoon in winter, typhoons July to October.
    "South China Sea": (1.30, 1.25, 1.05, 0.90, 0.85, 0.90, 1.00, 1.08, 1.08, 1.12, 1.25, 1.35),
    "East China Sea": (1.25, 1.20, 1.10, 0.95, 0.90, 0.95, 1.05, 1.12, 1.05, 1.05, 1.15, 1.25),
    # Southern-hemisphere summer cyclone season, December to March.
    "South Indian Ocean": (1.18, 1.22, 1.15, 1.00, 0.95, 0.95, 1.00, 1.00, 0.95, 0.92, 1.00, 1.12),
}

#: Used when a lane names a basin this table does not know.
_NEUTRAL = tuple([1.0] * 12)


def basin_factor(basin: str, month: int) -> float:
    """Weather multiplier for one basin in one month (1-12)."""
    table = BASIN_MONTHLY_FACTOR.get(basin, _NEUTRAL)
    return table[(int(month) - 1) % 12]


def seasonal_factor(basins: Sequence[Tuple[str, float]], month: int) -> float:
    """
    Distance-weighted weather multiplier for a lane in a given month.

    A lane that is 30% Arabian Sea and 70% Mediterranean in January gets
    0.3 x 0.85 + 0.7 x 1.20.
    """
    if not basins:
        return 1.0
    total_weight = sum(max(w, 0.0) for _, w in basins)
    if total_weight <= 0:
        return 1.0
    return sum(basin_factor(name, month) * max(w, 0.0) for name, w in basins) / total_weight


def season_label(month: int) -> str:
    """What a mariner in the Indian Ocean would call this month."""
    m = ((int(month) - 1) % 12) + 1
    if m in (6, 7, 8, 9):
        return "South-west monsoon"
    if m in (10, 11):
        return "Post-monsoon / cyclone season"
    if m in (12, 1, 2):
        return "North-east monsoon"
    return "Inter-monsoon (fair weather)"


def monthly_profile(basins: Sequence[Tuple[str, float]]) -> list:
    """The whole year for one lane, for charting."""
    return [
        {
            "month": m,
            "month_name": MONTH_NAMES[m - 1],
            "factor": round(seasonal_factor(basins, m), 4),
            "season": season_label(m),
        }
        for m in range(1, 13)
    ]


def basin_reference() -> Dict[str, object]:
    """Everything the API exposes about seasonality."""
    return {
        "months": list(MONTH_NAMES),
        "basins": [
            {
                "name": name,
                "monthly_factor": list(factors),
                "roughest_month": MONTH_NAMES[max(range(12), key=lambda i: factors[i])],
                "calmest_month": MONTH_NAMES[min(range(12), key=lambda i: factors[i])],
            }
            for name, factors in BASIN_MONTHLY_FACTOR.items()
        ],
        "note": (
            "Indicative climatology, not measured data. The shape is right — the "
            "south-west monsoon peaks in the Arabian Sea in July, the North "
            "Atlantic in January — but replace these with a met feed before using "
            "them operationally."
        ),
    }
