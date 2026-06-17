"""Schedule agent: deterministic rule evaluation over the operations calendar.

PLANNED ops are validated against R1 (holiday blackout), R2 (>=3 working-day gap),
and R3 (no Friday start); on failure the agent attaches the violations and the next
valid slot. EMERGENCY ops bypass all rules but the agent finds the PLANNED ops they
displace and proposes a valid new slot for each. No LLM is used here.
"""
import logging
from datetime import datetime

from schemas.graph_state import OrchestratorState, CalendarContext
from tools.calendar_tools import check_pipe_schedule_conflicts, get_active_operations
from tools import scheduling_rules as sr

logger = logging.getLogger(__name__)


def _duration_hours(start: str, end: str) -> float:
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    return max((e - s).total_seconds() / 3600.0, 1.0)


def _empty_context(start: str, end: str, op_class: str) -> CalendarContext:
    return CalendarContext(
        is_feasible_date=True, conflicts=[], blocking_conflict=False,
        checked_start=start, checked_end=end, operation_class=op_class,
        rule_violations=[], suggested_start=None, displaced_ops=[],
    )


def calendar_agent_node(state: OrchestratorState) -> dict:
    pipe_id = state.get("pipe_id", "")
    start = state.get("scheduled_start", "")
    end = state.get("scheduled_end", "")
    op_class = (state.get("operation_class") or "PLANNED").upper()

    if not pipe_id or not start or not end:
        logger.warning("Schedule agent called without complete pipe_id/start/end")
        return {
            "calendar_context": _empty_context(start, end, op_class),
            "agents_completed": state.get("agents_completed", []) + ["calendar"],
        }

    try:
        existing = get_active_operations()
    except Exception as e:
        logger.error("Could not load active operations: %s", e)
        existing = []

    # ── EMERGENCY: bypass all rules, find displaced planned ops, propose new slots ──
    if op_class == "EMERGENCY":
        displaced = sr.find_displaced(start, end, existing)
        proposals = []
        # The emergency now occupies its window; everything except each displaced op
        # remains booked when finding that op's replacement slot.
        emergency_op = {
            "operation_id": "EMERGENCY-NEW", "scheduled_start": start,
            "scheduled_end": end, "status": "PLANNED", "operation_class": "EMERGENCY",
        }
        for op in displaced:
            others = [o for o in existing if o["operation_id"] != op["operation_id"]]
            others.append(emergency_op)
            dur = _duration_hours(op["scheduled_start"], op["scheduled_end"])
            try:
                new_start = sr.next_valid_slot(op["scheduled_end"], dur, others)
                new_end = new_start.replace() + (datetime.fromisoformat(op["scheduled_end"])
                                                 - datetime.fromisoformat(op["scheduled_start"]))
                proposals.append({
                    "operation_id": op["operation_id"],
                    "title": op.get("title", ""),
                    "pipe_id": op.get("pipe_id", ""),
                    "old_start": op["scheduled_start"], "old_end": op["scheduled_end"],
                    "proposed_start": new_start.isoformat(),
                    "proposed_end": new_end.isoformat(),
                })
            except ValueError as e:
                logger.warning("No reschedule slot for %s: %s", op["operation_id"], e)

        ctx = _empty_context(start, end, op_class)
        ctx["displaced_ops"] = displaced
        return {
            "calendar_context": ctx,
            "schedule_proposals": proposals,
            "agents_completed": state.get("agents_completed", []) + ["calendar"],
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
            slot = sr.next_valid_slot(start, _duration_hours(start, end), existing)
            suggested = slot.isoformat()
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
    )

    return {
        "calendar_context": context,
        "agents_completed": state.get("agents_completed", []) + ["calendar"],
    }
