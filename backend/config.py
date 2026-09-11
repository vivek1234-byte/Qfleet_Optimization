"""
Central application configuration.

Every tunable in the platform lives here so that behaviour can be changed with
environment variables instead of code edits. Import ``settings`` anywhere:

    from config import settings
"""
from __future__ import annotations

import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# Generated on first use when QGF_JWT_SECRET is unset. See Settings.jwt_secret_resolved.
_EPHEMERAL_JWT_SECRET: Optional[str] = None


def _load_dotenv() -> None:
    """
    Read PROJECT_ROOT/.env into the environment, if it exists.

    Real values live in .env, which is git-ignored; .env.example documents the
    keys with placeholders. Existing environment variables always win, so a
    value exported by the shell or the container is never overwritten by a
    file left over on someone's laptop.
    """
    path = PROJECT_ROOT / ".env"
    try:
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # An unreadable .env is not worth failing startup over; defaults apply.
        pass


_load_dotenv()


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

    # ---- accounts database ------------------------------------------------
    # SQLite by default: the platform has to start from start.bat on a laptop
    # with no server running and possibly no network. Any SQLAlchemy URL works,
    # so switching to PostgreSQL is one environment variable:
    #   QGF_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/qfleet
    # Credentials live in the environment, never in code or in the frontend.
    DATABASE_URL: str = os.getenv(
        "QGF_DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'data' / 'qfleet.db').as_posix()}",
    )
    DB_ECHO: bool = _env_bool("QGF_DB_ECHO", False)

    # ---- authentication ---------------------------------------------------
    # The signing key MUST be set in production. Left unset, a random key is
    # generated per process, which is safe but logs every user out on restart.
    JWT_SECRET: str = os.getenv("QGF_JWT_SECRET", "")
    JWT_ALGORITHM: str = os.getenv("QGF_JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = _env_int("QGF_JWT_EXPIRE_MINUTES", 720)  # 12 hours
    # bcrypt work factor. 12 is the usual production floor; lower it only for
    # tests, where hashing hundreds of passwords at 12 rounds is the slowest
    # thing in the suite.
    BCRYPT_ROUNDS: int = _env_int("QGF_BCRYPT_ROUNDS", 12)
    PASSWORD_MIN_LENGTH: int = _env_int("QGF_PASSWORD_MIN_LENGTH", 8)

    # ---- brute-force protection ------------------------------------------
    # Counted over a sliding window, per Employee ID and per client address,
    # and only on failures. See auth/ratelimit.py for why both axes exist.
    LOGIN_MAX_ATTEMPTS_PER_ID: int = _env_int("QGF_LOGIN_MAX_ATTEMPTS_PER_ID", 8)
    LOGIN_MAX_ATTEMPTS_PER_IP: int = _env_int("QGF_LOGIN_MAX_ATTEMPTS_PER_IP", 30)
    LOGIN_WINDOW_SECONDS: int = _env_int("QGF_LOGIN_WINDOW_SECONDS", 300)

    # Whether a disabled account is told it is disabled. Saying so is kinder —
    # the person knows to call an administrator instead of retrying — but it
    # confirms the Employee ID exists, so the default is the private one.
    DISCLOSE_INACTIVE: bool = _env_bool("QGF_DISCLOSE_INACTIVE", False)

    # Send HSTS. Off by default because the development server is plain HTTP
    # and an HSTS header on localhost pins the whole origin to HTTPS in the
    # browser, which is a genuinely annoying thing to undo.
    HSTS_ENABLED: bool = _env_bool("QGF_HSTS_ENABLED", False)

    @property
    def allowed_dataset_dir(self) -> Path:
        return self.DATASET_DIR

    @property
    def jwt_secret_resolved(self) -> str:
        """The signing key, falling back to a per-process random one."""
        if self.JWT_SECRET:
            return self.JWT_SECRET
        global _EPHEMERAL_JWT_SECRET
        if _EPHEMERAL_JWT_SECRET is None:
            _EPHEMERAL_JWT_SECRET = secrets.token_urlsafe(48)
            logging.getLogger(__name__).warning(
                "QGF_JWT_SECRET is not set: using a random key for this process. "
                "Sessions will not survive a restart. Set QGF_JWT_SECRET in .env "
                "before deploying."
            )
        return _EPHEMERAL_JWT_SECRET


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
