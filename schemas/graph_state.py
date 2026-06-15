import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


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
    messages: Annotated[list, add_messages]
    session_id: str
    user_query_raw: str

    # Parsed intent
    pipe_id: Optional[str]
    target_date: Optional[str]           # ISO date "YYYY-MM-DD"
    scheduled_start: Optional[str]       # ISO datetime "YYYY-MM-DDTHH:MM:SS"
    scheduled_end: Optional[str]         # ISO datetime "YYYY-MM-DDTHH:MM:SS"
    operation_type: str                  # SHUTDOWN | INSPECTION | MAINTENANCE | GENERAL_QUERY | UNKNOWN
    intent_confidence: float

    # Clarification tracking
    clarification_round: int             # max 2 before hard stop
    awaiting_clarification: str          # "" | "pipe_id" | "date" | "time"

    # Agent outputs
    calendar_context: Optional[CalendarContext]
    topology_context: Optional[TopologyContext]
    sop_context: Optional[SOPContext]
    historical_context: Optional[HistoricalContext]
    operations_plan: Optional[OperationsPlan]
    sop_chain: Optional[dict[str, Any]]   # deterministic SOP walkthrough chain (build_sop_chain_data)

    # Orchestration control — Annotated so parallel nodes can both append safely
    agents_completed: Annotated[list[str], operator.add]
    error_messages: Annotated[list[str], operator.add]
    final_response: Optional[str]
