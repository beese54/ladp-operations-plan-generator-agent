"""Tests for the schedule agent node (Phase 3, S3.4).

The agent now *sizes* the operation from the shutdown chain's valve count, lays
it out across working days (10:00-16:00) to compute the window, then validates.
SQLite-backed helpers are monkeypatched so the tests are hermetic.

Anchor dates (all 2026, consistent with tests/test_scheduling_rules.py):
  - 2026-06-17  Wednesday, clear of any blackout  -> feasible.
  - 2026-06-19  Friday, clear of blackout          -> isolates R3.
  - 2026-02-16  Monday, within 7 days of CNY       -> R1 blackout.
  - 2026-09-15  Tuesday, clear                      -> emergency window.
"""
from datetime import datetime

import pytest

from agents import calendar_agent
from tools import scheduling_rules as sr


def _state(target_date, op_class="PLANNED", valves=2, pipe_id="pipe_084",
           end_date_mode=None, target_end_date=None):
    """Build a state with a stubbed shutdown chain of `valves` valves."""
    state = {
        "pipe_id": pipe_id,
        "target_date": target_date,
        "operation_class": op_class,
        "sop_chain": {"shutdown_valves": [f"v{i}" for i in range(valves)]},
    }
    if end_date_mode:
        state["end_date_mode"] = end_date_mode
    if target_end_date:
        state["target_end_date"] = target_end_date
    return state


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
def test_planned_clean_start_is_feasible_and_computes_window(no_db):
    out = calendar_agent.calendar_agent_node(_state("2026-06-17", valves=2))
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is True
    assert ctx["rule_violations"] == []
    # 2 small valves (closes only) fit in one 10:00-16:00 working day.
    assert out["scheduled_start"] == "2026-06-17T10:00:00"
    assert out["scheduled_end"].startswith("2026-06-17T")
    assert out["date_range_end"] == "2026-06-17"
    assert ctx["working_days_count"] == 1
    assert ctx["estimated_duration_hours"] > 0


def test_planned_friday_start_flags_r3_and_suggests_slot(no_db):
    out = calendar_agent.calendar_agent_node(_state("2026-06-19", valves=2))  # Friday
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is False
    assert any(v.startswith("R3") for v in ctx["rule_violations"])
    assert ctx["suggested_start"] is not None
    suggested = datetime.fromisoformat(ctx["suggested_start"])
    assert suggested.weekday() != sr.FRIDAY
    assert sr.is_working_day(suggested)


def test_planned_blackout_date_flags_r1(no_db):
    out = calendar_agent.calendar_agent_node(_state("2026-02-16", valves=2))
    ctx = out["calendar_context"]

    assert ctx["is_feasible_date"] is False
    assert any(v.startswith("R1") for v in ctx["rule_violations"])
    assert ctx["suggested_start"] is not None


def test_planned_large_chain_spans_multiple_days(no_db):
    # 10 valves -> 1 + 10*0.75 = 8.5h -> spills past 6h/day onto a second day.
    out = calendar_agent.calendar_agent_node(_state("2026-06-17", valves=10))
    ctx = out["calendar_context"]
    assert ctx["working_days_count"] >= 2
    assert out["scheduled_end"][:10] > out["scheduled_start"][:10]


# --------------------------------------------------------------------------- #
# Operator-driven end date (PLANNED only)
# --------------------------------------------------------------------------- #
def test_planned_user_end_date_honored_when_long_enough(no_db):
    # 2 valves fit in one day; the operator allows until the following Tuesday.
    out = calendar_agent.calendar_agent_node(
        _state("2026-06-17", valves=2, end_date_mode="USER", target_end_date="2026-06-23"))
    ctx = out["calendar_context"]

    assert out["scheduled_end"] == "2026-06-23T16:00:00"
    assert out["date_range_end"] == "2026-06-23"
    assert ctx["requested_end_date"] == "2026-06-23"
    assert ctx["window_auto_extended"] is False
    # Wed 17 -> Tue 23 inclusive = 5 working days (weekend skipped).
    assert ctx["working_days_count"] == 5


def test_planned_user_end_too_short_auto_extends(no_db):
    # 10 valves -> 8.5h -> needs 2 working days; operator only allows day 1.
    out = calendar_agent.calendar_agent_node(
        _state("2026-06-17", valves=10, end_date_mode="USER", target_end_date="2026-06-17"))
    ctx = out["calendar_context"]

    assert ctx["window_auto_extended"] is True
    assert ctx["requested_end_date"] == "2026-06-17"
    assert out["scheduled_end"].startswith("2026-06-18")  # extended to fit the work
    assert ctx["working_days_count"] == 2


def test_emergency_ignores_user_end_date(no_db):
    out = calendar_agent.calendar_agent_node(
        _state("2026-09-15", op_class="EMERGENCY", valves=2,
               end_date_mode="USER", target_end_date="2026-09-30"))
    ctx = out["calendar_context"]

    assert ctx["requested_end_date"] is None
    assert ctx["window_auto_extended"] is False
    assert out["scheduled_end"].startswith("2026-09-15")  # auto-sized, not 09-30


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

    out = calendar_agent.calendar_agent_node(
        _state("2026-09-15", op_class="EMERGENCY", valves=2)
    )
    ctx = out["calendar_context"]
    proposals = out["schedule_proposals"]

    assert ctx["is_feasible_date"] is True
    assert [d["operation_id"] for d in ctx["displaced_ops"]] == ["op-seed-1"]
    assert len(proposals) == 1
    p = proposals[0]
    assert p["operation_id"] == "op-seed-1"
    new_start = datetime.fromisoformat(p["proposed_start"])
    assert new_start.date() > datetime.fromisoformat(planned["scheduled_end"]).date()
    assert new_start.weekday() != sr.FRIDAY
    assert sr.is_working_day(new_start)


def test_operations_in_month_filters_and_flags_clash():
    existing = [
        {"operation_id": "A", "pipe_id": "pipe_001",
         "scheduled_start": "2026-07-06T10:00:00", "scheduled_end": "2026-07-06T16:00:00"},
        {"operation_id": "B", "pipe_id": "pipe_002",
         "scheduled_start": "2026-07-20T10:00:00", "scheduled_end": "2026-07-20T16:00:00"},
        {"operation_id": "C", "pipe_id": "pipe_003",  # August — different month
         "scheduled_start": "2026-08-03T10:00:00", "scheduled_end": "2026-08-03T16:00:00"},
    ]
    res = calendar_agent._operations_in_month(
        existing, "2026-07-06", "2026-07-06T12:00:00", "2026-07-06T18:00:00")
    flags = {o["operation_id"]: o["clash"] for o in res}
    assert set(flags) == {"A", "B"}     # only July ops surface
    assert flags["A"] is True           # overlaps the proposed window
    assert flags["B"] is False          # same month, no overlap


def test_operations_in_range_spans_multiple_months():
    existing = [
        {"operation_id": "A", "pipe_id": "pipe_001",  # July — before the range
         "scheduled_start": "2026-07-20T10:00:00", "scheduled_end": "2026-07-20T16:00:00"},
        {"operation_id": "B", "pipe_id": "pipe_002",  # August — inside the range
         "scheduled_start": "2026-08-03T10:00:00", "scheduled_end": "2026-08-03T16:00:00"},
        {"operation_id": "C", "pipe_id": "pipe_003",  # October — inside the range
         "scheduled_start": "2026-10-12T10:00:00", "scheduled_end": "2026-10-12T16:00:00"},
        {"operation_id": "D", "pipe_id": "pipe_004",  # December — after the range
         "scheduled_start": "2026-12-01T10:00:00", "scheduled_end": "2026-12-01T16:00:00"},
    ]
    res = calendar_agent._operations_in_range(existing, "2026-08-01", "2026-11-01")
    assert {o["operation_id"] for o in res} == {"B", "C"}


def test_operations_in_range_handles_reversed_dates():
    existing = [{"operation_id": "B", "pipe_id": "pipe_002",
                 "scheduled_start": "2026-08-03T10:00:00", "scheduled_end": "2026-08-03T16:00:00"}]
    res = calendar_agent._operations_in_range(existing, "2026-11-01", "2026-08-01")
    assert {o["operation_id"] for o in res} == {"B"}


def test_month_operations_empty_when_no_other_ops(no_db):
    out = calendar_agent.calendar_agent_node(_state("2026-06-17", valves=2))
    assert out["calendar_context"]["month_operations"] == []


def test_month_operations_surface_and_flag_clash(monkeypatch):
    op = {"operation_id": "OPS-X", "pipe_id": "pipe_033", "operation_class": "PLANNED",
          "status": "PLANNED", "scheduled_start": "2026-06-17T11:00:00",
          "scheduled_end": "2026-06-17T15:00:00"}
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [op])
    monkeypatch.setattr(calendar_agent, "check_pipe_schedule_conflicts",
                        lambda p, s, e: [])
    out = calendar_agent.calendar_agent_node(_state("2026-06-17", valves=2))
    mo = out["calendar_context"]["month_operations"]
    assert [o["operation_id"] for o in mo] == ["OPS-X"]
    assert mo[0]["clash"] is True


def test_emergency_detects_conflicting_emergency(monkeypatch):
    existing_em = {"operation_id": "E-OLD", "pipe_id": "pipe_010",
                   "operation_class": "EMERGENCY", "status": "PLANNED",
                   "scheduled_start": "2026-09-15T10:00:00", "scheduled_end": "2026-09-15T16:00:00"}
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [existing_em])
    monkeypatch.setattr(calendar_agent, "check_pipe_schedule_conflicts",
                        lambda p, s, e: [])
    out = calendar_agent.calendar_agent_node(
        _state("2026-09-15", op_class="EMERGENCY", valves=2))
    ce = out["calendar_context"]["conflicting_emergencies"]
    assert [o["operation_id"] for o in ce] == ["E-OLD"]
    # an existing emergency is NOT treated as a PLANNED displacement
    assert out["calendar_context"]["displaced_ops"] == []


def test_emergency_no_overlap_yields_no_proposals(monkeypatch):
    planned = {
        "operation_id": "op-seed-2",
        "pipe_id": "pipe_033",
        "operation_class": "PLANNED",
        "status": "PLANNED",
        "scheduled_start": "2026-10-20T10:00:00",
        "scheduled_end": "2026-10-20T16:00:00",
    }
    monkeypatch.setattr(calendar_agent, "get_active_operations", lambda: [planned])
    monkeypatch.setattr(
        calendar_agent, "check_pipe_schedule_conflicts",
        lambda pipe_id, start, end: [],
    )

    out = calendar_agent.calendar_agent_node(
        _state("2026-09-15", op_class="EMERGENCY", valves=2)
    )
    assert out["calendar_context"]["displaced_ops"] == []
    assert out["schedule_proposals"] == []
