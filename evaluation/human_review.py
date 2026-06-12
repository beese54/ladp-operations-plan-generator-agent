"""
Human Review Session for Logical Correctness evaluation.

Full workflow:
    1. Collect traces (OrchestratorState dicts) from recent production requests
       or from a batch eval run.
    2. Run detect_logical_issues() — fast rule-based pre-scan that flags
       HALLUCINATED_VALVE, MISSING_VALVE_SEQUENCE, VERDICT_CALENDAR_MISMATCH,
       MISSING_SAFETY_WARNINGS, NO_ALT_PATH_NOTED, LOW_STEP_COUNT.
    3. Call create_review_session() — logs a CSV issue-report artifact, then
       opens an MLflow Review/Annotation session with the Logical Correctness
       1–5 rubric and thumbs-up/down controls.  Returns the reviewer URL.
    4. Senior engineer opens the URL, scores each trace, adds free-text comments.
    5. Call promote_to_golden_dataset() — pulls thumbs_up + score ≥ 4 traces
       into data/eval_datasets/golden_verified.csv as authoritative ground truth.

Quick-start (two traces):
    python -m evaluation.human_review --recent 2
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import tempfile
from dataclasses import dataclass

import mlflow
import mlflow.tracking

from evaluation.mlflow_config import REVIEW_SESSION_NAME, setup_experiment

logger = logging.getLogger(__name__)

# All confirmed valve IDs in Bukit Batok network (valve_001–valve_057)
KNOWN_VALVE_IDS: frozenset[str] = frozenset(
    f"valve_{str(i).zfill(3)}" for i in range(1, 58)
)

LOGICAL_CORRECTNESS_RUBRIC = """\
Rate the logical correctness of this water network operations plan on a 1–5 scale:
  5 = Correct verdict + complete ordered valve sequence + all safety warnings present
  4 = Correct verdict + complete sequence, only minor omissions (e.g. missing timing note)
  3 = Correct verdict, sequence present but has ordering errors or missing isolation steps
  2 = Correct verdict but critical sequence errors, or safety warnings absent for SHUTDOWN
  1 = Wrong feasibility verdict, or valve IDs do not match the real network topology
"""


# ── Issue Detection ────────────────────────────────────────────────────────────

@dataclass
class DetectedIssue:
    severity: str    # "ERROR" | "WARNING" | "INFO"
    code: str        # e.g. "HALLUCINATED_VALVE"
    detail: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "detail": self.detail}


def detect_logical_issues(trace: dict) -> list[DetectedIssue]:
    """
    Pre-scan a single OrchestratorState trace for logical problems.

    Designed to run before human review so the senior engineer immediately
    sees which plans have already been flagged for specific issues.

    Returns a list of DetectedIssue sorted by severity (ERROR first).
    """
    issues: list[DetectedIssue] = []
    plan    = trace.get("operations_plan") or {}
    cal     = trace.get("calendar_context") or {}
    op_type = trace.get("operation_type", "")
    verdict = plan.get("feasibility_verdict", "")
    seq     = plan.get("valve_sequence") or []

    # ── ERROR checks ────────────────────────────────────────────────────────
    planned_valves = {s.get("valve_id", "") for s in seq}
    bad_valves = planned_valves - KNOWN_VALVE_IDS - {""}
    if bad_valves:
        issues.append(DetectedIssue(
            "ERROR", "HALLUCINATED_VALVE",
            f"valve_ids not in Bukit Batok network: {sorted(bad_valves)}",
        ))

    if verdict == "FEASIBLE" and not seq:
        issues.append(DetectedIssue(
            "ERROR", "MISSING_VALVE_SEQUENCE",
            "Verdict is FEASIBLE but valve_sequence is empty",
        ))

    if verdict == "FEASIBLE" and cal.get("blocking_conflict"):
        issues.append(DetectedIssue(
            "ERROR", "VERDICT_CALENDAR_MISMATCH",
            f"Calendar blocking conflict present but verdict is FEASIBLE: "
            f"{cal['blocking_conflict']}",
        ))

    # ── WARNING checks ───────────────────────────────────────────────────────
    if op_type == "SHUTDOWN" and not plan.get("safety_warnings"):
        issues.append(DetectedIssue(
            "WARNING", "MISSING_SAFETY_WARNINGS",
            "SHUTDOWN operation has no safety_warnings field",
        ))

    if verdict == "FEASIBLE" and plan.get("alternative_recommendation") is None:
        issues.append(DetectedIssue(
            "WARNING", "NO_ALT_PATH_NOTED",
            "Feasible plan does not document an alternative supply path",
        ))

    # ── INFO checks ──────────────────────────────────────────────────────────
    if verdict == "FEASIBLE" and 0 < len(seq) < 2:
        issues.append(DetectedIssue(
            "INFO", "LOW_STEP_COUNT",
            f"Only {len(seq)} valve step(s) for a FEASIBLE operation",
        ))

    return issues


# ── Review Session Creation ────────────────────────────────────────────────────

def create_review_session(
    traces: list[dict],
    session_name: str = REVIEW_SESSION_NAME,
    assigned_to: str | None = None,
) -> str:
    """
    Pre-scan traces for issues, log an issue-report artifact, then open an
    MLflow annotation/review session for the senior engineer.

    Must be called inside an active mlflow.start_run() context.

    Returns the URL the reviewer should open.
    """
    # Step 1 — enrich every trace with detected issues
    enriched: list[dict] = []
    for t in traces:
        issues = detect_logical_issues(t)
        enriched.append({
            **t,
            "_detected_issues": [i.to_dict() for i in issues],
            "_issue_count":     len(issues),
            "_error_count":     sum(1 for i in issues if i.severity == "ERROR"),
        })

    # Step 2 — log issue summary as a CSV artifact
    _log_issue_summary(enriched)

    # Step 3 — create the labeling session (tries mlflow.genai, falls back to REST)
    return _open_labeling_session(enriched, session_name, assigned_to)


def _log_issue_summary(enriched: list[dict]) -> None:
    import pandas as pd

    rows = [
        {
            "session_id":  t.get("session_id", ""),
            "pipe_id":     t.get("pipe_id", ""),
            "target_date": t.get("target_date", ""),
            "op_type":     t.get("operation_type", ""),
            "verdict":     (t.get("operations_plan") or {}).get("feasibility_verdict", ""),
            "error_count": t["_error_count"],
            "issues":      json.dumps(t["_detected_issues"]),
        }
        for t in enriched
    ]
    df = pd.DataFrame(rows)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        df.to_csv(f, index=False)
        tmp = f.name
    try:
        mlflow.log_artifact(tmp, artifact_path="human_review")
    finally:
        os.unlink(tmp)

    mlflow.log_metric("review_traces_total",  len(enriched))
    mlflow.log_metric("review_traces_errors", int(df["error_count"].gt(0).sum()))
    logger.info("Issue summary logged. %d traces, %d with errors.",
                len(enriched), int(df["error_count"].gt(0).sum()))


def _open_labeling_session(
    enriched: list[dict],
    session_name: str,
    assigned_to: str | None,
) -> str:
    """Try the mlflow.genai Python API; fall back to the REST endpoint."""
    try:
        return _create_via_sdk(enriched, session_name, assigned_to)
    except (ImportError, AttributeError) as e:
        logger.warning("mlflow.genai SDK path unavailable (%s); using REST fallback.", e)
        return _create_via_rest(enriched, session_name)


def _create_via_sdk(
    enriched: list[dict],
    session_name: str,
    assigned_to: str | None,
) -> str:
    import mlflow.genai as mlflow_genai

    label_schemas = [
        mlflow_genai.LabelSchema(
            name="logical_correctness",
            type="number",
            min_value=1,
            max_value=5,
            description=LOGICAL_CORRECTNESS_RUBRIC,
        ),
        mlflow_genai.LabelSchema(
            name="verdict_correct",
            type="enum",
            values=["thumbs_up", "thumbs_down"],
            description="Is the feasibility verdict correct given the network topology and calendar?",
        ),
        mlflow_genai.LabelSchema(
            name="engineer_comments",
            type="text",
            description="Technical notes on valve sequence, safety gaps, or hallucinated elements",
        ),
    ]

    session = mlflow_genai.create_labeling_session(
        name=session_name,
        assigned_users=[assigned_to] if assigned_to else [],
        label_schemas=label_schemas,
        description=(
            "Review AI-generated water-infrastructure operations plans for logical "
            "correctness. Pre-detected issues are shown in each trace's metadata. "
            "Focus on: (1) valve sequence order, (2) safety warnings adequacy, "
            "(3) feasibility verdict vs network topology and calendar."
        ),
    )

    for t in enriched:
        session.add_trace(t)

    url = session.url
    mlflow.set_tag("review_session_url",  url)
    mlflow.set_tag("review_session_name", session_name)
    return url


def _create_via_rest(enriched: list[dict], session_name: str) -> str:
    """
    Direct REST call to MLflow server.
    POST /api/2.0/mlflow/genai/annotation-sessions
    Works on any MLflow 3.x server regardless of Python SDK version.
    """
    import requests
    from evaluation.mlflow_config import MLFLOW_TRACKING_URI

    base_url = (
        MLFLOW_TRACKING_URI
        if MLFLOW_TRACKING_URI.startswith("http")
        else "http://localhost:5000"
    )

    payload = {
        "name": session_name,
        "label_schemas": [
            {"name": "logical_correctness", "type": "number", "min": 1, "max": 5},
            {"name": "verdict_correct",     "type": "enum",
             "values": ["thumbs_up", "thumbs_down"]},
            {"name": "engineer_comments",   "type": "text"},
        ],
        "traces": [
            {
                "trace_id": t.get("session_id", ""),
                "input":    t.get("user_query_raw", ""),
                "output":   t.get("final_response", ""),
                "metadata": {
                    "pipe_id":         t.get("pipe_id", ""),
                    "detected_issues": t.get("_detected_issues", []),
                    "error_count":     t.get("_error_count", 0),
                },
            }
            for t in enriched
        ],
    }

    resp = requests.post(
        f"{base_url}/api/2.0/mlflow/genai/annotation-sessions",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    url  = f"{base_url}/annotation-sessions/{data['session_id']}"
    mlflow.set_tag("review_session_url",  url)
    mlflow.set_tag("review_session_name", session_name)
    return url


# ── Golden Dataset Promotion ───────────────────────────────────────────────────

def promote_to_golden_dataset(
    session_id: str,
    min_score: int = 4,
    output_csv: str = "data/eval_datasets/golden_verified.csv",
) -> None:
    """
    Pull thumbs_up + logical_correctness >= min_score annotations from a completed
    review session and append them to the Golden Dataset CSV.

    Human-verified plans become the authoritative ground truth for future evals.
    """
    import pandas as pd

    annotations = _fetch_annotations(session_id)

    promoted = [
        {
            "session_id":          a["trace_id"],
            "pipe_id":             a.get("metadata", {}).get("pipe_id", ""),
            "query":               a.get("input", ""),
            "final_response":      a.get("output", ""),
            "logical_correctness": a["labels"].get("logical_correctness"),
            "verdict_correct":     a["labels"].get("verdict_correct"),
            "engineer_comments":   a["labels"].get("engineer_comments", ""),
            "promoted_at":         pd.Timestamp.now().isoformat(),
        }
        for a in annotations
        if (
            a["labels"].get("verdict_correct") == "thumbs_up"
            and (a["labels"].get("logical_correctness") or 0) >= min_score
        )
    ]

    if not promoted:
        print("No traces met the promotion threshold (thumbs_up + score ≥ %d)." % min_score)
        return

    new_df = pd.DataFrame(promoted)
    try:
        existing = pd.read_csv(output_csv)
        combined = (
            pd.concat([existing, new_df], ignore_index=True)
            .drop_duplicates("session_id")
        )
    except FileNotFoundError:
        combined = new_df

    combined.to_csv(output_csv, index=False)
    print(f"Promoted {len(promoted)} verified plans → {output_csv}")

    with mlflow.start_run(run_name="golden-dataset-update"):
        import mlflow.data
        dataset = mlflow.data.from_pandas(
            combined, name="golden_verified", targets="verdict_correct"
        )
        mlflow.log_input(dataset, context="golden_dataset")
        mlflow.log_metric("golden_dataset_size", len(combined))


def _fetch_annotations(session_id: str) -> list[dict]:
    """Fetch annotation results from a completed review session."""
    client = mlflow.tracking.MlflowClient()
    try:
        return client.get_annotation_session_results(session_id)
    except Exception:
        pass

    # REST fallback
    import requests
    from evaluation.mlflow_config import MLFLOW_TRACKING_URI
    base_url = (
        MLFLOW_TRACKING_URI
        if MLFLOW_TRACKING_URI.startswith("http")
        else "http://localhost:5000"
    )
    resp = requests.get(
        f"{base_url}/api/2.0/mlflow/genai/annotation-sessions/{session_id}/results",
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("annotations", [])


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create an MLflow human review session.")
    parser.add_argument("--recent",   type=int, default=5,
                        help="Number of recent production traces to collect (default: 5)")
    parser.add_argument("--run-id",   type=str, default=None,
                        help="Collect traces from a specific MLflow eval run-id")
    parser.add_argument("--assign-to", type=str, default=None,
                        help="Email address of the reviewer to assign the session to")
    args = parser.parse_args()

    from agents.orchestrator import invoke_graph

    setup_experiment()

    # Collect traces by running a small representative set
    sample_queries = [
        "Can I shut down pipe_003 on 2026-06-20 from 08:00 to 16:00?",
        "Inspect pipe_009 on 2026-06-30 from 09:00 to 13:00",
        "Can I shut down pipe_033 on 2026-08-01 from 06:00 to 20:00?",
        "What are the SOP steps for valve isolation?",
        "Can I shut down pipe_005 on 2026-09-15 from 09:00 to 17:00?",
    ]
    queries = sample_queries[: args.recent]
    traces = [
        invoke_graph(q, session_id=f"review-{i}")
        for i, q in enumerate(queries)
    ]

    with mlflow.start_run(run_name="human-review-session"):
        url = create_review_session(traces, assigned_to=args.assign_to)

    print(f"\nReview session ready. Share this URL with the senior engineer:\n  {url}")
