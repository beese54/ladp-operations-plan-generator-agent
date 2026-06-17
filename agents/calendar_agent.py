"""Schedule agent: size the operation, then evaluate scheduling rules.

The operation's effort is derived from the number of valves in the deterministic
shutdown chain and laid out across working days (10:00-16:00, skipping weekends
and public holidays) to compute the start/end window. That window is then:

  PLANNED   - validated against R1 (holiday blackout), R2 (>=3 working-day gap),
              R3 (no Friday start); on failure the next valid start is suggested.
  EMERGENCY - rules bypassed; the agent finds the PLANNED ops the window
              displaces and proposes a valid new slot for each.

No LLM is used here. The window is set on top-level state so downstream nodes
and the response use the system-computed schedule.
"""
import logging
from datetime import datetime

from schemas.graph_state import OrchestratorState, CalendarContext
from tools.calendar_tools import check_pipe_schedule_conflicts, get_active_operations
from tools import scheduling_rules as sr

logger = logging.getLogger(__name__)


def _valve_count(state: OrchestratorState) -> int:
    """Number of valves to operate, from the deterministic shutdown chain.

    Falls back to the two boundary valves if the chain is unavailable.
    """
    chain = state.get("sop_chain") or {}
    valves = chain.get("shutdown_valves") or []
    return len(valves) if valves else 2


def _empty_context(start: str, end: str, op_class: str, duration: float, days: int) -> CalendarContext:
    return CalendarContext(
        is_feasible_date=True, conflicts=[], blocking_conflict=False,
        checked_start=start, checked_end=end, operation_class=op_class,
        rule_violations=[], suggested_start=None, displaced_ops=[],
        estimated_duration_hours=duration, working_days_count=days,
    )


def calendar_agent_node(state: OrchestratorState) -> dict:
    pipe_id = state.get("pipe_id", "")
    target_date = state.get("target_date", "")
    op_class = (state.get("operation_class") or "PLANNED").upper()

    if not pipe_id or not target_date:
        logger.warning("Schedule agent called without pipe_id/target_date")
        return {
            "calendar_context": _empty_context("", "", op_class, 0.0, 0),
            "agents_completed": ["calendar"],
        }

    # ── Size the operation and lay it out across working days ──
    duration = sr.estimate_duration_hours(_valve_count(state))
    start_dt, end_dt, working_days = sr.layout_working_window(target_date, duration)
    start, end = start_dt.isoformat(), end_dt.isoformat()
    days_count = len(working_days)

    try:
        existing = get_active_operations()
    except Exception as e:
        logger.error("Could not load active operations: %s", e)
        existing = []

    # ── EMERGENCY: bypass rules, find displaced planned ops, propose new slots ──
    if op_class == "EMERGENCY":
        displaced = sr.find_displaced(start, end, existing)
        proposals = []
        emergency_op = {
            "operation_id": "EMERGENCY-NEW", "scheduled_start": start,
            "scheduled_end": end, "status": "PLANNED", "operation_class": "EMERGENCY",
        }
        for op in displaced:
            o_start = datetime.fromisoformat(op["scheduled_start"])
            o_end = datetime.fromisoformat(op["scheduled_end"])
            op_hours = max((o_end - o_start).total_seconds() / 3600.0, sr.DAILY_WORK_HOURS)
            others = [o for o in existing if o["operation_id"] != op["operation_id"]]
            others.append(emergency_op)
            try:
                new_start_date = sr.next_valid_layout_start(end_dt.date(), op_hours, others)
                ns, ne, _days = sr.layout_working_window(new_start_date, op_hours)
                proposals.append({
                    "operation_id": op["operation_id"],
                    "title": op.get("title", ""),
                    "pipe_id": op.get("pipe_id", ""),
                    "old_start": op["scheduled_start"], "old_end": op["scheduled_end"],
                    "proposed_start": ns.isoformat(),
                    "proposed_end": ne.isoformat(),
                })
            except ValueError as e:
                logger.warning("No reschedule slot for %s: %s", op["operation_id"], e)

        ctx = _empty_context(start, end, op_class, duration, days_count)
        ctx["displaced_ops"] = displaced
        return {
            "calendar_context": ctx,
            "scheduled_start": start,
            "scheduled_end": end,
            "date_range_end": end_dt.date().isoformat(),
            "schedule_proposals": proposals,
            "agents_completed": ["calendar"],
        }

    # ── PLANNED: validate against R1/R2/R3 ──
    result = sr.validate_planned(start, end, existing)
    try:
        pipe_conflicts = check_pipe_schedule_conflicts(pipe_id, start, end)
    except Exception as e:
        logger.error("Pipe conflict check failed: %s", e)
        pipe_conflicts = []

    suggested = None
    if not result.ok:
        try:
            slot = sr.next_valid_layout_start(target_date, duration, existing)
            suggested = datetime.combine(slot, start_dt.time()).isoformat()
        except ValueError as e:
            logger.warning("No valid slot found: %s", e)

    blocking = (not result.ok) or any(c["severity"] == "BLOCKING" for c in pipe_conflicts)

    context = CalendarContext(
        is_feasible_date=result.ok,
        conflicts=pipe_conflicts,
        blocking_conflict=blocking,
        checked_start=start,
        checked_end=end,
        operation_class=op_class,
        rule_violations=result.violations,
        suggested_start=suggested,
        displaced_ops=[],
        estimated_duration_hours=duration,
        working_days_count=days_count,
    )

    return {
        "calendar_context": context,
        "scheduled_start": start,
        "scheduled_end": end,
        "date_range_end": end_dt.date().isoformat(),
        "agents_completed": ["calendar"],
    }
