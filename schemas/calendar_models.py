from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, field_validator


class ScheduledOperation(BaseModel):
    operation_id: str
    title: str
    operation_type: Literal["PLANNED_SHUTDOWN", "MAINTENANCE", "EMERGENCY", "INSPECTION"]
    pipe_id: Optional[str] = None
    valve_ids: list[str] = []
    zone_id: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: datetime
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    status: Literal["PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"] = "PLANNED"
    priority: Literal["CRITICAL", "HIGH", "NORMAL", "LOW"] = "NORMAL"
    description: Optional[str] = None
    assigned_crew: list[str] = []
    created_by: str = "system"

    @field_validator("scheduled_end")
    @classmethod
    def end_after_start(cls, v: datetime, info) -> datetime:
        start = info.data.get("scheduled_start")
        if start and v <= start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return v


class SchedulingConflict(BaseModel):
    new_operation_id: str
    conflicting_op_id: str
    conflict_type: Literal["TIME_OVERLAP", "SHARED_ASSET"]
    severity: Literal["BLOCKING", "WARNING"]
    conflict_detail: str
    resolved: bool = False
    resolution_note: Optional[str] = None


class AffectedConsumer(BaseModel):
    consumer_id: str
    consumer_name: Optional[str] = None
    criticality: Literal["HIGH", "MEDIUM", "LOW"] = "LOW"
    notified_at: Optional[datetime] = None
    notified_via: Optional[str] = None
