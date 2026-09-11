"""
Central application configuration.

Every tunable in the platform lives here so that behaviour can be changed with
environment variables instead of code edits. Import ``settings`` anywhere:

    from config import settings
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    """Runtime settings, resolved once at import time."""

    # ---- application ---------------------------------------------------
    APP_NAME: str = "Quantum Green Fleet API"
    VERSION: str = "2.0.0"
    DEBUG: bool = _env_bool("QGF_DEBUG", False)
    LOG_LEVEL: str = os.getenv("QGF_LOG_LEVEL", "INFO").upper()

    # ---- paths ----------------------------------------------------------
    BASE_DIR: Path = BASE_DIR
    PROJECT_ROOT: Path = PROJECT_ROOT
    DATASET_DIR: Path = BASE_DIR / "data" / "datasets"
    MODEL_DIR: Path = BASE_DIR / "prediction" / "saved_models"
    DEFAULT_DATASET: Path = BASE_DIR / "data" / "datasets" / "voyage_data.csv"
    DEFAULT_MODEL_PATH: Path = BASE_DIR / "prediction" / "saved_models" / "xgboost_model.pkl"

    # ---- CORS -----------------------------------------------------------
    # NOTE: the wildcard "*" cannot be combined with credentials, so the
    # allowed origins are listed explicitly. Override with QGF_CORS_ORIGINS.
    CORS_ORIGINS: List[str] = _env_list(
        "QGF_CORS_ORIGINS",
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
    )

    # ---- optimization guard rails ---------------------------------------
    # Requests are validated against these so a single call cannot pin the CPU.
    MAX_VESSELS: int = _env_int("QGF_MAX_VESSELS", 60)
    MAX_ROUTES: int = _env_int("QGF_MAX_ROUTES", 20)
    MAX_ITERATIONS: int = _env_int("QGF_MAX_ITERATIONS", 400)
    MAX_POPULATION: int = _env_int("QGF_MAX_POPULATION", 200)
    MAX_ARCHIVE_SIZE: int = _env_int("QGF_MAX_ARCHIVE_SIZE", 100)
    MAX_BENCHMARK_RUNS: int = _env_int("QGF_MAX_BENCHMARK_RUNS", 10)

    # ---- prediction ------------------------------------------------------
    MAX_PREDICT_BATCH: int = _env_int("QGF_MAX_PREDICT_BATCH", 500)

    @property
    def allowed_dataset_dir(self) -> Path:
        return self.DATASET_DIR


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def configure_logging() -> None:
    """Set up a single, consistent log format for the whole process."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # uvicorn installs its own handlers; keep them but align the level.
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
