import logging
from schemas.graph_state import OrchestratorState, CalendarContext
from tools.calendar_tools import check_pipe_schedule_conflicts

logger = logging.getLogger(__name__)

DEFAULT_DURATION_HOURS = 8  # used only internally for overlap checks; user is always asked for time


def calendar_agent_node(state: OrchestratorState) -> dict:
    pipe_id = state.get("pipe_id", "")
    start = state.get("scheduled_start", "")
    end = state.get("scheduled_end", "")

    if not pipe_id or not start or not end:
        logger.warning("Calendar agent called without complete pipe_id/start/end")
        return {
            "calendar_context": CalendarContext(
                is_feasible_date=True,
                conflicts=[],
                blocking_conflict=False,
                checked_start=start,
                checked_end=end,
            ),
            "agents_completed": state.get("agents_completed", []) + ["calendar"],
        }

    try:
        raw_conflicts = check_pipe_schedule_conflicts(pipe_id, start, end)
    except Exception as e:
        logger.error("Calendar agent error: %s", e)
        raw_conflicts = []

    blocking = any(c["severity"] == "BLOCKING" for c in raw_conflicts)

    context = CalendarContext(
        is_feasible_date=not blocking,
        conflicts=raw_conflicts,
        blocking_conflict=blocking,
        checked_start=start,
        checked_end=end,
    )

    return {
        "calendar_context": context,
        "agents_completed": state.get("agents_completed", []) + ["calendar"],
    }
