#!/usr/bin/env python3
"""
Train the fuel-consumption model and save it for the API to load.

Runs from anywhere — the original used the relative path
``backend/data/datasets/voyage_data.csv``, so it only worked when invoked from
the project root, and it silently trained on nothing if the dataset was
missing.

Usage
-----
    python train_model.py                       # xgboost on the default dataset
    python train_model.py --model neural_network
    python train_model.py --dataset my_voyages.csv --test-size 0.25
    python train_model.py --generate 20000      # regenerate the dataset first
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import pandas as pd  # noqa: E402

from config import configure_logging, settings  # noqa: E402
from prediction.models import SUPPORTED_MODEL_TYPES, FuelPredictor  # noqa: E402

logger = logging.getLogger("train")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", default="voyage_data.csv", help="CSV file inside backend/data/datasets/")
    parser.add_argument("--model", default="xgboost", choices=list(SUPPORTED_MODEL_TYPES))
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--output", default=None, help="Where to save the model")
    parser.add_argument(
        "--generate",
        type=int,
        metavar="N",
        default=None,
        help="Regenerate the dataset with N synthetic voyages before training",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    dataset_path = settings.DATASET_DIR / args.dataset

    if args.generate:
        from data.generator import generate_dataset, save_dataset

        logger.info("generating %d synthetic voyage records", args.generate)
        save_dataset(generate_dataset(args.generate), dataset_path)

    if not dataset_path.exists():
        logger.error(
            "Dataset not found: %s\nGenerate one with:  python train_model.py --generate 10000",
            dataset_path,
        )
        return 1

    logger.info("loading %s", dataset_path)
    df = pd.read_csv(dataset_path)
    logger.info("loaded %d rows x %d columns", len(df), len(df.columns))

    predictor = FuelPredictor(model_type=args.model)
    metrics = predictor.train(df, test_size=args.test_size)

    print("\nTraining metrics")
    print("-" * 46)
    for key, value in metrics.items():
        if key == "trained_at":
            continue
        print(f"  {key:<14} {value}")

    output = Path(args.output) if args.output else settings.DEFAULT_MODEL_PATH
    predictor.save_model(output)
    print(f"\nSaved model to {output}")

    # Sanity check: a model whose held-out R2 looks fine can still be broken at
    # inference time (that was the original bug), so predict a real row back.
    sample = df.iloc[0]
    features = {c: sample[c] for c in predictor.base_features if c in df.columns}
    predicted = float(predictor.predict(features)[0])
    actual = float(sample.get("fuel_consumption_tons", float("nan")))
    print(f"Spot check — actual {actual:.2f} t, predicted {predicted:.2f} t "
          f"({abs(predicted - actual) / actual * 100:.1f}% error)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
