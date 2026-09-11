"""Fuel reference data and the synthetic voyage dataset generator."""
from .fuel_database import FUEL_DATABASE, FuelType, get_all_fuels, get_fuel, require_fuel  # noqa: F401

__all__ = ["FUEL_DATABASE", "FuelType", "get_fuel", "require_fuel", "get_all_fuels"]
