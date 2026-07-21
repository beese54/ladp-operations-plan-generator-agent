"""Tests for reporting/timeline.py (build_step_schedule)."""
from datetime import datetime

import pytest

from reporting.timeline import build_step_schedule
from tools import scheduling_rules as sr
from tools import valve_operation_rules as vor

_CHAIN_WITH_ALT = {
    "pipe_id": "pipe_084",
    "shutdown_valves": ["v1", "v2", "v3", "v4"],
    "shutdown_pipes": ["p1", "p2", "p3"],
    "tail_valve_id": "v4",
    "alternate_feed": {"from_valve_id": "va", "pipe_id": "p-alt"},
    "reverse_checks": [
        {"from_valve": "v4", "to_valve": "v3", "pipe_id": "p-r1"},
        {"from_valve": "v3", "to_valve": "v2", "pipe_id": "p-r2"},
        {"from_valve": "v2", "to_valve": "v1", "pipe_id": "p-r3"},
    ],
    "valve_diameters": {k: 300 for k in ["v1", "v2", "v3", "v4", "va"]},
}

_CHAIN_NO_ALT = {
    "pipe_id": "pipe_099",
    "shutdown_valves": ["v1", "v2"],
    "shutdown_pipes": ["p1"],
    "tail_valve_id": "v2",
    "alternate_feed": None,
    "reverse_checks": [],
    "valve_diameters": {"v1": 300, "v2": 300},
}


def test_build_step_schedule_step_count_matches_chain_valve_steps():
    steps, _start, _end, _days = build_step_schedule(_CHAIN_WITH_ALT, "2026-06-17T10:00:00")
    assert len(steps) == len(vor.chain_valve_steps(_CHAIN_WITH_ALT))


def test_build_step_schedule_total_matches_operation_duration_hours():
    steps, start_dt, end_dt, _days = build_step_schedule(_CHAIN_WITH_ALT, "2026-06-17T10:00:00")
    total_minutes = sum(s.minutes for s in steps)
    assert total_minutes / 60.0 == pytest.approx(vor.operation_duration_hours(_CHAIN_WITH_ALT))


def test_build_step_schedule_end_matches_layout_working_window():
    steps, start_dt, end_dt, days = build_step_schedule(_CHAIN_WITH_ALT, "2026-06-17T10:00:00")
    duration_hours = vor.operation_duration_hours(_CHAIN_WITH_ALT)
    _s, expected_end, expected_days = sr.layout_working_window("2026-06-17", duration_hours)
    assert end_dt == expected_end
    assert days == expected_days
    assert steps[-1].end == expected_end


def test_build_step_schedule_anchored_at_scheduled_start_not_target_date():
    # scheduled_start already includes the time-of-day the operation was booked at.
    steps, start_dt, _end, _days = build_step_schedule(_CHAIN_NO_ALT, "2026-06-17T10:00:00")
    assert start_dt == datetime(2026, 6, 17, 10, 0)
    assert steps[0].start == datetime(2026, 6, 17, 10, 0)


def test_build_step_schedule_no_setup_time_reserved():
    # setup_hours=0.0 in build_step_schedule — the first step must start
    # immediately at scheduled_start, not an hour later.
    steps, start_dt, _end, _days = build_step_schedule(_CHAIN_NO_ALT, "2026-06-17T10:00:00")
    assert steps[0].start == start_dt
