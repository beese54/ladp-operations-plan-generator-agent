"""Tests for evaluation/scorers.py — the eval harness must never silently produce
zero scores again.

The original bug: @make_metric used as a decorator (wrong in MLflow 3.x), caught
by a blanket `except Exception`, so get_available_scorers() returned [] for WEEKS
without anyone noticing. These tests exist to prevent that failure class permanently.
"""
import pandas as pd
import pytest

from evaluation.scorers import (
    _ALL_SCORERS,
    get_available_scorers,
    get_triad_scorers,
    answer_correctness_scorer,
    context_relevance_scorer,
    groundedness_scorer,
    answer_relevance_scorer,
    refusal_accuracy_scorer,
    feasibility_match_scorer,
    scope_fidelity_scorer,
)


class TestScorerInitialization:
    def test_all_scorers_are_not_none(self):
        """The exact failure mode that went undetected for weeks."""
        for s in _ALL_SCORERS:
            assert s is not None, f"Scorer is None — make_metric() likely failed"

    def test_get_available_scorers_returns_expected_count(self):
        """If this number changes, a scorer was added/removed — update the count."""
        assert len(get_available_scorers()) == 9

    def test_get_triad_scorers_returns_four(self):
        assert len(get_triad_scorers()) == 4

    def test_every_scorer_has_a_name(self):
        for s in get_available_scorers():
            assert hasattr(s, "name") and s.name, f"Scorer missing .name attribute"

    def test_no_duplicate_names(self):
        names = [s.name for s in get_available_scorers()]
        assert len(names) == len(set(names)), f"Duplicate scorer names: {names}"


# ── Smoke tests: each scorer runs on a minimal DataFrame without crashing ─────

MINIMAL_DF = pd.DataFrame([{
    "question": "Which valves isolate pipe_084?",
    "actual_response": "Valves valve_034, valve_035, valve_036 and valve_037.",
    "actual_verdict": "FEASIBLE",
    "targets": "FEASIBLE",
    "actual_valve_count": 4,
    "expected_min_valve_steps": 4,
    "actual_pipe_id": "pipe_084",
    "pipe_id": "pipe_084",
    "actual_date": "2026-08-01",
    "target_date": "2026-08-01",
    "banned_phrases": "",
    "ground_truth": "Valves valve_034, valve_035, valve_036 and valve_037 must be closed.",
    "retrieved_chunks": "Close valve_034. Close valve_035. Close valve_036. Close valve_037.",
    "answer_path": "sop_rag",
    "should_answer": "YES",
}])


class TestScorerSmoke:
    @pytest.mark.parametrize("scorer", get_available_scorers(),
                             ids=[s.name for s in get_available_scorers()])
    def test_scorer_runs_without_error(self, scorer):
        """Each scorer must handle the minimal DataFrame without raising."""
        result = scorer.eval_fn(MINIMAL_DF, {})
        assert hasattr(result, "scores")
        assert len(result.scores) == 1
        assert isinstance(result.scores[0], float)


# ── RAG Triad scorer logic ────────────────────────────────────────────────────

class TestAnswerCorrectness:
    def test_perfect_match_scores_high(self):
        df = pd.DataFrame([{
            "actual_response": "Turn anticlockwise to close and clockwise to open.",
            "ground_truth": "Turn anticlockwise to close and clockwise to open.",
        }])
        result = answer_correctness_scorer.eval_fn(df, {})
        assert result.scores[0] > 0.9

    def test_completely_wrong_scores_low(self):
        df = pd.DataFrame([{
            "actual_response": "The capital of France is Paris and the weather is sunny.",
            "ground_truth": "Turn anticlockwise to close and clockwise to open.",
        }])
        result = answer_correctness_scorer.eval_fn(df, {})
        assert result.scores[0] < 0.4

    def test_empty_ground_truth_scores_neutral(self):
        df = pd.DataFrame([{
            "actual_response": "Some answer",
            "ground_truth": "",
        }])
        result = answer_correctness_scorer.eval_fn(df, {})
        assert result.scores[0] == 1.0

    def test_decline_ground_truth_scores_neutral(self):
        df = pd.DataFrame([{
            "actual_response": "I can't help with that.",
            "ground_truth": "DECLINE",
        }])
        result = answer_correctness_scorer.eval_fn(df, {})
        assert result.scores[0] == 1.0


class TestGroundedness:
    def test_answer_from_chunks_scores_high(self):
        df = pd.DataFrame([{
            "actual_response": "Turn anticlockwise to close the valve.",
            "retrieved_chunks": "PUB valves: anticlockwise to close, clockwise to open.",
            "answer_path": "sop_rag",
        }])
        result = groundedness_scorer.eval_fn(df, {})
        assert result.scores[0] >= 0.4

    def test_fabricated_answer_scores_low(self):
        df = pd.DataFrame([{
            "actual_response": "The lockout tagout procedure requires a confined space permit and PPE including a hard hat and steel-toed boots with reflective vest.",
            "retrieved_chunks": "Turn anticlockwise to close. Clockwise to open.",
            "answer_path": "sop_rag",
        }])
        result = groundedness_scorer.eval_fn(df, {})
        assert result.scores[0] < 0.3

    def test_deterministic_path_always_scores_one(self):
        df = pd.DataFrame([{
            "actual_response": "Whatever content doesn't matter",
            "retrieved_chunks": "",
            "answer_path": "system_knowledge",
        }])
        result = groundedness_scorer.eval_fn(df, {})
        assert result.scores[0] == 1.0


class TestContextRelevance:
    def test_relevant_chunks_score_high(self):
        df = pd.DataFrame([{
            "question": "Which direction to turn to close a valve?",
            "retrieved_chunks": "PUB valve direction: anticlockwise to close, clockwise to open. Never close a valve quickly.",
            "answer_path": "sop_rag",
        }])
        result = context_relevance_scorer.eval_fn(df, {})
        assert result.scores[0] > 0.3

    def test_irrelevant_chunks_score_low(self):
        df = pd.DataFrame([{
            "question": "Which direction to turn to close a valve?",
            "retrieved_chunks": "The customer notification policy requires seven days advance notice. Water wagons should be dispatched to affected residents.",
            "answer_path": "sop_rag",
        }])
        result = context_relevance_scorer.eval_fn(df, {})
        assert result.scores[0] < 0.2

    def test_no_chunks_scores_zero(self):
        df = pd.DataFrame([{
            "question": "Some question",
            "retrieved_chunks": "",
            "answer_path": "sop_rag",
        }])
        result = context_relevance_scorer.eval_fn(df, {})
        assert result.scores[0] == 0.0


class TestRefusalAccuracy:
    def test_correct_refusal(self):
        df = pd.DataFrame([{
            "actual_response": "I can't help with that.",
            "should_answer": "NO",
        }])
        result = refusal_accuracy_scorer.eval_fn(df, {})
        assert result.scores[0] == 1.0

    def test_incorrect_answer_to_out_of_scope(self):
        df = pd.DataFrame([{
            "actual_response": "The capital of France is Paris. " * 20,
            "should_answer": "NO",
        }])
        result = refusal_accuracy_scorer.eval_fn(df, {})
        assert result.scores[0] == 0.0

    def test_substantive_answer_to_in_scope(self):
        df = pd.DataFrame([{
            "actual_response": "Turn anticlockwise to close. " * 20,
            "should_answer": "YES",
        }])
        result = refusal_accuracy_scorer.eval_fn(df, {})
        assert result.scores[0] == 1.0
