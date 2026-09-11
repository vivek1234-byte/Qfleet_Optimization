"""
Regression tests for the prediction pipeline.

The headline test here is :func:`test_predictions_are_independent_of_batch`,
which pins down the bug that made the original model useless: the scaler was
refit on every call, so a row's prediction changed depending on what else was
sent with it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from prediction.models import BASE_FEATURES, FuelPredictor, OrdinalEncoder


@pytest.fixture(scope="module")
def trained(voyage_df):
    predictor = FuelPredictor("xgboost")
    predictor.train(voyage_df.head(3000), test_size=0.2)
    return predictor


def _features(row):
    return {c: row[c] for c in BASE_FEATURES}


# ---------------------------------------------------------------------------
# The scaler-refit regression
# ---------------------------------------------------------------------------
def test_predictions_are_independent_of_batch(trained, voyage_df):
    """A voyage must predict the same value alone as it does in a batch."""
    rows = voyage_df.head(8)
    batch = trained.predict([_features(r) for _, r in rows.iterrows()])
    singles = np.array([trained.predict(_features(r))[0] for _, r in rows.iterrows()])
    np.testing.assert_allclose(batch, singles, rtol=1e-6)


def test_transform_does_not_mutate_fitted_state(trained, voyage_df):
    """Inference must never refit the scaler or the encoders."""
    before_mean = trained.scaler.mean_.copy()
    before_scale = trained.scaler.scale_.copy()
    before_classes = {k: list(v.classes_) for k, v in trained.encoders.items()}

    trained.predict([_features(r) for _, r in voyage_df.head(50).iterrows()])

    np.testing.assert_array_equal(trained.scaler.mean_, before_mean)
    np.testing.assert_array_equal(trained.scaler.scale_, before_scale)
    assert {k: list(v.classes_) for k, v in trained.encoders.items()} == before_classes


def test_predictions_track_reality(trained, voyage_df):
    """Held-out accuracy must actually hold up on unseen rows."""
    holdout = voyage_df.tail(200)
    preds = trained.predict([_features(r) for _, r in holdout.iterrows()])
    actual = holdout["fuel_consumption_tons"].to_numpy()
    mape = float(np.mean(np.abs((preds - actual) / actual))) * 100.0
    assert mape < 15.0, f"mean absolute percentage error too high: {mape:.1f}%"


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def test_ordinal_encoder_handles_unseen_labels():
    encoder = OrdinalEncoder().fit(["a", "b", "c"])
    assert encoder.transform(["a", "zzz"]).tolist() == [0, encoder.unknown_index]
    # The mapping must stay frozen after an unseen value is seen.
    assert encoder.classes_ == ["a", "b", "c"]


def test_unknown_category_does_not_crash(trained, voyage_df):
    features = _features(voyage_df.iloc[0])
    features["fuel_type"] = "Unobtanium"
    features["vessel_type"] = "Submarine"
    value = trained.predict(features)
    assert value.shape == (1,)
    assert np.isfinite(value[0])


# ---------------------------------------------------------------------------
# Training contract
# ---------------------------------------------------------------------------
def test_predict_before_training_raises():
    with pytest.raises(RuntimeError):
        FuelPredictor("xgboost").predict({"speed_knots": 12})


def test_train_requires_a_target_column(voyage_df):
    without_target = voyage_df.drop(columns=["fuel_consumption_tons"]).head(100)
    with pytest.raises(ValueError, match="target column"):
        FuelPredictor("xgboost").train(without_target)


def test_train_rejects_empty_frame():
    with pytest.raises(ValueError):
        FuelPredictor("xgboost").train(pd.DataFrame())


def test_unknown_model_type_rejected():
    with pytest.raises(ValueError):
        FuelPredictor("random_forest")


def test_metrics_are_cached(trained):
    assert trained.metrics is not None
    assert 0.0 < trained.metrics.r2 <= 1.0
    assert trained.metrics.rmse > 0
    assert trained.metrics.n_train > 0


def test_predictions_are_non_negative(trained, voyage_df):
    tiny = _features(voyage_df.iloc[0])
    tiny.update({"distance_nm": 1.0, "speed_knots": 25.0, "cargo_load_pct": 0.0})
    assert trained.predict(tiny)[0] >= 0.0


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_save_load_roundtrip(trained, voyage_df, tmp_path):
    path = tmp_path / "model.pkl"
    trained.save_model(path)

    reloaded = FuelPredictor("xgboost").load_model(path)
    rows = [_features(r) for _, r in voyage_df.head(5).iterrows()]
    np.testing.assert_allclose(reloaded.predict(rows), trained.predict(rows), rtol=1e-6)
    assert reloaded.metrics.r2 == pytest.approx(trained.metrics.r2, abs=1e-5)


def test_load_rejects_stale_format(trained, tmp_path):
    import joblib

    path = tmp_path / "stale.pkl"
    trained.save_model(path)
    state = joblib.load(path)
    state["format_version"] = 1
    joblib.dump(state, path)

    with pytest.raises(ValueError, match="format version"):
        FuelPredictor("xgboost").load_model(path)


def test_save_untrained_raises(tmp_path):
    with pytest.raises(RuntimeError):
        FuelPredictor("xgboost").save_model(tmp_path / "nope.pkl")


def test_feature_importance_sums_to_one(trained):
    importance = trained.feature_importance()
    assert set(importance) == set(trained.feature_columns)
    assert sum(importance.values()) == pytest.approx(1.0, abs=1e-6)
