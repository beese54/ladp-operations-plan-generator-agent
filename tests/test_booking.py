"""Tests for the booking gate helpers (Phase 4, S4.1-S4.3).

The interrupt itself is exercised live; here we unit-test the pure decision and
commit logic with the DB writes monkeypatched.
"""
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
