"""
Prompt registry and pickle-free model logging.

Prompt registry:
    Registers the production system prompts to MLflow so versions are tracked.
    Prompt v1 is the current hardcoded string; v2+ come from iterating on evals.

    python -m evaluation.prompts          # register v1 for all prompts
    python -m evaluation.prompts --log-model   # also log the pyfunc model artifact

Pickle-free model:
    OpsGeneratorPyfuncModel wraps invoke_graph() as an mlflow.pyfunc.PythonModel.
    All serialisation state lives in a JSON config artifact — no pickle file.
    Safe to load in any Python environment and inspect without security risk.

Prompt optimisation workflow:
    1. PYTHONPATH=. python -m evaluation.run_eval --dataset all       (baseline, v1)
    2. Edit the system prompt in agents/ops_plan_generator.py
    3. PYTHONPATH=. python -m evaluation.prompts                      (register v2)
    4. PYTHONPATH=. python -m evaluation.run_eval --dataset all --prompt-version 2
    5. Compare runs in MLflow UI Parallel Coordinates chart
"""

import argparse
import json
import logging
import os
import tempfile

import mlflow
import mlflow.pyfunc
import pandas as pd

from evaluation.mlflow_config import setup_experiment
from config.settings import get_settings

logger = logging.getLogger(__name__)


# ── Prompt Registry ───────────────────────────────────────────────────────────

def register_all_prompts() -> None:
    """Register current production prompts as v1 in the MLflow prompt registry."""
    from agents.ops_plan_generator import _SYSTEM_PROMPT
    from agents.orchestrator import _INTENT_SYSTEM, _GENERAL_SYSTEM
    from prompts.sop_walkthrough_prompt import SOP_WALKTHROUGH_SYSTEM_PROMPT

    s = get_settings()
    prompts = {
        "ops-plan-system-prompt":           _SYSTEM_PROMPT,
        "intent-parser-system-prompt":      _INTENT_SYSTEM,
        "general-response-system-prompt":   _GENERAL_SYSTEM,
        "sop-walkthrough-system-prompt":    SOP_WALKTHROUGH_SYSTEM_PROMPT,
    }

    for name, template in prompts.items():
        try:
            mlflow.register_prompt(
                name=name,
                template=template,
                commit_message="v1 — initial production prompt",
                tags={"model": s.azure_openai_chat_deployment_name},
            )
            logger.info("Registered prompt: %s", name)
        except Exception as e:
            logger.warning("Could not register prompt '%s': %s", name, e)


def load_prompt(name: str, version: int | None = None) -> str:
    """Load a registered prompt by name and optional version (default: latest)."""
    alias = f"prompts:/{name}/{version}" if version else f"prompts:/{name}/latest"
    return mlflow.load_prompt(alias).template


# ── Pickle-free Pyfunc Model ──────────────────────────────────────────────────

class OpsGeneratorPyfuncModel(mlflow.pyfunc.PythonModel):
    """
    MLflow pyfunc wrapper for the full LangGraph agent.

    Serialisation is JSON-only (no pickle):
      load_context() reads agent_config.json from the logged artifact path
      predict()       calls invoke_graph() and returns final_response strings

    Input DataFrame columns:  query  (required), session_id (optional)
    Output DataFrame columns: response
    """

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        with open(context.artifacts["agent_config"]) as f:
            self.config = json.load(f)

    def predict(self, context, model_input: pd.DataFrame) -> pd.DataFrame:
        from agents.orchestrator import invoke_graph
        import uuid as _uuid

        results = []
        for _, row in model_input.iterrows():
            sid = row.get("session_id") or f"mlflow-{_uuid.uuid4().hex[:8]}"
            out = invoke_graph(str(row["query"]), session_id=sid)
            results.append(out.get("final_response", ""))
        return pd.DataFrame({"response": results})


def log_model() -> str:
    """
    Log the OpsGeneratorPyfuncModel to MLflow and return the artifact URI.
    Must be called inside an active mlflow.start_run() context.
    """
    s = get_settings()
    config = {
        "version":            "1.0",
        "azure_openai_model": s.azure_openai_chat_deployment_name,
        "together_model":     s.together_model,
        "neo4j_uri":          s.neo4j_uri,
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f, indent=2)
        tmp = f.name

    try:
        model_info = mlflow.pyfunc.log_model(
            artifact_path="ops_generator",
            python_model=OpsGeneratorPyfuncModel(),
            artifacts={"agent_config": tmp},
            pip_requirements=[
                "mlflow>=3.11.0",
                "langgraph>=1.1.6",
                "neo4j>=5.28.1",
                "chromadb>=1.5.6",
                "pandas>=2.0.0",
                "openai>=1.30.0",
                "pydantic>=2.7.0",
                "pydantic-settings>=2.3.0",
            ],
        )
        return model_info.model_uri
    finally:
        os.unlink(tmp)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register prompts and optionally log pyfunc model.")
    parser.add_argument("--log-model", action="store_true",
                        help="Also log the pickle-free pyfunc model artifact")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
    setup_experiment()

    with mlflow.start_run(run_name="register-prompts"):
        register_all_prompts()

        if args.log_model:
            uri = log_model()
            print(f"Model logged to: {uri}")
        else:
            print("Prompts registered. Run with --log-model to also log the pyfunc artifact.")
