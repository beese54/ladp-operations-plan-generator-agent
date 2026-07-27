"""Regression test for intent_parser_node dropping an in-progress operation
when re-parsing a clarification answer.

Bug report: user asked to shut down pipe_084, gave a date, said "planned",
then answered the end-date question with "plan for me" (missing "it" from
the suggested "plan it for me") — the assistant replied with the off-topic
decline instead of continuing. Root cause: every other slot (pipe_id,
target_date, operation_class, end_date_mode) falls back to the prior state
value so a clarification round-trip can't drop it, but operation_type did
not — so a single ambiguous/UNKNOWN reclassification of the merged,
fragment-heavy user_query_raw ("shut pipe 84. 9 septmeber. planned. plan for
me") silently discarded the already-established SHUTDOWN and routed to
off_topic_node.
"""
import json
from unittest.mock import MagicMock

from agents import orchestrator as orch


def _fake_client(content: str):
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    client.chat.completions.create.return_value = response
    return client


def _mid_clarification_state(**overrides):
    base = {
        "user_query_raw": "shut pipe 84. 9 septmeber. planned. plan for me",
        "messages": [],
        "pipe_id": "pipe_084",
        "target_date": "2026-09-09",
        "operation_class": "PLANNED",
        "operation_type": "SHUTDOWN",
        "end_date_mode": None,
        "awaiting_clarification": "end_date",  # clarification_node just asked this
        "clarification_round": 3,
    }
    base.update(overrides)
    return base


def test_unknown_reclassification_mid_clarification_preserves_operation_type(monkeypatch):
    # The classifier comes back UNKNOWN for the merged fragment string (the
    # actual failure mode reported) but still extracts end_date_mode fine.
    monkeypatch.setattr(orch, "get_azure_openai_client", lambda: _fake_client(
        json.dumps({
            "operation_type": "UNKNOWN",
            "pipe_id": None,
            "target_date": None,
            "target_end_date": None,
            "end_date_mode": "AUTO",
            "operation_class": None,
            "confidence": 0.2,
        })
    ))

    out = orch.intent_parser_node(_mid_clarification_state())

    assert out["operation_type"] == "SHUTDOWN"
    assert out["pipe_id"] == "pipe_084"
    assert out["target_date"] == "2026-09-09"
    assert out["operation_class"] == "PLANNED"
    assert out["end_date_mode"] == "AUTO"
    # The whole point: this must NOT route to the off-topic decline.
    assert orch.route_after_intent(out) != "off_topic"


def test_unknown_classification_on_a_fresh_message_still_goes_off_topic(monkeypatch):
    # Guard against over-correcting: a genuinely fresh, non-clarification
    # message that's actually off-topic must still be declined normally.
    monkeypatch.setattr(orch, "get_azure_openai_client", lambda: _fake_client(
        json.dumps({
            "operation_type": "UNKNOWN",
            "pipe_id": None,
            "target_date": None,
            "target_end_date": None,
            "end_date_mode": None,
            "operation_class": None,
            "confidence": 0.9,
        })
    ))

    out = orch.intent_parser_node({
        "user_query_raw": "what's the capital of France?",
        "messages": [],
        "awaiting_clarification": "",
        "clarification_round": 0,
    })

    assert out["operation_type"] == "UNKNOWN"
    assert orch.route_after_intent(out) == "off_topic"


def test_unknown_reclassification_without_prior_operation_stays_unknown(monkeypatch):
    # If there's no established operation in state to fall back to, UNKNOWN
    # must pass through as-is rather than fabricating one.
    monkeypatch.setattr(orch, "get_azure_openai_client", lambda: _fake_client(
        json.dumps({
            "operation_type": "UNKNOWN",
            "pipe_id": None,
            "target_date": None,
            "target_end_date": None,
            "end_date_mode": None,
            "operation_class": None,
            "confidence": 0.3,
        })
    ))

    out = orch.intent_parser_node(_mid_clarification_state(operation_type=None))

    assert out["operation_type"] == "UNKNOWN"


def test_genuine_schedule_query_tangent_mid_clarification_still_switches(monkeypatch):
    # The fix must only guard the UNKNOWN failure mode — a real topic switch
    # (e.g. a schedule-listing question) mid-clarification should still work.
    monkeypatch.setattr(orch, "get_azure_openai_client", lambda: _fake_client(
        json.dumps({
            "operation_type": "SCHEDULE_QUERY",
            "pipe_id": None,
            "target_date": "2026-11-01",
            "target_end_date": None,
            "end_date_mode": None,
            "operation_class": None,
            "confidence": 0.85,
        })
    ))

    out = orch.intent_parser_node(_mid_clarification_state(
        user_query_raw="shut pipe 84. 9 septmeber. planned. what's scheduled in November?",
    ))

    assert out["operation_type"] == "SCHEDULE_QUERY"
