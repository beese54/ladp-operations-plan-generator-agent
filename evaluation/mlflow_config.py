"""Shared MLflow constants, experiment setup, and cost-budget helpers."""

MLFLOW_TRACKING_URI  = "mlruns"
EXPERIMENT_NAME      = "water-ops-agent"
REVIEW_SESSION_NAME  = "logical-correctness-review"

# USD per 1 000 tokens — update when provider pricing changes
COST_TABLE: dict[str, float] = {
    "claude-sonnet-4-6-input":  0.003,
    "claude-sonnet-4-6-output": 0.015,
    "llama-3.3-70b-input":      0.0009,
    "llama-3.3-70b-output":     0.0009,
}

BUDGET_PER_EVAL_RUN_USD = 5.0
BUDGET_PER_REQUEST_USD  = 0.10


def setup_experiment() -> str:
    """Idempotent experiment creation; returns experiment_id."""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    exp = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if exp is None:
        return mlflow.create_experiment(EXPERIMENT_NAME)
    return exp.experiment_id


def estimate_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    in_cost  = COST_TABLE.get(f"{model_key}-input",  0.0) * input_tokens  / 1000
    out_cost = COST_TABLE.get(f"{model_key}-output", 0.0) * output_tokens / 1000
    return in_cost + out_cost
