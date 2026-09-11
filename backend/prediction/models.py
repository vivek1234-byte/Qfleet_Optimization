"""
Fuel-consumption prediction models.

THE BUG THIS MODULE EXISTED TO FIX
----------------------------------
``preprocess()`` used to call ``self.scaler.fit_transform(X)`` on every
invocation — including at prediction time. Refitting a StandardScaler on the
rows being predicted means each request is standardised against its own mean
and standard deviation, so a single row collapses to all zeros and a batch is
rescaled to whatever happens to be in it. The model then sees features from a
completely different space than the one it was trained on.

The symptom was a model reporting R2 = 0.985 during training while its live
predictions were 60-115% wrong, and the *same* vessel predicting differently
depending on how many other rows were sent with it.

The pipeline is now explicitly split: :meth:`fit_transform` (training only,
learns the statistics) and :meth:`transform` (inference, applies the frozen
statistics). Unseen categories map to a reserved index instead of mutating the
encoder's classes at request time.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

try:  # optional dependency
    import torch
    import torch.nn as nn
    import torch.optim as optim

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    TORCH_AVAILABLE = False

import joblib
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

MODEL_FORMAT_VERSION = 2
TARGET_CANDIDATES = ("fuel_consumption_tons", "fuel_consumption", "target")
SUPPORTED_MODEL_TYPES = ("xgboost", "neural_network")

BASE_FEATURES: List[str] = [
    "vessel_type",
    "dwt",
    "engine_power_kw",
    "speed_knots",
    "distance_nm",
    "cargo_load_pct",
    "weather_beaufort",
    "draft_meters",
    "fuel_type",
]
CATEGORICAL_FEATURES: List[str] = ["vessel_type", "fuel_type"]
#: Physically motivated features derived from the raw inputs. Fuel burn scales
#: with the cube of speed and with time at sea, so handing the model those
#: products directly is worth several points of R2.
DERIVED_FEATURES: List[str] = [
    "voyage_hours",
    "speed_cubed",
    "propulsion_energy_proxy",
    "weather_factor",
    "load_factor",
    "power_to_dwt",
]
FEATURE_COLUMNS: List[str] = BASE_FEATURES + DERIVED_FEATURES


class OrdinalEncoder:
    """
    Minimal, pickle-safe ordinal encoder with an explicit unknown bucket.

    ``sklearn.LabelEncoder`` has no concept of unseen labels; the old code
    worked around that by appending ``'<unknown>'`` to ``classes_`` at predict
    time, mutating fitted state on a live request. This keeps the mapping
    frozen after :meth:`fit` and sends anything unrecognised to a reserved
    index that the model saw during training.
    """

    def __init__(self) -> None:
        self.mapping: Dict[str, int] = {}
        self.unknown_index: int = 0

    def fit(self, values: Sequence[Any]) -> "OrdinalEncoder":
        labels = sorted({str(v) for v in values})
        self.mapping = {label: i for i, label in enumerate(labels)}
        self.unknown_index = len(self.mapping)
        return self

    def transform(self, values: Sequence[Any]) -> np.ndarray:
        return np.array(
            [self.mapping.get(str(v), self.unknown_index) for v in values], dtype=float
        )

    @property
    def classes_(self) -> List[str]:
        return list(self.mapping.keys())


@dataclass
class TrainingMetrics:
    """What a training run produced — cached so ``/metrics`` can serve it."""

    rmse: float
    mae: float
    r2: float
    mape: float
    train_time: float
    n_train: int
    n_test: int
    model_type: str
    trained_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rmse": round(self.rmse, 4),
            "mae": round(self.mae, 4),
            "r2": round(self.r2, 5),
            "mape": round(self.mape, 4),
            "train_time": round(self.train_time, 4),
            "n_train": self.n_train,
            "n_test": self.n_test,
            "model_type": self.model_type,
            "trained_at": self.trained_at,
        }


if TORCH_AVAILABLE:

    class NeuralNet(nn.Module):
        """Small MLP regressor with dropout for the neural-network option."""

        def __init__(self, input_dim: int) -> None:
            super().__init__()
            self.model = nn.Sequential(
                nn.Linear(input_dim, 128),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 1),
            )

        def forward(self, x):  # noqa: D102
            return self.model(x)


class FuelPredictor:
    """Trains and serves fuel-consumption predictions for a single voyage."""

    def __init__(self, model_type: str = "xgboost") -> None:
        model_type = (model_type or "xgboost").strip().lower()
        if model_type not in SUPPORTED_MODEL_TYPES:
            raise ValueError(
                f"Unknown model_type '{model_type}'. Supported: {', '.join(SUPPORTED_MODEL_TYPES)}"
            )
        if model_type == "neural_network" and not TORCH_AVAILABLE:
            raise ImportError(
                "PyTorch is required for the neural_network model. Install it with: pip install torch"
            )

        self.model_type = model_type
        self.base_features = list(BASE_FEATURES)
        self.feature_columns = list(FEATURE_COLUMNS)
        self.categorical_features = list(CATEGORICAL_FEATURES)
        self.scaler: Optional[StandardScaler] = None
        self.encoders: Dict[str, OrdinalEncoder] = {}
        self.model: Optional[Any] = None
        self.metrics: Optional[TrainingMetrics] = None
        self.is_fitted = False

    # ------------------------------------------------------------------
    # Feature engineering
    # ------------------------------------------------------------------
    @staticmethod
    def _add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        speed = pd.to_numeric(df.get("speed_knots"), errors="coerce").clip(lower=0.1)
        distance = pd.to_numeric(df.get("distance_nm"), errors="coerce").clip(lower=0.0)
        power = pd.to_numeric(df.get("engine_power_kw"), errors="coerce").clip(lower=0.0)
        dwt = pd.to_numeric(df.get("dwt"), errors="coerce").clip(lower=1.0)
        beaufort = pd.to_numeric(df.get("weather_beaufort"), errors="coerce").clip(lower=0.0)
        load = pd.to_numeric(df.get("cargo_load_pct"), errors="coerce").clip(lower=0.0, upper=100.0)

        df["voyage_hours"] = distance / speed
        df["speed_cubed"] = speed ** 3
        df["propulsion_energy_proxy"] = power * df["voyage_hours"]
        df["weather_factor"] = 1.0 + 0.02 * np.power(beaufort, 1.5)
        df["load_factor"] = np.power(load / 100.0, 0.7)
        df["power_to_dwt"] = power / dwt
        return df

    def _prepare_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self._add_derived_features(df)
        for col in self.feature_columns:
            if col not in df.columns:
                logger.warning("feature '%s' missing from input; filling with 0", col)
                df[col] = 0.0
        return df

    def _encode(self, df: pd.DataFrame, fit: bool) -> pd.DataFrame:
        df = df.copy()
        for col in self.categorical_features:
            if col not in df.columns:
                df[col] = "unknown"
            if fit:
                self.encoders[col] = OrdinalEncoder().fit(df[col].astype(str))
            encoder = self.encoders.get(col)
            if encoder is None:
                raise RuntimeError(f"encoder for '{col}' is missing; the model is not fitted")
            df[col] = encoder.transform(df[col].astype(str))
        return df

    def fit_transform(self, df: pd.DataFrame) -> np.ndarray:
        """Learn the encoders and scaler, then transform. **Training only.**"""
        prepared = self._encode(self._prepare_frame(df), fit=True)
        X = prepared[self.feature_columns].astype(float).to_numpy()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        self.scaler = StandardScaler().fit(X)
        return self.scaler.transform(X)

    def transform(self, df: pd.DataFrame) -> np.ndarray:
        """Apply the frozen encoders and scaler. **Inference only.**"""
        if self.scaler is None or not self.encoders:
            raise RuntimeError("Predictor is not fitted; call train() or load_model() first")
        prepared = self._encode(self._prepare_frame(df), fit=False)
        X = prepared[self.feature_columns].astype(float).to_numpy()
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        return self.scaler.transform(X)

    def preprocess(self, df: pd.DataFrame, fit: bool = False):
        """
        Backwards-compatible wrapper.

        ``fit`` now has to be requested explicitly — the old signature defaulted
        to fitting, which is precisely what corrupted inference.
        """
        X = self.fit_transform(df) if fit else self.transform(df)
        return X, self._extract_target(df)

    @staticmethod
    def _extract_target(df: pd.DataFrame) -> Optional[np.ndarray]:
        for name in TARGET_CANDIDATES:
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
        return None

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(
        self,
        df: pd.DataFrame,
        test_size: float = 0.2,
        random_state: int = 42,
        epochs: int = 300,
    ) -> Dict[str, Any]:
        if not isinstance(df, pd.DataFrame) or df.empty:
            raise ValueError("Training data must be a non-empty DataFrame")
        if not 0.05 <= test_size <= 0.5:
            raise ValueError("test_size must be between 0.05 and 0.5")

        y = self._extract_target(df)
        if y is None:
            raise ValueError(
                "Training data must contain a target column "
                f"(one of: {', '.join(TARGET_CANDIDATES)})"
            )

        valid = np.isfinite(y)
        if valid.sum() < 20:
            raise ValueError("Need at least 20 rows with a valid target to train")
        df = df.loc[valid].reset_index(drop=True)
        y = y[valid]

        started = time.perf_counter()

        # Split FIRST, then fit the transforms on the training split only, so
        # test-set statistics never leak into the scaler.
        train_df, test_df, y_train, y_test = train_test_split(
            df, y, test_size=test_size, random_state=random_state
        )
        X_train = self.fit_transform(train_df)
        X_test = self.transform(test_df)

        if self.model_type == "xgboost":
            self.model = xgb.XGBRegressor(
                n_estimators=400,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.9,
                colsample_bytree=0.9,
                min_child_weight=2,
                reg_lambda=1.0,
                objective="reg:squarederror",
                n_jobs=-1,
                random_state=random_state,
            )
            self.model.fit(X_train, y_train, eval_set=[(X_test, y_test)], verbose=False)
            preds = self.model.predict(X_test)
        else:
            preds = self._train_neural_network(X_train, y_train, X_test, epochs, random_state)

        train_time = time.perf_counter() - started
        self.is_fitted = True
        self.metrics = self._score(y_test, preds, train_time, len(X_train), len(X_test))
        self.metrics.model_type = self.model_type
        logger.info(
            "trained %s: R2=%.4f RMSE=%.3f MAE=%.3f in %.2fs",
            self.model_type,
            self.metrics.r2,
            self.metrics.rmse,
            self.metrics.mae,
            train_time,
        )
        return self.metrics.to_dict()

    def _train_neural_network(self, X_train, y_train, X_test, epochs, random_state):  # pragma: no cover
        torch.manual_seed(random_state)
        self.model = NeuralNet(input_dim=X_train.shape[1])
        criterion = nn.MSELoss()
        optimizer = optim.Adam(self.model.parameters(), lr=1e-3, weight_decay=1e-5)

        # Standardise the target too; raw tonnages in the thousands make the
        # loss surface badly conditioned.
        self._y_mean = float(np.mean(y_train))
        self._y_std = float(np.std(y_train)) or 1.0
        X_t = torch.tensor(X_train, dtype=torch.float32)
        y_t = torch.tensor((y_train - self._y_mean) / self._y_std, dtype=torch.float32).view(-1, 1)

        dataset = torch.utils.data.TensorDataset(X_t, y_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=256, shuffle=True)

        self.model.train()
        for _ in range(epochs):
            for xb, yb in loader:
                optimizer.zero_grad()
                loss = criterion(self.model(xb), yb)
                loss.backward()
                optimizer.step()

        self.model.eval()
        with torch.no_grad():
            scaled = self.model(torch.tensor(X_test, dtype=torch.float32)).numpy().ravel()
        return scaled * self._y_std + self._y_mean

    @staticmethod
    def _score(y_true, y_pred, train_time, n_train, n_test) -> TrainingMetrics:
        y_true = np.asarray(y_true, dtype=float)
        y_pred = np.asarray(y_pred, dtype=float)
        nonzero = np.abs(y_true) > 1e-9
        mape = (
            float(np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100.0)
            if nonzero.any()
            else 0.0
        )
        return TrainingMetrics(
            rmse=float(np.sqrt(mean_squared_error(y_true, y_pred))),
            mae=float(mean_absolute_error(y_true, y_pred)),
            r2=float(r2_score(y_true, y_pred)),
            mape=mape,
            train_time=float(train_time),
            n_train=int(n_train),
            n_test=int(n_test),
            model_type="",
        )

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def predict(self, inputs: Union[Dict[str, Any], List[Dict[str, Any]], pd.DataFrame]) -> np.ndarray:
        """Predict fuel consumption in tonnes for one or many voyages."""
        if self.model is None or not self.is_fitted:
            raise RuntimeError("Model is not trained. Train it or load a saved model first.")

        if isinstance(inputs, pd.DataFrame):
            df = inputs.copy()
        else:
            records = [inputs] if isinstance(inputs, dict) else list(inputs)
            if not records:
                return np.empty(0)
            df = pd.DataFrame(records)

        X = self.transform(df)

        if self.model_type == "xgboost":
            preds = self.model.predict(X)
        elif self.model_type == "neural_network":  # pragma: no cover
            self.model.eval()
            with torch.no_grad():
                scaled = self.model(torch.tensor(X, dtype=torch.float32)).numpy().ravel()
            preds = scaled * getattr(self, "_y_std", 1.0) + getattr(self, "_y_mean", 0.0)
        else:  # pragma: no cover - constructor rejects anything else
            raise RuntimeError(f"Cannot predict with model_type '{self.model_type}'")

        # Fuel burn cannot be negative; a tree ensemble can extrapolate below 0.
        return np.maximum(np.asarray(preds, dtype=float), 0.0)

    def feature_importance(self) -> Dict[str, float]:
        """Feature importances, normalised to sum to 1. XGBoost only."""
        if self.model is None or not self.is_fitted:
            raise RuntimeError("Model is not trained.")
        if self.model_type != "xgboost":
            raise RuntimeError("Feature importance is only available for the XGBoost model.")
        importances = np.asarray(self.model.feature_importances_, dtype=float)
        if len(importances) != len(self.feature_columns):  # pragma: no cover - defensive
            raise RuntimeError(
                f"Model expects {len(importances)} features but {len(self.feature_columns)} are configured; "
                "the saved model is stale — retrain it."
            )
        total = importances.sum()
        if total > 0:
            importances = importances / total
        return {
            name: float(value)
            for name, value in sorted(
                zip(self.feature_columns, importances), key=lambda kv: -kv[1]
            )
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_model(self, path: Union[str, Path]) -> Path:
        if self.model is None or not self.is_fitted:
            raise RuntimeError("Nothing to save: the model is not trained.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state: Dict[str, Any] = {
            "format_version": MODEL_FORMAT_VERSION,
            "model_type": self.model_type,
            "scaler": self.scaler,
            "encoders": self.encoders,
            "feature_columns": self.feature_columns,
            "base_features": self.base_features,
            "categorical_features": self.categorical_features,
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }
        if self.model_type == "xgboost":
            state["model"] = self.model
        else:  # pragma: no cover
            state["model_state_dict"] = self.model.state_dict()
            state["y_mean"] = getattr(self, "_y_mean", 0.0)
            state["y_std"] = getattr(self, "_y_std", 1.0)

        joblib.dump(state, path)
        logger.info("saved %s model to %s", self.model_type, path)
        return path

    def load_model(self, path: Union[str, Path]) -> "FuelPredictor":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No saved model at {path}")

        state = joblib.load(path)
        version = state.get("format_version", 1)
        if version != MODEL_FORMAT_VERSION:
            raise ValueError(
                f"Saved model at {path} uses format version {version}, but this build expects "
                f"{MODEL_FORMAT_VERSION}. Retrain the model (python train_model.py)."
            )

        self.model_type = state["model_type"]
        self.scaler = state["scaler"]
        self.encoders = state["encoders"]
        self.feature_columns = state["feature_columns"]
        self.base_features = state.get("base_features", list(BASE_FEATURES))
        self.categorical_features = state.get("categorical_features", list(CATEGORICAL_FEATURES))

        if self.model_type == "xgboost":
            self.model = state["model"]
        else:  # pragma: no cover
            if not TORCH_AVAILABLE:
                raise ImportError("PyTorch is required to load a neural_network model.")
            self.model = NeuralNet(input_dim=len(self.feature_columns))
            self.model.load_state_dict(state["model_state_dict"])
            self.model.eval()
            self._y_mean = state.get("y_mean", 0.0)
            self._y_std = state.get("y_std", 1.0)

        saved_metrics = state.get("metrics")
        if saved_metrics:
            self.metrics = TrainingMetrics(
                rmse=saved_metrics.get("rmse", 0.0),
                mae=saved_metrics.get("mae", 0.0),
                r2=saved_metrics.get("r2", 0.0),
                mape=saved_metrics.get("mape", 0.0),
                train_time=saved_metrics.get("train_time", 0.0),
                n_train=saved_metrics.get("n_train", 0),
                n_test=saved_metrics.get("n_test", 0),
                model_type=saved_metrics.get("model_type", self.model_type),
                trained_at=saved_metrics.get("trained_at", 0.0),
            )
        self.is_fitted = True
        logger.info("loaded %s model from %s", self.model_type, path)
        return self
