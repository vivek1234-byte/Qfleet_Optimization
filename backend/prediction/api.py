"""
Prediction API.

Fixes over the original router:
  * ``/predict`` wrapped its own ``HTTPException`` in ``except Exception`` and
    re-raised it as a 500, so "model not trained" was served as an internal
    server error with the string ``"400: Model is not trained yet."`` as the
    detail. Errors now carry the right status and a structured body.
  * ``/train`` accepted an arbitrary ``dataset_path`` from the request and
    handed it to ``pandas.read_csv`` — a straightforward arbitrary-file read
    (``{"dataset_path": "/etc/passwd"}`` reached the file). Datasets are now
    resolved by name inside a fixed directory.
  * ``/metrics`` returned hard-coded zeros. Real metrics from the last training
    run are cached on the predictor and persisted with the model.
  * Requests had no bounds, so a negative speed or a 900-Beaufort sea state was
    happily fed to the model.
"""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

try:
    from ..config import settings
    from ..core.errors import AppError, ModelNotTrainedError, NotFoundError, ValidationError
    from ..data.fuel_database import fuel_names
    from .models import BASE_FEATURES, SUPPORTED_MODEL_TYPES, FuelPredictor
except ImportError:  # pragma: no cover
    from config import settings
    from core.errors import AppError, ModelNotTrainedError, NotFoundError, ValidationError
    from data.fuel_database import fuel_names
    from prediction.models import BASE_FEATURES, SUPPORTED_MODEL_TYPES, FuelPredictor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prediction", tags=["Prediction"])

VESSEL_TYPES = ["Container", "Bulk Carrier", "Tanker"]

# A single process-wide predictor. Model objects are read-only after training,
# so sharing one is safe; retraining swaps the fitted state atomically enough
# for a single-worker deployment.
predictor = FuelPredictor(model_type="xgboost")


def _load_startup_model() -> None:
    path = settings.DEFAULT_MODEL_PATH
    if not path.exists():
        logger.warning(
            "No saved model at %s — /predict will return 409 until the model is trained "
            "(run `python train_model.py` or POST /api/prediction/train).",
            path,
        )
        return
    try:
        predictor.load_model(path)
        logger.info("loaded pre-trained model from %s", path)
    except Exception as exc:  # a stale or corrupt file must not stop the API
        logger.error("could not load model at %s: %s", path, exc)


_load_startup_model()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class VesselParams(BaseModel):
    """One voyage to predict. Every bound reflects a real physical range."""

    model_config = ConfigDict(extra="forbid")

    vessel_type: str = Field(..., description="Container, Bulk Carrier or Tanker")
    dwt: float = Field(..., gt=0, le=700_000, description="Deadweight tonnage")
    engine_power_kw: float = Field(..., gt=0, le=120_000, description="Installed power, kW")
    speed_knots: float = Field(..., gt=0, le=45, description="Service speed, knots")
    distance_nm: float = Field(..., gt=0, le=25_000, description="Voyage distance, nautical miles")
    cargo_load_pct: float = Field(..., ge=0, le=100, description="Cargo load, percent of capacity")
    weather_beaufort: float = Field(..., ge=0, le=12, description="Sea state, Beaufort 0-12")
    draft_meters: float = Field(..., gt=0, le=30, description="Draft, metres")
    fuel_type: str = Field(..., description=f"One of: {', '.join(fuel_names())}")

    @field_validator("vessel_type")
    @classmethod
    def _known_vessel(cls, v: str) -> str:
        match = next((t for t in VESSEL_TYPES if t.lower() == v.strip().lower()), None)
        if match is None:
            raise ValueError(f"vessel_type must be one of: {', '.join(VESSEL_TYPES)}")
        return match

    @field_validator("fuel_type")
    @classmethod
    def _known_fuel(cls, v: str) -> str:
        match = next((f for f in fuel_names() if f.lower() == v.strip().lower()), None)
        if match is None:
            raise ValueError(f"fuel_type must be one of: {', '.join(fuel_names())}")
        return match

    def to_features(self) -> Dict[str, Any]:
        return {key: getattr(self, key) for key in BASE_FEATURES}


class PredictionResponse(BaseModel):
    predicted_fuel_consumption: float = Field(..., description="Predicted fuel burn, tonnes")
    unit: str = "tons"
    estimated_co2_tons: float
    estimated_cost_usd: float
    confidence_interval: Optional[List[float]] = Field(
        None, description="Approximate 95% interval derived from the model's test RMSE"
    )
    model_type: str
    model_r2: Optional[float] = None


class BatchPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voyages: List[VesselParams] = Field(..., min_length=1)


class BatchPredictionResponse(BaseModel):
    count: int
    predictions: List[float]
    total_fuel_tons: float
    total_co2_tons: float
    unit: str = "tons"


class TrainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(
        "voyage_data.csv",
        description="CSV file name inside the server's dataset directory (not a path)",
    )
    model_type: str = Field("xgboost", description=f"One of: {', '.join(SUPPORTED_MODEL_TYPES)}")
    test_size: float = Field(0.2, ge=0.05, le=0.5)
    persist: bool = Field(True, description="Save the trained model to disk")

    @field_validator("model_type")
    @classmethod
    def _supported(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in SUPPORTED_MODEL_TYPES:
            raise ValueError(f"model_type must be one of: {', '.join(SUPPORTED_MODEL_TYPES)}")
        return v


class MetricsResponse(BaseModel):
    rmse: float
    mae: float
    r2: float
    mape: float
    train_time: float
    n_train: int
    n_test: int
    model_type: str
    trained_at: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_dataset(name: str) -> Path:
    """
    Map a dataset *name* to a file inside the configured dataset directory.

    Anything with a path separator, a drive letter or a parent reference is
    rejected outright, and the resolved path is re-checked against the allowed
    root so a symlink cannot escape it.
    """
    candidate = (name or "").strip()
    if not candidate:
        raise ValidationError("dataset must not be empty")
    if any(sep in candidate for sep in ("/", "\\")) or candidate.startswith("."):
        # Deliberately does not echo the submitted value: reflecting an
        # attacker-controlled path back into the response is a needless
        # information channel.
        raise ValidationError(
            "dataset must be a bare file name inside the server's dataset directory, "
            "not a path"
        )
    if not candidate.lower().endswith(".csv"):
        candidate += ".csv"

    root = settings.DATASET_DIR.resolve()
    path = (root / candidate).resolve()
    if root not in path.parents and path.parent != root:
        raise ValidationError("dataset resolves outside the dataset directory")
    if not path.is_file():
        available = sorted(p.name for p in root.glob("*.csv"))
        raise NotFoundError(
            f"Dataset '{candidate}' not found.",
            details={"available_datasets": available},
        )
    return path


def _require_model() -> FuelPredictor:
    if predictor.model is None or not predictor.is_fitted:
        raise ModelNotTrainedError(
            "No trained model is loaded. Train one with POST /api/prediction/train "
            "or run `python train_model.py` on the server."
        )
    return predictor


def _fuel_economics(fuel_type: str, tons: float) -> Dict[str, float]:
    try:
        from ..data.fuel_database import cost_from_mass, emissions_from_mass
    except ImportError:  # pragma: no cover
        from data.fuel_database import cost_from_mass, emissions_from_mass
    emissions = emissions_from_mass(fuel_type, tons)
    return {
        "co2_tons": round(emissions["co2_tons"], 3),
        "cost_usd": round(cost_from_mass(fuel_type, tons), 2),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.post("/predict", response_model=PredictionResponse)
def predict_fuel(params: VesselParams) -> PredictionResponse:
    """Predict fuel consumption, CO2 and bunker cost for a single voyage."""
    model = _require_model()
    prediction = float(model.predict(params.to_features())[0])

    interval = None
    if model.metrics and model.metrics.rmse > 0:
        margin = 1.96 * model.metrics.rmse
        interval = [round(max(prediction - margin, 0.0), 3), round(prediction + margin, 3)]

    economics = _fuel_economics(params.fuel_type, prediction)
    return PredictionResponse(
        predicted_fuel_consumption=round(prediction, 3),
        estimated_co2_tons=economics["co2_tons"],
        estimated_cost_usd=economics["cost_usd"],
        confidence_interval=interval,
        model_type=model.model_type,
        model_r2=round(model.metrics.r2, 5) if model.metrics else None,
    )


@router.post("/predict/batch", response_model=BatchPredictionResponse)
def predict_batch(request: BatchPredictionRequest) -> BatchPredictionResponse:
    """Predict a whole set of voyages in one call."""
    model = _require_model()
    if len(request.voyages) > settings.MAX_PREDICT_BATCH:
        raise ValidationError(
            f"Batch too large: {len(request.voyages)} voyages "
            f"(maximum {settings.MAX_PREDICT_BATCH})."
        )

    predictions = model.predict([v.to_features() for v in request.voyages])
    total_co2 = sum(
        _fuel_economics(v.fuel_type, float(p))["co2_tons"]
        for v, p in zip(request.voyages, predictions)
    )
    return BatchPredictionResponse(
        count=len(predictions),
        predictions=[round(float(p), 3) for p in predictions],
        total_fuel_tons=round(float(predictions.sum()), 3),
        total_co2_tons=round(float(total_co2), 3),
    )


@router.post("/train", response_model=MetricsResponse, status_code=status.HTTP_200_OK)
def train_model(request: TrainRequest) -> MetricsResponse:
    """Retrain the model on one of the server's datasets."""
    path = _resolve_dataset(request.dataset)
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        raise ValidationError(f"Could not read dataset '{path.name}': {exc}") from exc

    global predictor
    fresh = FuelPredictor(model_type=request.model_type)
    try:
        metrics = fresh.train(df, test_size=request.test_size)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    if request.persist:
        try:
            fresh.save_model(settings.DEFAULT_MODEL_PATH)
        except OSError as exc:  # disk problems must not lose the trained model
            logger.error("trained model could not be saved: %s", exc)

    # Swap in only after training succeeded, so a failed retrain leaves the
    # previously working model serving traffic.
    predictor = fresh
    return MetricsResponse(**metrics)


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics() -> MetricsResponse:
    """Metrics from the run that produced the currently loaded model."""
    model = _require_model()
    if model.metrics is None:
        raise ModelNotTrainedError(
            "The loaded model carries no training metrics. Retrain it to populate them."
        )
    return MetricsResponse(**model.metrics.to_dict())


@router.get("/feature-importance")
def get_feature_importance() -> Dict[str, Any]:
    """Relative contribution of each feature, normalised to sum to 1."""
    model = _require_model()
    try:
        importance = model.feature_importance()
    except RuntimeError as exc:
        raise AppError(str(exc)) from exc
    return {
        "model_type": model.model_type,
        "features": [
            {"feature": name, "importance": round(value, 6)}
            for name, value in importance.items()
        ],
    }


@router.get("/model-info")
def model_info() -> Dict[str, Any]:
    """Everything the UI needs to describe the current model's state."""
    trained = predictor.model is not None and predictor.is_fitted
    return {
        "trained": trained,
        "model_type": predictor.model_type,
        "supported_model_types": list(SUPPORTED_MODEL_TYPES),
        "features": list(predictor.feature_columns),
        "input_fields": list(BASE_FEATURES),
        "vessel_types": VESSEL_TYPES,
        "fuel_types": fuel_names(),
        "metrics": predictor.metrics.to_dict() if (trained and predictor.metrics) else None,
        "model_path": str(settings.DEFAULT_MODEL_PATH),
        "available_datasets": sorted(p.name for p in settings.DATASET_DIR.glob("*.csv")),
    }
