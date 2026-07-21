"""Per-step schedule for the confirmed-operation PDF report.

Anchors the deterministic valve-timing engine (tools/valve_operation_rules.py)
to the operation's already-booked scheduled_start via the day-layout engine
(tools/scheduling_rules.py), so every step's timestamp is derived from the same
math that sized the booked window in the first place — never a second,
independently-derived timing engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from tools import scheduling_rules as sr
from tools import valve_operation_rules as vor


@dataclass(frozen=True)
class ReportStep:
    seq: int
    start: datetime
    end: datetime
    action: str
    valve_id: str
    pipe_id: Optional[str]
    diameter_mm: float
    minutes: float
    day_split: bool   # start.date() != end.date() — render as "(spans overnight)"


def build_step_schedule(
    chain: dict[str, Any],
    scheduled_start: str,
    travel_minutes: float = vor.DAILY_TRAVEL_MINUTES,
    path: Optional[str] = None,
) -> tuple[list[ReportStep], datetime, datetime, list[date]]:
    """Lay the chain's valve actions out from the operation's booked start.

    setup_hours is deliberately 0.0: vor.operation_duration_hours (which sizes
    every real SOP-driven booking) never adds SETUP_HOURS, so reserving real
    elapsed time for it here would push the last step's end past the booked
    scheduled_end already persisted in the calendar. Setup is called out as a
    static note in the PDF instead of a time block.
    """
    vsteps = vor.chain_valve_steps(chain, travel_minutes=travel_minutes)
    minutes = [s.total_minutes for s in vsteps]
    layout = sr.layout_working_steps(scheduled_start, minutes, path=path, setup_hours=0.0)

    steps = [
        ReportStep(
            seq=vs.seq,
            start=s0,
            end=s1,
            action=vs.action,
            valve_id=vs.valve_id,
            pipe_id=vs.pipe_id,
            diameter_mm=vs.diameter_mm,
            minutes=vs.total_minutes,
            day_split=(s0.date() != s1.date()),
        )
        for vs, (s0, s1) in zip(vsteps, layout.steps)
    ]
    return steps, layout.start, layout.end, layout.working_days
