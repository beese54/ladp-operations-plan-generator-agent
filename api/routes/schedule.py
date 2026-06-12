from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from schemas.api_models import CreateScheduleRequest, CreateScheduleResponse, ScheduledOperationResponse
from tools.calendar_tools import (
    check_pipe_schedule_conflicts,
    create_scheduled_operation,
    cancel_operation,
    get_upcoming_operations,
)

router = APIRouter()


@router.get("/schedule", response_model=list[ScheduledOperationResponse])
async def list_schedule(
    pipe_id: Optional[str] = Query(None),
    days_ahead: int = Query(30, ge=1, le=365),
):
    rows = get_upcoming_operations(pipe_id=pipe_id, days_ahead=days_ahead)
    return [
        ScheduledOperationResponse(
            operation_id=r["operation_id"],
            title=r["title"],
            operation_type=r["operation_type"],
            pipe_id=r.get("pipe_id"),
            scheduled_start=r["scheduled_start"],
            scheduled_end=r["scheduled_end"],
            status=r["status"],
            priority=r["priority"],
        )
        for r in rows
    ]


@router.post("/schedule", response_model=CreateScheduleResponse)
async def create_schedule(req: CreateScheduleRequest) -> CreateScheduleResponse:
    # Check for conflicts before creating
    conflicts = []
    if req.pipe_id:
        conflicts = check_pipe_schedule_conflicts(
            req.pipe_id, req.scheduled_start, req.scheduled_end
        )

    blocking = any(c["severity"] == "BLOCKING" for c in conflicts)
    if blocking:
        # Surface conflicts but still allow creation (operator override)
        pass

    op_id = create_scheduled_operation(
        title=req.title,
        operation_type=req.operation_type,
        pipe_id=req.pipe_id or "",
        scheduled_start=req.scheduled_start,
        scheduled_end=req.scheduled_end,
        priority=req.priority,
        description=req.description,
        zone_id=req.zone_id,
        assigned_crew=req.assigned_crew,
    )

    return CreateScheduleResponse(
        operation_id=op_id,
        conflicts=conflicts,
        created=True,
    )


@router.delete("/schedule/{operation_id}")
async def delete_schedule(operation_id: str):
    cancelled = cancel_operation(operation_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found or already closed.")
    return {"operation_id": operation_id, "status": "CANCELLED"}
