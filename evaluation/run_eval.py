"""
Batch evaluation CLI for the Ops Plan Generator.

Usage:
    PYTHONPATH=. python -m evaluation.run_eval --dataset shutdown
    PYTHONPATH=. python -m evaluation.run_eval --dataset all
    PYTHONPATH=. python -m evaluation.run_eval --dataset shutdown --prompt-version 2

For each row in the golden dataset, the agent is invoked and the output is scored
by all available scorers (rule-based + LLM judges).  Results are written to an
MLflow run with all params, metrics, and the tool-definition artifact logged.

mlflow.genai.evaluate() is tried first (mlflow 3.x); if unavailable, falls back
to mlflow.evaluate() which is available in mlflow 2.x+.
"""

import argparse
import uuid
import logging
from datetime import datetime

import mlflow
import pandas as pd

from evaluation.mlflow_config import setup_experiment, BUDGET_PER_EVAL_RUN_USD
from evaluation.tracing import log_tool_definitions
from evaluation.scorers import get_available_scorers
from evaluation.datasets import load_dataset, log_dataset_to_mlflow
from agents.orchestrator import invoke_graph
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _invoke_and_extract(row: dict) -> dict:
    """Invoke the agent for one eval row and return a flat scoring-ready dict."""
    sid    = f"eval-{uuid.uuid4().hex[:8]}"
    result = invoke_graph(row["query"], session_id=sid)
    plan   = result.get("operations_plan") or {}
    topo   = result.get("topology_context") or {}
    cal    = result.get("calendar_context") or {}
    return {
        "actual_verdict":     plan.get("feasibility_verdict", "ERROR"),
        "actual_valve_count": len(plan.get("valve_sequence") or []),
        "actual_pipe_id":     result.get("pipe_id", ""),
        "actual_date":        result.get("target_date", ""),
        "actual_response":    result.get("final_response", ""),
        "topology_summary":   str(topo)[:500],
        "calendar_summary":   str(cal)[:200],
    }


def run_evaluation(dataset_name: str, prompt_version: int | None = None) -> object:
    """
    Run a full evaluation against a named golden dataset.

    Returns an mlflow.EvaluationResult (or similar) with .metrics populated.
    """
    setup_experiment()
    df        = load_dataset(dataset_name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    s         = get_settings()
    scorers   = get_available_scorers()

    with mlflow.start_run(run_name=f"eval-{dataset_name}-{timestamp}") as run:
        mlflow.log_params({
            "dataset":        dataset_name,
            "prompt_version": str(prompt_version or "current"),
            "model":          s.azure_openai_chat_deployment_name,
            "row_count":      len(df),
            "scorer_count":   len(scorers),
        })
        log_tool_definitions()
        log_dataset_to_mlflow(df, dataset_name)

        logger.info("Running %d eval cases for dataset '%s'…", len(df), dataset_name)
        records = df.to_dict("records")
        outputs = [_invoke_and_extract(r) for r in records]
        results_df = pd.DataFrame([{**r, **o} for r, o in zip(records, outputs)])

        # Try mlflow.genai.evaluate (3.x), fall back to mlflow.evaluate (2.x+)
        eval_result = _run_evaluate(results_df, scorers)

        # Budget guard
        if "estimated_cost_usd" in results_df.columns:
            total_cost = results_df["estimated_cost_usd"].sum()
            if total_cost > BUDGET_PER_EVAL_RUN_USD:
                mlflow.set_tag(
                    "budget_alert",
                    f"${total_cost:.3f} exceeds run budget ${BUDGET_PER_EVAL_RUN_USD}"
                )

        print(f"\n=== Eval: {dataset_name} | Run: {run.info.run_id} ===")
        if hasattr(eval_result, "metrics"):
            for k, v in eval_result.metrics.items():
                print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    return eval_result


def _run_evaluate(results_df: pd.DataFrame, scorers: list) -> object:
    try:
        # mlflow 3.x
        return mlflow.genai.evaluate(
            data=results_df,
            predictions="actual_verdict",
            targets="expected_verdict",
            extra_metrics=scorers,
        )
    except AttributeError:
        pass

    # mlflow 2.x fallback
    return mlflow.evaluate(
        data=results_df,
        model_type=None,
        predictions="actual_verdict",
        targets="expected_verdict",
        extra_metrics=scorers,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch evaluation for the Ops Plan Generator.")
    parser.add_argument(
        "--dataset",
        choices=["shutdown", "inspection", "general_query", "all"],
        default="shutdown",
        help="Which golden dataset to evaluate against (default: shutdown)",
    )
    parser.add_argument(
        "--prompt-version",
        type=int,
        default=None,
        help="Prompt version number to test (default: current hardcoded prompt)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")

    if args.dataset == "all":
        for name in ("shutdown", "inspection", "general_query"):
            run_evaluation(name, args.prompt_version)
    else:
        run_evaluation(args.dataset, args.prompt_version)
