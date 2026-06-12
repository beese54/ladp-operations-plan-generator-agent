"""
MLflow tracing setup for the Water Network Ops Generator.

Call setup_mlflow_tracing() once at API startup (api/main.py lifespan).

Three autolog integrations run together:
  mlflow.langchain.autolog()   — traces LangGraph node execution (the graph structure)
  mlflow.anthropic.autolog()   — traces raw Anthropic SDK calls (tokens, latency, prompts)
  mlflow.openai.autolog()      — traces Together.ai calls via OpenAI-compat client

This produces a fully nested Trace Graph View in the MLflow UI:
  [AGENT] LangGraph.invoke
    ├─ [AGENT] intent_parser
    │    └─ [LLM] anthropic.messages.create
    ├─ [TOOL]  calendar_check
    ├─ [RETRIEVER] neo4j_topology
    ├─ [RETRIEVER] sop_retrieval
    │    └─ [LLM] openai.chat.completions
    ├─ [RETRIEVER] historical_retrieval
    └─ [AGENT] ops_plan_generator
         └─ [LLM] anthropic.messages.create
"""

import json
import logging
import os
import tempfile

import mlflow
import mlflow.langchain
import mlflow.anthropic
import mlflow.openai

logger = logging.getLogger(__name__)


def setup_mlflow_tracing() -> None:
    """Configure all three autolog integrations. Safe to call multiple times."""
    from evaluation.mlflow_config import MLFLOW_TRACKING_URI, EXPERIMENT_NAME

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(EXPERIMENT_NAME)

    # LangGraph graph structure — each node becomes a nested span
    # log_models/log_input_examples removed: not supported by mlflow.langchain.autolog
    # in mlflow 3.x — model logging is handled explicitly via prompts.py (pickle-free)
    mlflow.langchain.autolog(log_traces=True)

    # Token-level detail for raw Anthropic SDK calls
    mlflow.anthropic.autolog()

    # Token-level detail for Together.ai (OpenAI-compatible client)
    mlflow.openai.autolog()

    logger.info("MLflow tracing enabled — experiment: %s, URI: %s",
                EXPERIMENT_NAME, MLFLOW_TRACKING_URI)


# ── Tool Definition Logging ───────────────────────────────────────────────────
# Tool descriptions are tracked as hyperparameters because they directly
# determine what the model "knows" about the network — a different description
# on get_alternative_path changes feasibility reasoning.

_TOOL_CATALOG: dict[str, str] = {
    "get_pipe_and_valves":           "Fetch PIPE relationship + two endpoint Valves from Neo4j",
    "get_partner_pipe":              "Return reverse-direction pipe pair for bidirectional connection",
    "get_neighborhood_pipes":        "All PIPE relationships directly connected to a Valve (in + out)",
    "get_downstream_pipes":          "BFS traversal from to_valve up to depth hops; returns all PIPE rels",
    "check_alternative_path":        "shortestPath check between two Valves excluding target pipe set",
    "update_valve_status":           "SET v.status = new_status on a Valve node",
    "update_pipe_status":            "SET p.status on all PIPE rels with matching pipe_id",
    "check_pipe_schedule_conflicts": "SQLite: return SchedulingConflict rows overlapping [start, end]",
    "search_sop_documents":          "ChromaDB k-NN: retrieve SOP procedure chunks by semantic query",
    "search_historical_plans":       "ChromaDB k-NN: retrieve historical ops plan chunks by query",
}


def log_tool_definitions() -> None:
    """
    Log all tool descriptions as MLflow run params and a JSON artifact.
    Must be called inside an active mlflow.start_run() context.
    """
    # MLflow param values are limited to 500 chars; truncate for safety
    params = {f"tool.{k}": v[:250] for k, v in _TOOL_CATALOG.items()}
    params["tool.count"] = str(len(_TOOL_CATALOG))
    mlflow.log_params(params)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="tool_definitions_"
    ) as f:
        json.dump(_TOOL_CATALOG, f, indent=2)
        tmp_path = f.name

    try:
        mlflow.log_artifact(tmp_path, artifact_path="tool_definitions")
    finally:
        os.unlink(tmp_path)
