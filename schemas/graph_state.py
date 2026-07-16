import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


class OpsValveAction(TypedDict):
    valve_id: str
    road_name: str
    action: str              # CLOSE | OPEN | CHECK | MONITOR
    sequence_number: int
    reason: str
    timing_note: str
    current_status: str      # OPEN | CLOSED | UNKNOWN


class SchedulingConflict(TypedDict):
    conflicting_op_id: str
    conflict_type: str       # TIME_OVERLAP | SHARED_ASSET
    severity: str            # BLOCKING | WARNING
    title: str
    scheduled_start: str
    scheduled_end: str
    detail: str


class CalendarContext(TypedDict):
    is_feasible_date: bool
    conflicts: list[SchedulingConflict]
    blocking_conflict: bool
    checked_start: str       # ISO datetime string
    checked_end: str         # ISO datetime string
    operation_class: str            # PLANNED | EMERGENCY
    rule_violations: list[str]      # R1/R2/R3 messages (deterministic, planned only)
    suggested_start: Optional[str]  # next valid slot (ISO) when not feasible
    displaced_ops: list[dict[str, Any]]  # planned ops an emergency would displace
    estimated_duration_hours: float      # effort sized from the valve chain
    working_days_count: int              # working days the window spans
    month_operations: list[dict[str, Any]]  # ops scheduled in the requested month (clash-flagged)
    conflicting_emergencies: list[dict[str, Any]]  # active EMERGENCY ops overlapping this window
    requested_end_date: Optional[str]    # operator's intended end date, when given
    window_auto_extended: bool           # requested end was too short; window extended to fit


class TopologyContext(TypedDict):
    pipe_id: str
    partner_pipe_id: Optional[str]
    from_valve: dict[str, Any]
    to_valve: dict[str, Any]
    pipe_props: dict[str, Any]
    downstream_pipes: list[dict[str, Any]]
    alternative_path_exists: bool
    neighborhood_pipes: list[dict[str, Any]]


class SOPContext(TypedDict):
    retrieved_chunks: list[dict[str, Any]]
    relevant_principles: list[str]


class HistoricalContext(TypedDict):
    retrieved_chunks: list[dict[str, Any]]
    similar_plans: list[dict[str, Any]]


class OperationsPlan(TypedDict):
    feasibility_verdict: str              # FEASIBLE | NOT_FEASIBLE | CONDITIONAL
    feasibility_reason: str
    pre_operation_checks: list[str]
    valve_sequence: list[OpsValveAction]
    estimated_duration_hours: float
    affected_consumers_summary: str
    notifications_required: list[str]
    post_operation_steps: list[str]
    safety_warnings: list[str]
    alternative_recommendation: Optional[str]


class OrchestratorState(TypedDict):
    # Rolling chat transcript ({"role","content"} dicts), appended per turn so the
    # LLM nodes have conversational history. operator.add => append, never replace.
    messages: Annotated[list[dict[str, str]], operator.add]
    session_id: str
    user_query_raw: str

    # Parsed intent
    pipe_id: Optional[str]
    target_date: Optional[str]           # ISO date "YYYY-MM-DD"
    target_end_date: Optional[str]       # ISO date — operator's intended end (pipe back in service)
    end_date_mode: Optional[str]         # "USER" (end date given) | "AUTO" (agent sizes it) | None (not asked)
    scheduled_start: Optional[str]       # ISO datetime "YYYY-MM-DDTHH:MM:SS"
    scheduled_end: Optional[str]         # ISO datetime "YYYY-MM-DDTHH:MM:SS"
    operation_type: str                  # SHUTDOWN | INSPECTION | MAINTENANCE | GENERAL_QUERY | UNKNOWN
    operation_class: Optional[str]       # PLANNED | EMERGENCY
    date_range_end: Optional[str]        # ISO date "YYYY-MM-DD" — system-computed end date
    intent_confidence: float

    # Clarification tracking
    clarification_round: int             # max MAX_CLARIFICATION_ROUNDS before hard stop
    awaiting_clarification: str          # "" | "pipe_id" | "date" | "operation_class" | "end_date"

    # Scheduling proposals (emergency displaces planned -> suggested new slots)
    schedule_proposals: Optional[list[dict[str, Any]]]

    # Agent outputs
    calendar_context: Optional[CalendarContext]
    topology_context: Optional[TopologyContext]
    sop_context: Optional[SOPContext]
    historical_context: Optional[HistoricalContext]
    operations_plan: Optional[OperationsPlan]
    sop_chain: Optional[dict[str, Any]]   # deterministic SOP walkthrough chain (build_sop_chain_data)
    booked_operation_id: Optional[str]    # set once the operation is committed to the calendar

    # Orchestration control — Annotated so parallel nodes can both append safely
    agents_completed: Annotated[list[str], operator.add]
    error_messages: Annotated[list[str], operator.add]
    final_response: Optional[str]
