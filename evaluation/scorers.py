"""
MLflow scorers for the Ops Plan Generator.

Five scorers total:
  Rule-based (deterministic, zero LLM cost):
    feasibility_match_scorer   — exact verdict match vs expected
    valve_count_scorer         — actual valve steps >= expected minimum
    intent_accuracy_scorer     — pipe_id and date extracted correctly

  LLM-as-judge (Together.ai Llama 3.3 70B, already paid for):
    safety_compliance_judge    — safety_warnings adequacy, scored 1–5
    plan_coherence_judge       — logical coherence vs topology + calendar, scored 1–5

Logical Correctness Rubric (primary metric for human review, 1–5):
    5 = Correct verdict + complete ordered valve sequence + all safety warnings present
    4 = Correct verdict + complete sequence, only minor omissions (e.g. timing notes)
    3 = Correct verdict, sequence present but has ordering errors or missing isolation steps
    2 = Correct verdict, sequence has critical errors or safety warnings absent for SHUTDOWN
    1 = Wrong feasibility verdict, or valve IDs do not match the network topology
"""

from mlflow.metrics import MetricValue

try:
    import mlflow.metrics as _mlflow_metrics

    # ── Rule-based scorers ────────────────────────────────────────────────────

    @_mlflow_metrics.make_metric(name="feasibility_match", greater_is_better=True)
    def feasibility_match_scorer(eval_df, _builtin_metrics):
        """1.0 if actual_verdict == expected_verdict, else 0.0."""
        scores = (eval_df["actual_verdict"] == eval_df["targets"]).astype(float)
        return MetricValue(scores=scores.tolist())

    @_mlflow_metrics.make_metric(name="valve_count_adequate", greater_is_better=True)
    def valve_count_scorer(eval_df, _builtin_metrics):
        """1.0 if actual valve count meets the expected minimum, else 0.0."""
        scores = (
            eval_df["actual_valve_count"].fillna(0).astype(int)
            >= eval_df["expected_min_valve_steps"].fillna(0).astype(int)
        ).astype(float)
        return MetricValue(scores=scores.tolist())

    @_mlflow_metrics.make_metric(name="intent_extraction_accuracy", greater_is_better=True)
    def intent_accuracy_scorer(eval_df, _builtin_metrics):
        """0.0 / 0.5 / 1.0 based on correct extraction of pipe_id and target_date."""
        pipe_match = (
            eval_df["actual_pipe_id"].fillna("") == eval_df["pipe_id"].fillna("")
        ).astype(float)
        date_match = (
            eval_df["actual_date"].fillna("") == eval_df["target_date"].fillna("")
        ).astype(float)
        scores = ((pipe_match + date_match) / 2).tolist()
        return MetricValue(scores=scores)

except Exception:
    feasibility_match_scorer = None
    valve_count_scorer = None
    intent_accuracy_scorer = None


# ── LLM-as-judge scorers ──────────────────────────────────────────────────────
# Uses Together.ai's OpenAI-compatible endpoint (already in the stack).
# NOTE: make_genai_metric import path changed between MLflow versions.
# We try the mlflow 3.x path first, then the 2.x path, then provide a
# manual fallback that calls Together.ai directly.

SAFETY_JUDGE_DEFINITION = """
Score whether the safety_warnings field of a water network operations plan
adequately addresses the risks of isolating a pressurised water main in an urban
network. Apply this 1–5 rubric:
  5: All four present — pressure-surge warning, valve-sequence order rationale,
     customer notification timeline, and emergency-bypass reference.
  4: Three of the four present.
  3: Two present, OR mentions "follow SOP" without specifics.
  2: Only one present, OR warnings are vague or generic.
  1: No safety warnings at all, OR the warnings are contradictory or dangerous.
"""

COHERENCE_JUDGE_DEFINITION = """
Score the logical coherence of a water network operations plan against the
topology_summary and calendar_summary context provided. Apply this 1–5 rubric:
  5: Feasibility verdict matches calendar + topology; valve sequence correctly
     isolates the target pipe with no redundant or missing steps; alternative
     supply path is verified and explicitly noted.
  4: Minor issues only — one unnecessary step, or alt path mentioned but not named.
  3: Verdict correct but valve sequence has one ordering error.
  2: Verdict correct but sequence has multiple errors, or alt path ignored.
  1: Verdict is wrong given the context, or valve IDs don't match the network.
"""

safety_compliance_judge = None
plan_coherence_judge = None

try:
    from mlflow.genai import make_genai_metric  # mlflow 3.x

    safety_compliance_judge = make_genai_metric(
        name="safety_compliance",
        definition=SAFETY_JUDGE_DEFINITION,
        grading_context_columns=[],
        examples=[],
        model="openai:/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        parameters={"temperature": 0},
    )

    plan_coherence_judge = make_genai_metric(
        name="plan_coherence",
        definition=COHERENCE_JUDGE_DEFINITION,
        grading_context_columns=["topology_summary", "calendar_summary"],
        examples=[],
        model="openai:/meta-llama/Llama-3.3-70B-Instruct-Turbo",
        parameters={"temperature": 0},
    )

except ImportError:
    try:
        from mlflow.metrics.genai import make_genai_metric  # mlflow 2.x fallback

        safety_compliance_judge = make_genai_metric(
            name="safety_compliance",
            definition=SAFETY_JUDGE_DEFINITION,
            grading_context_columns=[],
            examples=[],
            model="openai:/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            parameters={"temperature": 0},
        )

        plan_coherence_judge = make_genai_metric(
            name="plan_coherence",
            definition=COHERENCE_JUDGE_DEFINITION,
            grading_context_columns=["topology_summary", "calendar_summary"],
            examples=[],
            model="openai:/meta-llama/Llama-3.3-70B-Instruct-Turbo",
            parameters={"temperature": 0},
        )

    except Exception:
        pass  # LLM judges unavailable; run_eval falls back to rule-based only


def get_available_scorers() -> list:
    """Return all scorers that initialised successfully."""
    candidates = [
        feasibility_match_scorer,
        valve_count_scorer,
        intent_accuracy_scorer,
        safety_compliance_judge,
        plan_coherence_judge,
    ]
    return [s for s in candidates if s is not None]
