from typing import Any, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    message: str
    stream: bool = False


class ChatResponse(BaseModel):
    session_id: str
    message: str
    feasibility: Optional[Literal["FEASIBLE", "NOT_FEASIBLE", "CONDITIONAL"]] = None
    pipe_id: Optional[str] = None
    target_date: Optional[str] = None
    has_plan: bool = False
    operations_plan: Optional[dict[str, Any]] = None
    awaiting_clarification: bool = False
    booked_operation_id: Optional[str] = None
    processing_time_ms: int = 0
    # Non-null exactly on a turn the left-panel calendar should switch to/refresh:
    # a schedule-listing question was asked, or a booking was just committed.
    schedule_view: Optional[dict[str, int]] = None
    # RAG Triad observability — which path answered and what was retrieved.
    # Present only when useful (sop_rag path); None for deterministic paths
    # and clarification turns. The probe harness uses these for triad scoring.
    answer_path: Optional[str] = None           # system_knowledge | topology | sop_rag | plan_pipeline | off_topic
    retrieved_chunks: Optional[str] = None      # concatenated chunk texts (for groundedness/context scoring)


class CreateScheduleRequest(BaseModel):
    title: str
    operation_type: Literal["PLANNED_SHUTDOWN", "MAINTENANCE", "EMERGENCY", "INSPECTION"]
    pipe_id: Optional[str] = None
    zone_id: Optional[str] = None
    scheduled_start: str   # ISO datetime string
    scheduled_end: str     # ISO datetime string
    priority: Literal["CRITICAL", "HIGH", "NORMAL", "LOW"] = "NORMAL"
    description: Optional[str] = None
    assigned_crew: list[str] = []


class CreateScheduleResponse(BaseModel):
    operation_id: str
    conflicts: list[dict[str, Any]] = []
    created: bool


class ScheduledOperationResponse(BaseModel):
    operation_id: str
    title: str
    operation_type: str
    pipe_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    status: str
    priority: str


class DayScheduleEntry(BaseModel):
    date: str
    weekday: int  # Monday=0 .. Sunday=6
    is_holiday: bool
    holiday_name: Optional[str] = None
    is_blackout: bool
    is_working_day: bool
    operations: list[dict[str, Any]] = []


class MonthScheduleResponse(BaseModel):
    year: int
    month: int
    holiday_data_available: bool
    days: list[DayScheduleEntry]


class HealthResponse(BaseModel):
    status: Literal["OK", "DEGRADED", "DOWN"]
    neo4j: str
    chromadb: str
    sqlite: str
    azure_openai: str
    timestamp: str


# ── Field Crew Interface models ────────────────────────────────────────────────

class ChecklistStepResponse(BaseModel):
    step_number: int
    phase: str                       # isolation | alternate_feed | re_feed | notify | verify
    description: str
    valve_id: Optional[str] = None
    pipe_id: Optional[str] = None
    status: str = "PENDING"          # PENDING | DONE | FLAGGED
    flag_note: Optional[str] = None
    updated_at: Optional[str] = None


class CrewOperationResponse(BaseModel):
    operation_id: str
    title: str
    operation_type: str
    pipe_id: Optional[str] = None
    pipe_road: Optional[str] = None  # from sop_chain
    scheduled_start: str
    scheduled_end: str
    status: str
    operation_class: str = "PLANNED"
    checklist: list[ChecklistStepResponse] = []
    completion: dict[str, Any] = {}
    crew_link: str = ""              # the full /crew/{operation_id} URL


class UpdateStepRequest(BaseModel):
    status: Literal["PENDING", "DONE", "FLAGGED"]
    flag_note: Optional[str] = None


class CrewNoteRequest(BaseModel):
    message: str
    step_number: Optional[int] = None


class CrewNoteResponse(BaseModel):
    id: int
    step_number: Optional[int] = None
    message: str
    created_at: str


class CrewProgressResponse(BaseModel):
    operation_id: str
    total: int
    done: int
    flagged: int
    pending: int
    percent_complete: float
