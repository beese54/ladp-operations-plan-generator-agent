"""Tests for the booking gate helpers (Phase 4, S4.1-S4.3).

The interrupt itself is exercised live; here we unit-test the pure decision and
commit logic with the DB writes monkeypatched.
"""
from datetime import datetime, timedelta

import pytest

from agents import orchestrator as orch


def _state(op_class="PLANNED", feasible=True, suggested=None, proposals=None, blocking=False):
    return {
        "pipe_id": "pipe_084",
        "operation_type": "SHUTDOWN",
        "operation_class": op_class,
        "scheduled_start": "2026-07-06T10:00:00",
        "scheduled_end": "2026-07-06T14:00:00",
        "sop_chain": {"shutdown_valves": ["v1", "v2", "v3"]},
        "schedule_proposals": proposals or [],
        "final_response": "PLAN TEXT",
        "calendar_context": {
            "is_feasible_date": feasible,
            "blocking_conflict": blocking,
            "suggested_start": suggested,
            "estimated_duration_hours": 4.0,
        },
    }


# ── _is_affirmative ──
@pytest.mark.parametrize("ans,expected", [
    ("confirm", True), ("yes please", True), ("OK", True), ("book it", True),
    ("cancel", False), ("no", False), ("", False), ("yesterday", False),
])
def test_is_affirmative(ans, expected):
    assert orch._is_affirmative(ans) is expected


@pytest.mark.parametrize("msg,expected", [
    ("show me the steps", True),
    ("what are the steps to isolate it?", True),
    ("see the full procedure", True),
    ("show the SOP", True),
    ("can I shut pipe_084 on 2026-07-06, planned?", False),
    ("confirm", False),
])
def test_is_steps_request(msg, expected):
    assert orch._is_steps_request(msg) is expected


# ── near-term emergency nudge ──
def test_is_near_term():
    today = datetime.now().date()
    assert orch._is_near_term(today.isoformat()) is True
    assert orch._is_near_term((today + timedelta(days=1)).isoformat()) is True
    assert orch._is_near_term((today + timedelta(days=5)).isoformat()) is False
    assert orch._is_near_term(None) is False
    assert orch._is_near_term("not-a-date") is False


def test_clarification_slot_order():
    assert orch._next_clarification_slot({})[0] == "pipe_id"
    assert orch._next_clarification_slot({"pipe_id": "pipe_084"})[0] == "date"


def test_clarification_planned_asks_end_date_last():
    slot, q = orch._next_clarification_slot(
        {"pipe_id": "pipe_084", "target_date": "2026-08-17", "operation_class": "PLANNED"}
    )
    assert slot == "end_date"
    assert "end date" in q.lower() and "plan it for me" in q.lower()


def test_route_requires_end_date_mode_for_planned_only():
    base = {"operation_type": "SHUTDOWN", "pipe_id": "pipe_084",
            "target_date": "2026-08-17"}
    # PLANNED without an end-date answer -> keep clarifying.
    assert orch.route_after_intent({**base, "operation_class": "PLANNED"}) == "clarification"
    # PLANNED with either answer -> proceed.
    assert orch.route_after_intent(
        {**base, "operation_class": "PLANNED", "end_date_mode": "AUTO"}) == "neo4j_agent"
    assert orch.route_after_intent(
        {**base, "operation_class": "PLANNED", "end_date_mode": "USER",
         "target_end_date": "2026-08-20"}) == "neo4j_agent"
    # EMERGENCY skips the end-date question entirely.
    assert orch.route_after_intent({**base, "operation_class": "EMERGENCY"}) == "neo4j_agent"


def test_clarification_far_date_asks_neutral_class():
    far = (datetime.now().date() + timedelta(days=10)).isoformat()
    slot, q = orch._next_clarification_slot({"pipe_id": "pipe_084", "target_date": far})
    assert slot == "operation_class"
    assert "short notice" not in q.lower()


def test_clarification_near_term_nudges_emergency():
    for d in (datetime.now().date(), datetime.now().date() + timedelta(days=1)):
        slot, q = orch._next_clarification_slot(
            {"pipe_id": "pipe_084", "target_date": d.isoformat()}
        )
        assert slot == "operation_class"
        assert "emergency" in q.lower() and "short notice" in q.lower()


# ── month schedule preview (shown when the date is given) ──
def test_month_schedule_preview_lists_ops(monkeypatch):
    ops = [{"operation_id": "OPS-1", "pipe_id": "pipe_043",
            "scheduled_start": "2026-07-13T08:00:00", "scheduled_end": "2026-07-15T16:00:00"}]
    monkeypatch.setattr(orch, "get_active_operations", lambda: ops)
    out = orch._month_schedule_preview("2026-07-08")
    assert "Operation plans that are already scheduled in July 2026" in out
    assert "| Operation | Pipe | When |" in out
    assert "OPS-1" in out and "`pipe_043`" in out


def test_month_schedule_preview_empty(monkeypatch):
    monkeypatch.setattr(orch, "get_active_operations", lambda: [])
    assert "calendar is clear" in orch._month_schedule_preview("2026-07-08")


def test_month_schedule_preview_bad_date():
    assert orch._month_schedule_preview(None) == ""
    assert orch._month_schedule_preview("not-a-date") == ""


# ── emergency-vs-emergency priority decision ──
_CONFLICT = [{"operation_id": "OPS-OLD", "pipe_id": "pipe_010",
              "scheduled_start": "2026-08-19T10:00:00", "scheduled_end": "2026-08-19T16:00:00"}]


def _emerg_state(op_class="EMERGENCY"):
    return {
        "pipe_id": "pipe_084", "operation_type": "SHUTDOWN", "operation_class": op_class,
        "scheduled_start": "2026-08-19T10:00:00", "scheduled_end": "2026-08-19T14:00:00",
        "sop_chain": {"shutdown_valves": ["v1", "v2"]},
        "schedule_proposals": [],
        "calendar_context": {"estimated_duration_hours": 4.0, "conflicting_emergencies": _CONFLICT},
    }


@pytest.mark.parametrize("ans,expected", [
    ("new", "new"), ("run this first", "new"),
    ("OPS-OLD", "OPS-OLD"), ("keep ops-old first", "OPS-OLD"),
    ("cancel", None), ("", None), ("huh?", None),
])
def test_resolve_emergency_priority(ans, expected):
    assert orch._resolve_emergency_priority(ans, _CONFLICT) == expected


def test_priority_new_first_books_and_moves_other(monkeypatch):
    monkeypatch.setattr(orch, "create_scheduled_operation", lambda **kw: "OPS-NEW")
    moved = []
    monkeypatch.setattr(orch, "reschedule_operation",
                        lambda op, s, e: moved.append((op, s, e)) or True)
    out = orch._commit_emergency_priority(_emerg_state(), "new", _CONFLICT)
    assert out["booked_operation_id"] == "OPS-NEW"
    assert moved and moved[0][0] == "OPS-OLD"
    # the moved slot starts strictly after the new op's end date
    assert moved[0][1] > "2026-08-19T16:00:00"
    assert "Moved OPS-OLD" in out["final_response"]


def test_priority_existing_first_books_after_no_move(monkeypatch):
    captured = {}
    monkeypatch.setattr(orch, "create_scheduled_operation",
                        lambda **kw: captured.update(kw) or "OPS-NEW")
    monkeypatch.setattr(orch, "reschedule_operation",
                        lambda *a: (_ for _ in ()).throw(AssertionError("should not move")))
    out = orch._commit_emergency_priority(_emerg_state(), "OPS-OLD", _CONFLICT)
    assert out["booked_operation_id"] == "OPS-NEW"
    # new op scheduled AFTER the chosen op's end (2026-08-19) -> a later date
    assert captured["scheduled_start"] > "2026-08-19T16:00:00"
    assert "keeps its slot" in out["final_response"]


def test_priority_cancel_writes_nothing(monkeypatch):
    monkeypatch.setattr(orch, "create_scheduled_operation",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("should not book")))
    out = orch._commit_emergency_priority(_emerg_state(), None, _CONFLICT)
    assert "booked_operation_id" not in out
    assert "haven't booked" in out["final_response"]


# ── _window_to_offer ──
def test_offer_feasible_planned_uses_requested_window():
    s, e, prompt = orch._window_to_offer(_state(feasible=True))
    assert (s, e) == ("2026-07-06T10:00:00", "2026-07-06T14:00:00")
    assert "Confirm booking" in prompt


def test_offer_infeasible_planned_uses_suggested_slot():
    offer = orch._window_to_offer(_state(feasible=False, suggested="2026-07-21T10:00:00"))
    assert offer is not None
    s, e, prompt = offer
    assert s.startswith("2026-07-21")
    assert e.startswith("2026-07-21")
    assert "next valid slot" in prompt


def test_offer_infeasible_no_suggestion_is_none():
    assert orch._window_to_offer(_state(feasible=False, suggested=None)) is None


def test_offer_emergency_always_bookable():
    s, e, prompt = orch._window_to_offer(_state(op_class="EMERGENCY", feasible=True))
    assert (s, e) == ("2026-07-06T10:00:00", "2026-07-06T14:00:00")
    assert "EMERGENCY" in prompt


def test_offer_blocking_conflict_falls_back_to_suggested():
    offer = orch._window_to_offer(_state(feasible=True, blocking=True, suggested="2026-07-21T10:00:00"))
    assert offer[0].startswith("2026-07-21")


def test_offer_no_window_is_none():
    st = _state()
    st["scheduled_start"] = None
    assert orch._window_to_offer(st) is None


# ── _commit_booking ──
def test_commit_confirm_creates_operation(monkeypatch):
    captured = {}
    monkeypatch.setattr(orch, "create_scheduled_operation",
                        lambda **kw: captured.update(kw) or "OPS-TEST123")
    out = orch._commit_booking(_state(), "confirm", "2026-07-06T10:00:00", "2026-07-06T14:00:00")

    assert out["booked_operation_id"] == "OPS-TEST123"
    assert "Booked" in out["final_response"]
    assert captured["operation_class"] == "PLANNED"
    assert captured["valve_ids"] == ["v1", "v2", "v3"]
    assert captured["scheduled_start"] == "2026-07-06T10:00:00"
    assert "/api/v1/operations/OPS-TEST123/report" in out["final_response"]


def test_commit_cancel_writes_nothing(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(orch, "create_scheduled_operation",
                        lambda **kw: calls.__setitem__("n", calls["n"] + 1) or "OPS-X")
    out = orch._commit_booking(_state(), "cancel", "2026-07-06T10:00:00", "2026-07-06T14:00:00")

    assert calls["n"] == 0
    assert "booked_operation_id" not in out
    assert "haven't booked" in out["final_response"]


def test_commit_emergency_reschedules_displaced(monkeypatch):
    monkeypatch.setattr(orch, "create_scheduled_operation", lambda **kw: "OPS-EMERG")
    resched = []
    monkeypatch.setattr(orch, "reschedule_operation",
                        lambda op, s, e: resched.append((op, s, e)) or True)
    proposals = [{"operation_id": "op-1",
                  "proposed_start": "2026-07-21T10:00:00",
                  "proposed_end": "2026-07-21T14:00:00"}]
    out = orch._commit_booking(
        _state(op_class="EMERGENCY", proposals=proposals),
        "confirm", "2026-07-06T10:00:00", "2026-07-06T14:00:00",
    )

    assert out["booked_operation_id"] == "OPS-EMERG"
    assert resched == [("op-1", "2026-07-21T10:00:00", "2026-07-21T14:00:00")]
    assert "Rescheduled op-1" in out["final_response"]
    assert "/api/v1/operations/OPS-EMERG/report" in out["final_response"]


def test_priority_new_first_includes_report_link(monkeypatch):
    monkeypatch.setattr(orch, "create_scheduled_operation", lambda **kw: "OPS-PRIO1")
    monkeypatch.setattr(orch, "reschedule_operation", lambda op, s, e: True)
    out = orch._commit_emergency_priority(_emerg_state(), "new", _CONFLICT)
    assert "/api/v1/operations/OPS-PRIO1/report" in out["final_response"]
