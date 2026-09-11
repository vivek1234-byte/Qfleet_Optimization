"""
Synthetic voyage dataset generator.

Changes from the original:
  * seedable, so a dataset can be reproduced exactly
  * fuel properties come from the shared fuel database instead of a private
    if/elif ladder of SFC values
  * the output path is resolved absolutely rather than relative to the caller's
    working directory
  * added ``sea_days``, ``main_engine_load_pct`` and route name columns, which
    make the dataset useful for more than one model
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    from .fuel_database import FuelType, get_all_fuels
except ImportError:  # pragma: no cover
    from fuel_database import FuelType, get_all_fuels

logger = logging.getLogger(__name__)

BASE_SFC_G_PER_KWH = 180.0


@dataclass(frozen=True)
class VesselSpec:
    vessel_type: str
    dwt_min: float
    dwt_max: float
    engine_kw_min: float
    engine_kw_max: float
    min_speed_knots: float = 10.0
    max_speed_knots: float = 24.0


VESSEL_SPECS: List[VesselSpec] = [
    VesselSpec("Container", 50_000, 150_000, 20_000, 60_000, 14.0, 24.0),
    VesselSpec("Bulk Carrier", 30_000, 100_000, 8_000, 25_000, 11.0, 16.0),
    VesselSpec("Tanker", 80_000, 200_000, 15_000, 45_000, 12.0, 17.5),
]

ROUTES: List[Dict[str, Any]] = [
    {"name": "Asia-Europe", "distance_nm": 11_000},
    {"name": "Trans-Pacific", "distance_nm": 7_000},
    {"name": "Trans-Atlantic", "distance_nm": 3_500},
    {"name": "Intra-Asia", "distance_nm": 1_500},
    {"name": "Middle East-Asia", "distance_nm": 5_000},
]

BEAUFORT_LEVELS = np.array([1, 2, 3, 4, 5, 6, 7, 8])
BEAUFORT_WEIGHTS = np.array([0.05, 0.10, 0.25, 0.30, 0.20, 0.05, 0.03, 0.02])


def generate_dataset(n_records: int = 10_000, seed: Optional[int] = 42) -> pd.DataFrame:
    """
    Generate ``n_records`` synthetic voyages.

    Vectorised: 10,000 rows take milliseconds instead of a Python loop with
    three ``random`` calls per row.
    """
    if n_records < 1:
        raise ValueError("n_records must be at least 1")
    rng = np.random.default_rng(seed)

    spec_idx = rng.integers(0, len(VESSEL_SPECS), n_records)
    route_idx = rng.integers(0, len(ROUTES), n_records)
    fuels: List[FuelType] = get_all_fuels()
    fuel_idx = rng.integers(0, len(fuels), n_records)

    dwt_min = np.array([VESSEL_SPECS[i].dwt_min for i in spec_idx])
    dwt_max = np.array([VESSEL_SPECS[i].dwt_max for i in spec_idx])
    kw_min = np.array([VESSEL_SPECS[i].engine_kw_min for i in spec_idx])
    kw_max = np.array([VESSEL_SPECS[i].engine_kw_max for i in spec_idx])
    v_min = np.array([VESSEL_SPECS[i].min_speed_knots for i in spec_idx])
    v_max = np.array([VESSEL_SPECS[i].max_speed_knots for i in spec_idx])

    dwt = rng.uniform(dwt_min, dwt_max)
    engine_power_kw = rng.uniform(kw_min, kw_max)
    speed_knots = rng.uniform(v_min, v_max)

    route_distance = np.array([ROUTES[i]["distance_nm"] for i in route_idx], dtype=float)
    distance_nm = route_distance * rng.uniform(0.95, 1.05, n_records)

    cargo_load_pct = rng.uniform(30.0, 100.0, n_records)
    weather_beaufort = rng.choice(BEAUFORT_LEVELS, size=n_records, p=BEAUFORT_WEIGHTS)
    draft_meters = (10.0 + (cargo_load_pct / 100.0) * 5.0) * rng.uniform(0.95, 1.05, n_records)

    sfc_mult = np.array([fuels[i].sfc_multiplier for i in fuel_idx])
    energy_density = np.array([fuels[i].energy_density_mj_per_kg for i in fuel_idx])
    emission_factor = np.array([fuels[i].emission_factor_gco2_per_mj for i in fuel_idx])
    sox_factor = np.array([fuels[i].sox_factor for i in fuel_idx])
    nox_factor = np.array([fuels[i].nox_factor for i in fuel_idx])
    cost_per_gj = np.array([fuels[i].cost_per_gj for i in fuel_idx])

    sfc = BASE_SFC_G_PER_KWH * sfc_mult * rng.uniform(0.95, 1.05, n_records)

    hours = distance_nm / speed_knots
    # Engine load falls with the cube of the speed ratio against the class max.
    load_ratio = np.clip((speed_knots / v_max) ** 3, 0.15, 1.0)
    power_kw = engine_power_kw * load_ratio

    weather_factor = 1.0 + 0.02 * np.power(weather_beaufort, 1.5)
    load_factor = np.power(cargo_load_pct / 100.0, 0.7)

    fuel_tons = (power_kw * sfc * hours / 1e6) * weather_factor * load_factor
    fuel_tons *= rng.uniform(0.95, 1.05, n_records)

    energy_mj = fuel_tons * 1000.0 * energy_density
    co2_tons = energy_mj * emission_factor / 1e6
    sox_tons = energy_mj * sox_factor / 1e6
    nox_tons = energy_mj * nox_factor / 1e6
    cost_usd = (energy_mj / 1000.0) * cost_per_gj

    return pd.DataFrame(
        {
            "vessel_type": [VESSEL_SPECS[i].vessel_type for i in spec_idx],
            "route_name": [ROUTES[i]["name"] for i in route_idx],
            "dwt": dwt.round(2),
            "engine_power_kw": engine_power_kw.round(2),
            "speed_knots": speed_knots.round(2),
            "distance_nm": distance_nm.round(2),
            "cargo_load_pct": cargo_load_pct.round(2),
            "weather_beaufort": weather_beaufort,
            "draft_meters": draft_meters.round(2),
            "fuel_type": [fuels[i].name for i in fuel_idx],
            "sea_days": (hours / 24.0).round(3),
            "main_engine_load_pct": (load_ratio * 100.0).round(2),
            "fuel_consumption_tons": fuel_tons.round(3),
            "co2_emissions_tons": co2_tons.round(3),
            "sox_emissions_tons": sox_tons.round(4),
            "nox_emissions_tons": nox_tons.round(4),
            "operational_cost_usd": cost_usd.round(2),
        }
    )


def save_dataset(df: pd.DataFrame, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("saved %d records to %s", len(df), path)
    return path


def default_path() -> Path:
    return Path(__file__).resolve().parent / "datasets" / "voyage_data.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic voyage dataset")
    parser.add_argument("-n", "--records", type=int, default=10_000)
    parser.add_argument("-s", "--seed", type=int, default=42)
    parser.add_argument("-o", "--output", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    df = generate_dataset(args.records, seed=args.seed)
    out = save_dataset(df, args.output or default_path())
    print(f"Wrote {len(df)} records to {out}")


if __name__ == "__main__":
    main()
