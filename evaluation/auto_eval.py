"""
Automatic per-request evaluation.

AutoEvaluator.log_request() is called as a FastAPI BackgroundTask after every
/chat request so that production metrics accumulate in MLflow without adding
any latency to the API response.

Metrics logged per request:
  latency_ms, intent_confidence, feasibility_verdict_num (FEASIBLE=1/CONDITIONAL=0.5/NOT_FEASIBLE=0),
  valve_step_count, safety_warning_count, clarification_rounds, estimated_cost_usd

Tags logged per request:
  operation_type, pipe_id, target_date, session_id, budget_alert (if over limit)

The run is opened as nested=True so it appears under the parent chat run in the
MLflow UI rather than as a separate top-level entry.
"""

import logging
import mlflow

from evaluation.mlflow_config import estimate_cost, BUDGET_PER_REQUEST_USD

logger = logging.getLogger(__name__)

_VERDICT_NUMERIC = {
    "FEASIBLE":     1.0,
    "CONDITIONAL":  0.5,
    "NOT_FEASIBLE": 0.0,
}


class AutoEvaluator:
    """Stateless helper; instantiate once per API process."""

    def log_request(
        self,
        session_id: str,
        query: str,
        result: dict,
        latency_ms: float,
    ) -> None:
        """
        Log per-request metrics and cost estimate to MLflow.
        Designed to run in a FastAPI BackgroundTask.
        """
        plan    = result.get("operations_plan") or {}
        verdict = plan.get("feasibility_verdict", "UNKNOWN")

        try:
            with mlflow.start_run(run_name=f"live-{session_id[:8]}", nested=True):
                mlflow.log_metrics({
                    "latency_ms":              latency_ms,
                    "intent_confidence":       result.get("intent_confidence", 0.0),
                    "feasibility_verdict_num": _VERDICT_NUMERIC.get(verdict, -1.0),
                    "valve_step_count":        len(plan.get("valve_sequence") or []),
                    "safety_warning_count":    len(plan.get("safety_warnings") or []),
                    "clarification_rounds":    result.get("clarification_round", 0),
                })
                mlflow.set_tags({
                    "operation_type": result.get("operation_type", ""),
                    "pipe_id":        result.get("pipe_id", "") or "",
                    "target_date":    result.get("target_date", "") or "",
                    "session_id":     session_id,
                })

                # Cost estimate from token counts captured by anthropic.autolog
                usage = result.get("_usage") or {}
                cost  = estimate_cost(
                    "claude-sonnet-4-6",
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                )
                mlflow.log_metric("estimated_cost_usd", cost)

                if cost > BUDGET_PER_REQUEST_USD:
                    mlflow.set_tag(
                        "budget_alert",
                        f"${cost:.4f} exceeds per-request budget ${BUDGET_PER_REQUEST_USD}",
                    )

        except Exception as e:
            # Non-fatal: eval logging must never break the API response
            logger.warning("AutoEvaluator.log_request failed: %s", e)
