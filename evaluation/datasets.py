"""
Evaluation dataset helpers.

Usage (logs all datasets to MLflow as versioned artifacts):
    PYTHONPATH=. python -m evaluation.datasets
"""

from pathlib import Path

import mlflow
import mlflow.data
import pandas as pd

DATASET_DIR = Path("data/eval_datasets")

DATASET_NAMES = ("shutdown", "inspection", "general_query")


def load_dataset(name: str) -> pd.DataFrame:
    """Load a golden eval CSV by short name ('shutdown' | 'inspection' | 'general_query')."""
    path = DATASET_DIR / f"{name}_cases.csv"
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")
    return pd.read_csv(path)


def log_dataset_to_mlflow(df: pd.DataFrame, name: str) -> None:
    """Register a DataFrame as a versioned MLflow dataset artifact in the active run."""
    dataset = mlflow.data.from_pandas(df, name=name, targets="expected_verdict")
    mlflow.log_input(dataset, context="evaluation")


if __name__ == "__main__":
    from evaluation.mlflow_config import setup_experiment

    setup_experiment()
    with mlflow.start_run(run_name="log-eval-datasets"):
        for ds_name in DATASET_NAMES:
            try:
                df = load_dataset(ds_name)
                log_dataset_to_mlflow(df, ds_name)
                print(f"Logged dataset '{ds_name}' — {len(df)} rows")
            except FileNotFoundError as e:
                print(f"Skipped: {e}")
