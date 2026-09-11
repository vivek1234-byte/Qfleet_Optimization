"""
Quantum Green Fleet — FastAPI application entry point.

Fixes over the original:
  * ``allow_origins=["*"]`` was combined with ``allow_credentials=True``. That
    combination is invalid under the CORS spec and browsers reject the
    response, so credentialed requests failed with an opaque CORS error.
    Origins are now listed explicitly and configurable.
  * A catch-all ``@app.exception_handler(Exception)`` returned
    ``str(exc)`` to the client, leaking internal paths and stack details, and
    it swallowed deliberate ``HTTPException``s raised inside routers.
  * ``@app.on_event("startup")`` is deprecated; replaced with a lifespan
    context manager that also warms the model and reports readiness.
  * Added request logging with timing, a request id, and a ``/api/health``
    payload that actually reflects subsystem state.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

# Allow `uvicorn main:app` from inside backend/ as well as
# `uvicorn backend.main:app` from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import configure_logging, settings
from core.errors import AppError

configure_logging()
logger = logging.getLogger("qgf.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("starting %s v%s", settings.APP_NAME, settings.VERSION)
    # Read the paths from the OpenAPI schema rather than walking ``app.routes``:
    # FastAPI >= 0.13x wraps included routers in an internal container object
    # with no ``.path``, so iterating app.routes lists only the root endpoints.
    try:
        paths = sorted(app.openapi().get("paths", {}))
    except Exception:  # pragma: no cover - schema generation is best-effort here
        paths = []
    logger.info("registered %d routes", len(paths))
    for path in paths:
        logger.debug("  %s", path)

    if not settings.DEFAULT_MODEL_PATH.exists():
        logger.warning(
            "prediction model missing at %s — run `python train_model.py` to enable /api/prediction/predict",
            settings.DEFAULT_MODEL_PATH,
        )
    if not settings.DEFAULT_DATASET.exists():
        logger.warning(
            "dataset missing at %s — run `python -m data.generator` to create it",
            settings.DEFAULT_DATASET,
        )

    # Accounts. A missing or empty employees table is not fatal — the rest of
    # the API still works — but nobody can sign in, so say so loudly rather
    # than letting the first person discover it at the login screen.
    try:
        from db import Employee
        from db.session import get_sessionmaker
        from sqlalchemy import func, select

        with get_sessionmaker()() as session:
            total = session.scalar(select(func.count()).select_from(Employee)) or 0
            admins = (
                session.scalar(
                    select(func.count())
                    .select_from(Employee)
                    .where(Employee.role == "ADMIN", Employee.is_active.is_(True))
                )
                or 0
            )
        if total == 0:
            logger.warning(
                "no employee accounts exist — run `python -m backend.manage seed` "
                "(demo data) or `python -m backend.manage bootstrap` (first admin)"
            )
        elif admins == 0:
            logger.warning(
                "no active administrator — run `python -m backend.manage bootstrap` "
                "to create one, or employee management is unreachable"
            )
        else:
            logger.info("accounts ready: %d employees, %d active administrators", total, admins)
    except Exception as exc:  # pragma: no cover - startup diagnostics only
        logger.warning(
            "accounts database unavailable (%s: %s) — sign-in will fail until "
            "`alembic upgrade head` has been run",
            type(exc).__name__,
            exc,
        )

    yield
    logger.info("shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Backend API for the Quantum-Inspired Green Fleet Management platform: "
        "fuel-consumption prediction, multi-objective fleet optimization, "
        "algorithm benchmarking and fuel-transition scenario analysis."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)
# Optimization responses carry full Pareto fronts and per-vessel plans; they
# compress extremely well.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed = time.perf_counter() - started
        logger.exception(
            "[%s] %s %s failed after %.3fs", request_id, request.method, request.url.path, elapsed
        )
        raise
    elapsed = time.perf_counter() - started
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{elapsed:.4f}"
    if request.url.path.startswith("/api"):
        logger.info(
            "[%s] %s %s -> %d in %.3fs",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )
    return response


# ---------------------------------------------------------------------------
# Error handlers — one consistent envelope for every failure
# ---------------------------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.info("%s %s -> %s: %s", request.method, request.url.path, exc.code, exc.message)
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": f"HTTP_{exc.status_code}", "message": detail}},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Turn pydantic's error list into something a UI can render inline."""
    fields = [
        {
            # Model-level validators report an empty location; label those
            # "body" so the client always has something to attach the error to.
            "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body") or "body",
            "message": err.get("msg", "invalid value"),
            "type": err.get("type", "value_error"),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields are invalid.",
                "details": {"fields": fields},
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Last resort. The message is generic unless debug mode is on — the previous
    handler returned ``str(exc)`` to any caller, which exposed file paths and
    library internals.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    payload: Dict[str, Any] = {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An internal error occurred. Check the server logs for details.",
        }
    }
    if settings.DEBUG:
        payload["error"]["details"] = {"exception": f"{type(exc).__name__}: {exc}"}
    return JSONResponse(status_code=500, content=payload)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
from admin.api import router as admin_router  # noqa: E402
from auth.api import router as auth_router  # noqa: E402
from benchmarking.api import router as benchmarking_router  # noqa: E402
from optimization.api import router as optimization_router  # noqa: E402
from prediction.api import router as prediction_router  # noqa: E402
from regulatory.api import router as regulatory_router  # noqa: E402
from scenario.api import router as scenario_router  # noqa: E402

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(optimization_router)
app.include_router(benchmarking_router)
app.include_router(prediction_router)
app.include_router(scenario_router)
app.include_router(regulatory_router)


# ---------------------------------------------------------------------------
# Root endpoints
# ---------------------------------------------------------------------------
@app.get("/", tags=["Meta"])
async def root() -> Dict[str, Any]:
    return {
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "health": "/api/health",
            "auth": "/api/auth",
            "admin": "/api/admin",
            "optimization": "/api/optimization",
            "benchmarks": "/api/benchmarks",
            "prediction": "/api/prediction",
            "scenarios": "/api/scenarios",
        },
    }


@app.get("/api/health", tags=["Meta"])
async def health_check() -> Dict[str, Any]:
    """Readiness detail, so the UI can tell the user exactly what is missing."""
    from prediction.api import predictor  # imported lazily to avoid a cycle

    model_ready = predictor.model is not None and predictor.is_fitted
    dataset_ready = settings.DEFAULT_DATASET.exists()

    # Accounts. Reported without ever including the database URL, which can
    # carry a password.
    accounts_ok = False
    accounts_detail = "not initialised"
    try:
        from db import Employee
        from db.session import get_sessionmaker
        from sqlalchemy import func, select

        with get_sessionmaker()() as session:
            admins = (
                session.scalar(
                    select(func.count())
                    .select_from(Employee)
                    .where(Employee.role == "ADMIN", Employee.is_active.is_(True))
                )
                or 0
            )
        accounts_ok = admins > 0
        accounts_detail = (
            f"{admins} active administrator{'s' if admins != 1 else ''}"
            if accounts_ok
            else "no active administrator; run python -m backend.manage bootstrap"
        )
    except Exception as exc:  # pragma: no cover - health reporting only
        accounts_detail = f"{type(exc).__name__}; run alembic upgrade head"

    return {
        "status": "healthy" if model_ready and dataset_ready and accounts_ok else "degraded",
        "version": settings.VERSION,
        "checks": {
            "api": {"ok": True},
            "accounts": {"ok": accounts_ok, "detail": accounts_detail},
            "prediction_model": {
                "ok": model_ready,
                "detail": (
                    f"{predictor.model_type} model loaded"
                    if model_ready
                    else "no trained model; run train_model.py or POST /api/prediction/train"
                ),
            },
            "dataset": {
                "ok": dataset_ready,
                "detail": (
                    str(settings.DEFAULT_DATASET.name)
                    if dataset_ready
                    else "voyage_data.csv missing; run python -m data.generator"
                ),
            },
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("QGF_HOST", "127.0.0.1"),
        port=int(os.getenv("QGF_PORT", "8000")),
        reload=settings.DEBUG,
    )
