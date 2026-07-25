from calendar import monthrange
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from schemas.api_models import (
    CreateScheduleRequest,
    CreateScheduleResponse,
    DayScheduleEntry,
    MonthScheduleResponse,
    ScheduledOperationResponse,
)
from tools.calendar_tools import (
    check_pipe_schedule_conflicts,
    create_scheduled_operation,
    cancel_operation,
    get_active_operations,
    get_upcoming_operations,
)
from tools.scheduling_rules import available_holiday_years, classify_day
from agents.calendar_agent import _operations_in_range

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


@router.get("/schedule/month", response_model=MonthScheduleResponse)
async def get_month_schedule(
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
) -> MonthScheduleResponse:
    """Structured month view for the left-panel calendar: every day of the
    month classified (holiday/blackout/working) plus the operations booked
    on it. Reuses the same active-ops source and month-range logic the
    chat-driven schedule-listing path already relies on."""
    first = date(year, month, 1)
    last_day_num = monthrange(year, month)[1]
    month_iso = first.isoformat()

    existing = get_active_operations()
    touching = _operations_in_range(existing, month_iso, month_iso)
    by_id = {op["operation_id"]: op for op in existing}
    ops_full = [by_id[o["operation_id"]] for o in touching if o["operation_id"] in by_id]

    holiday_years = available_holiday_years()

    days: list[DayScheduleEntry] = []
    for day_num in range(1, last_day_num + 1):
        d = date(year, month, day_num)
        info = classify_day(d)
        day_ops = [
            op for op in ops_full
            if datetime.fromisoformat(op["scheduled_start"]).date() <= d
            and datetime.fromisoformat(op["scheduled_end"]).date() >= d
        ]
        days.append(DayScheduleEntry(
            date=info["date"],
            weekday=d.weekday(),
            is_holiday=info["is_holiday"],
            holiday_name=info["holiday_name"],
            is_blackout=info["is_blackout"],
            is_working_day=info["is_working_day"],
            operations=day_ops,
        ))

    return MonthScheduleResponse(
        year=year,
        month=month,
        holiday_data_available=year in holiday_years,
        days=days,
    )


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
