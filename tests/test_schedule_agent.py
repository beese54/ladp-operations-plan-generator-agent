"""Tests for the schedule agent node (Phase 2, S2.3).

These exercise agents.calendar_agent.calendar_agent_node end-to-end against the
real deterministic rules engine, but with the SQLite-backed helpers
(get_active_operations / check_pipe_schedule_conflicts) monkeypatched so the
test is hermetic and does not depend on calendar.db contents.

Anchor dates (all 2026, consistent with tests/test_scheduling_rules.py):
  - 2026-06-19  Friday, clear of any holiday blackout  -> isolates R3.
  - 2026-02-17  Chinese New Year                        -> 02-16 is in blackout.
  - 2026-09-15  Tuesday, clear of any blackout          -> emergency window.
"""
from datetime import datetime

import pytest

from agents import calendar_agent
from tools import scheduling_rules as sr


@pytest.fixture
def no_db(monkeypatch):
    """Default: no existing operations and no pipe conflicts."""
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [])
    monkeypatch.setattr(
        calendar_agent, "check_pipe_schedule_conflicts",
        lambda pipe_id, start, end: [],
    )


# --------------------------------------------------------------------------- #
# PLANNED path
# --------------------------------------------------------------------------- #
def test_planned_friday_start_flags_r3_and_suggests_slot(no_db):
    state = {
        "pipe_id": "pipe_084",
        "scheduled_start": "2026-06-19T08:00:00",   # Friday, no blackout
        "scheduled_end": "2026-06-19T16:00:00",
        "operation_class": "PLANNED",
    }
    out = calendar_agent.calendar_agent_node(state)
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is False
    assert any(v.startswith("R3") for v in ctx["rule_violations"])
    # A concrete alternative slot must be offered, and it must be valid.
    assert ctx["suggested_start"] is not None
    suggested = datetime.fromisoformat(ctx["suggested_start"])
    assert suggested.weekday() != sr.FRIDAY
    assert sr.is_working_day(suggested)


def test_planned_blackout_date_flags_r1(no_db):
    state = {
        "pipe_id": "pipe_084",
        "scheduled_start": "2026-02-16T08:00:00",   # within 7 days of CNY (02-17)
        "scheduled_end": "2026-02-16T16:00:00",
        "operation_class": "PLANNED",
    }
    out = calendar_agent.calendar_agent_node(state)
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is False
    assert any(v.startswith("R1") for v in ctx["rule_violations"])
    assert ctx["suggested_start"] is not None


def test_planned_clean_window_is_feasible(no_db):
    state = {
        "pipe_id": "pipe_084",
        "scheduled_start": "2026-06-17T08:00:00",   # Wednesday, clear
        "scheduled_end": "2026-06-17T16:00:00",
        "operation_class": "PLANNED",
    }
    out = calendar_agent.calendar_agent_node(state)
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is True
    assert ctx["rule_violations"] == []
    assert ctx["suggested_start"] is None


# --------------------------------------------------------------------------- #
# EMERGENCY path
# --------------------------------------------------------------------------- #
def test_emergency_displaces_overlapping_planned_and_proposes_slot(monkeypatch):
    planned = {
        "operation_id": "op-seed-1",
        "title": "Seeded planned shutdown",
        "pipe_id": "pipe_033",
        "operation_class": "PLANNED",
        "status": "PLANNED",
        "scheduled_start": "2026-09-15T10:00:00",
        "scheduled_end": "2026-09-15T14:00:00",
    }
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [planned])
    monkeypatch.setattr(
        calendar_agent, "check_pipe_schedule_conflicts",
        lambda pipe_id, start, end: [],
    )

    state = {
        "pipe_id": "pipe_084",
        "scheduled_start": "2026-09-15T08:00:00",   # overlaps the planned op
        "scheduled_end": "2026-09-15T16:00:00",
        "operation_class": "EMERGENCY",
    }
    out = calendar_agent.calendar_agent_node(state)
    ctx = out["calendar_context"]
    proposals = out["schedule_proposals"]

    # Emergency itself is always feasible.
    assert ctx["is_feasible_date"] is True
    # The overlapping planned op is identified as displaced.
    assert [d["operation_id"] for d in ctx["displaced_ops"]] == ["op-seed-1"]

    # One reschedule proposal, for that op, at a valid new slot after the emergency.
    assert len(proposals) == 1
    p = proposals[0]
    assert p["operation_id"] == "op-seed-1"
    new_start = datetime.fromisoformat(p["proposed_start"])
    assert new_start > datetime.fromisoformat(planned["scheduled_end"])
    assert new_start.weekday() != sr.FRIDAY
    assert sr.is_working_day(new_start)
    # Duration is preserved.
    old_dur = datetime.fromisoformat(planned["scheduled_end"]) - datetime.fromisoformat(planned["scheduled_start"])
    new_dur = datetime.fromisoformat(p["proposed_end"]) - new_start
    assert new_dur == old_dur


def test_emergency_no_overlap_yields_no_proposals(monkeypatch):
    planned = {
        "operation_id": "op-seed-2",
        "pipe_id": "pipe_033",
        "operation_class": "PLANNED",
        "status": "PLANNED",
        "scheduled_start": "2026-10-20T08:00:00",
        "scheduled_end": "2026-10-20T16:00:00",
    }
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [planned])
    monkeypatch.setattr(
        calendar_agent, "check_pipe_schedule_conflicts",
        lambda pipe_id, start, end: [],
    )

    state = {
        "pipe_id": "pipe_084",
        "scheduled_start": "2026-09-15T08:00:00",   # no overlap with the planned op
        "scheduled_end": "2026-09-15T16:00:00",
        "operation_class": "EMERGENCY",
    }
    out = calendar_agent.calendar_agent_node(state)

    assert out["calendar_context"]["displaced_ops"] == []
    assert out["schedule_proposals"] == []
