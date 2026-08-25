"""Tests for prompts/system_knowledge.py — deterministic answers about how the
system works.

Two things are being protected here:
  1. The routing gaps found by scripts/probe_chatbot.py are actually closed.
  2. Matching stays CONSERVATIVE — genuine SOP/field questions must still fall
     through to the corpus (return None) rather than being shadowed by a
     canned answer.
"""
import pytest

from prompts.system_knowledge import (
    all_answers,
    all_topic_names,
    answer_system_question,
    match_topic,
)
from tools import scheduling_rules as sr
from tools import valve_operation_rules as vr


# ── The specific probe questions this module was written to fix ───────────────
# IDs refer to data/eval_datasets/rag_probe_questions.csv.

ROUTING_GAP_QUESTIONS = [
    ("P06", "Why can't I schedule an operation the week before Chinese New Year?", "blackout_rule"),
    ("P09", "How do you calculate how long a shutdown will take?", "duration_calc"),
    ("P12", "An emergency burst overlaps two planned operations - what happens to them?", "emergency_behaviour"),
    ("P16", "Can two emergency operations run at the same time on connected pipes?", "emergency_behaviour"),
    ("P20", "What can you help me with?", "capabilities"),
    ("C16", "Who do I contact if I cannot complete a step?", "crew_flagging"),
    ("C17", "How do I mark a step as done?", "crew_marking_steps"),
    ("P17", "How do I give the field crew the valve sequence?", "crew_link"),
    ("P05", "Can I shut down a pipe on a Friday?", "friday_rule"),
]


class TestRoutingGapsClosed:
    @pytest.mark.parametrize("qid,question,expected_topic", ROUTING_GAP_QUESTIONS,
                             ids=[q[0] for q in ROUTING_GAP_QUESTIONS])
    def test_probe_question_now_matches_expected_topic(self, qid, question, expected_topic):
        assert match_topic(question) == expected_topic

    @pytest.mark.parametrize("qid,question,_t", ROUTING_GAP_QUESTIONS,
                             ids=[q[0] for q in ROUTING_GAP_QUESTIONS])
    def test_probe_question_gets_substantive_answer(self, qid, question, _t):
        answer = answer_system_question(question)
        assert answer is not None
        # The baseline failure mode was a ~90 char "not in the procedure" reply.
        assert len(answer) > 180, f"{qid} answer too thin to be useful"


# ── Conservative matching: these must NOT be claimed ──────────────────────────

FALL_THROUGH_QUESTIONS = [
    # Real SOP corpus content
    "What is the procedure when an alternate feed is available?",
    "What happens if there is no alternate feed available?",
    "Can I reopen the valves in any order or does it have to be reverse?",
    # Field mechanics — belong to a valve manual, not to our scheduling engine
    "Which direction do I turn to close the valve?",
    "How many turns to fully close valve_021?",
    "What torque should I apply to a 700mm gate valve?",
    "The valve is stuck and will not turn - what do I do?",
    "The valve spindle is leaking after I operated it - is that normal?",
    "There is an air lock after refilling the main - how do I clear it?",
    "Residents are complaining of dirty water after I reopened the valves - why?",
    # Domain knowledge — belong to a reference document
    "What is a gate valve?",
    "What does mRL mean in pipe pressure?",
    "What causes water hammer?",
    # Topology — needs Neo4j, not canned text
    "Which valves isolate pipe_084?",
    "What road is pipe_033 on?",
    # Genuinely off topic
    "What is the capital of France?",
    "Tell me a joke",
    "What stocks should I invest in?",
]


class TestConservativeMatching:
    @pytest.mark.parametrize("question", FALL_THROUGH_QUESTIONS)
    def test_falls_through_to_corpus(self, question):
        """None means 'not mine' — the SOP path stays the default."""
        assert answer_system_question(question) is None, (
            f"system_knowledge wrongly claimed: {question!r}"
        )

    def test_empty_input_returns_none(self):
        assert answer_system_question("") is None
        assert answer_system_question("   ") is None

    def test_bare_topic_word_is_not_enough(self):
        """A single signal term must not trigger a match on its own."""
        for bare in ("emergency", "valve", "schedule", "step", "holiday", "flag"):
            assert answer_system_question(bare) is None, f"{bare!r} matched alone"


# ── Answers derive from real constants (cannot drift from behaviour) ──────────

class TestAnswersTrackConstants:
    def test_blackout_answer_uses_real_radius(self):
        answer = answer_system_question("why can't I book near a public holiday?")
        assert str(sr.BLACKOUT_RADIUS_DAYS) in answer

    def test_gap_answer_uses_real_gap(self):
        answer = answer_system_question(
            "how many working days gap do I need between scheduled operations?")
        assert str(sr.MIN_WORKING_DAYS_GAP) in answer

    def test_duration_answer_uses_real_per_valve_minutes(self):
        answer = answer_system_question("how do you calculate how long a shutdown will take?")
        assert f"{sr.MINUTES_PER_VALVE:.0f}" in answer

    def test_duration_answer_uses_real_window(self):
        answer = answer_system_question("how do you calculate how long a shutdown will take?")
        assert f"{sr.DAILY_START_HOUR:02d}:00" in answer
        assert f"{int(sr.DAILY_START_HOUR + sr.DAILY_WORK_HOURS):02d}:00" in answer

    def test_duration_answer_uses_real_large_valve_threshold(self):
        answer = answer_system_question("how is operation duration estimated?")
        assert str(vr.LARGE_VALVE_MM) in answer

    def test_all_rules_answer_lists_all_three(self):
        answer = answer_system_question("what scheduling rules apply?")
        assert "R1" in answer and "R2" in answer and "R3" in answer


# ── Guardrail compatibility ──────────────────────────────────────────────────

class TestGuardrailCompatibility:
    def test_no_answer_trips_the_banned_capability_filter(self):
        """These answers reach the user through general_response_node, which runs
        _claims_banned_capability() as a hallucination backstop. Deterministic text
        must never trip it — otherwise a correct answer gets swapped for a refusal.
        """
        from agents.orchestrator import _claims_banned_capability
        for name, answer in all_answers().items():
            assert not _claims_banned_capability(answer), (
                f"topic {name!r} trips the banned-capability filter"
            )

    def test_capabilities_answer_states_real_limits(self):
        answer = answer_system_question("what can you do?")
        low = answer.lower()
        # Must be explicit about the things the system genuinely cannot do,
        # since over-promising here is what Phase 12 was written to stop.
        assert "cannot" in low or "can't" in low
        assert "live" in low or "telemetry" in low

    def test_no_answer_promises_live_telemetry(self):
        for name, answer in all_answers().items():
            low = answer.lower()
            assert "real-time pressure" not in low, f"{name} implies live telemetry"


# ── Registry integrity ───────────────────────────────────────────────────────

class TestRegistry:
    def test_topic_names_unique(self):
        names = all_topic_names()
        assert len(names) == len(set(names))

    def test_every_topic_builds_non_empty_markdown(self):
        for name, answer in all_answers().items():
            assert answer.strip(), f"{name} produced an empty answer"
            assert len(answer) > 100, f"{name} answer suspiciously short"

    def test_match_topic_agrees_with_answer(self):
        """match_topic() and answer_system_question() must never disagree."""
        for question, *_ in [(q,) for _, q, _ in ROUTING_GAP_QUESTIONS]:
            assert (match_topic(question) is None) == (answer_system_question(question) is None)

    def test_punctuation_normalisation(self):
        """Curly apostrophes must match the same as straight ones (Phase 12 bug class)."""
        straight = answer_system_question("why can't I schedule near Chinese New Year?")
        curly = answer_system_question("why can\u2019t I schedule near Chinese New Year?")
        assert straight is not None
        assert straight == curly
