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


class HealthResponse(BaseModel):
    status: Literal["OK", "DEGRADED", "DOWN"]
    neo4j: str
    chromadb: str
    sqlite: str
    azure_openai: str
    timestamp: str
