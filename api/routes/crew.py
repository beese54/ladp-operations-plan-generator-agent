"""Field Crew Interface API routes.

GET  /api/v1/crew/{operation_id}              — full operation + checklist (crew page load)
PATCH /api/v1/crew/{operation_id}/steps/{step} — update a step status (PENDING/DONE/FLAGGED)
POST  /api/v1/crew/{operation_id}/notes        — add a complication note
GET  /api/v1/crew/{operation_id}/progress      — completion rate (for ops planner polling)
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from prompts.sop_walkthrough_prompt import build_sop_chain_data
from schemas.api_models import (
    ChecklistStepResponse,
    CrewNoteRequest,
    CrewNoteResponse,
    CrewOperationResponse,
    CrewProgressResponse,
    UpdateStepRequest,
)
from tools.calendar_tools import get_operation
from tools.crew_tools import (
    add_crew_note,
    get_checklist_snapshot,
    get_completion_rate,
    get_crew_notes,
    get_full_checklist,
    save_checklist_snapshot,
    update_step_status,
    _chain_to_steps,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_checklist_for(operation_id: str, pipe_id: str) -> list[dict[str, Any]]:
    """Return the full checklist for an operation.

    Strategy:
    1. Try to rebuild live from Neo4j via build_sop_chain_data(pipe_id).
       If successful, re-save the snapshot (idempotent) so it stays fresh.
    2. On any Neo4j failure, fall back to the snapshot stored at booking time.
    3. If neither source has data, return an empty list.
    """
    # Attempt live rebuild
    try:
        chain = build_sop_chain_data(pipe_id)
        save_checklist_snapshot(operation_id, chain)  # idempotent — updates snapshot
        logger.info("Checklist built live from Neo4j for %s", operation_id)
    except Exception as e:
        logger.warning("Neo4j unavailable for crew checklist (%s), using snapshot: %s", operation_id, e)
        chain = None

    # If we have a live chain, merge with stored progress
    if chain is not None:
        from tools.crew_tools import get_checklist_progress
        steps_raw = _chain_to_steps(chain)
        progress = get_checklist_progress(operation_id)
        return [
            {
                **s,
                "status": progress.get(s["step_number"], {}).get("status", "PENDING"),
                "flag_note": progress.get(s["step_number"], {}).get("flag_note"),
                "updated_at": progress.get(s["step_number"], {}).get("updated_at"),
            }
            for s in steps_raw
        ]

    # Fallback to snapshot
    checklist = get_full_checklist(operation_id)
    if not checklist:
        logger.warning("No checklist data available for %s (Neo4j down, no snapshot)", operation_id)
    return checklist


def _crew_link(request: Request, operation_id: str) -> str:
    """Build the absolute crew page URL from the incoming request."""
    base = str(request.base_url).rstrip("/")
    return f"{base}/crew/{operation_id}"


@router.get("/crew/{operation_id}", response_model=CrewOperationResponse)
async def get_crew_operation(operation_id: str, request: Request) -> CrewOperationResponse:
    """Return everything the crew page needs on load:
    operation details, full checklist with progress, and completion stats."""
    op = get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")

    if op.get("status") == "CANCELLED":
        raise HTTPException(status_code=410, detail=f"Operation '{operation_id}' has been cancelled.")

    pipe_id = op.get("pipe_id") or ""
    pipe_road: str | None = None

    checklist_raw = _build_checklist_for(operation_id, pipe_id)

    # Try to get pipe road name from chain if available
    try:
        chain = build_sop_chain_data(pipe_id)
        pipe_road = chain.get("pipe_road_name")
    except Exception:
        pass

    completion = get_completion_rate(operation_id)
    checklist = [ChecklistStepResponse(**s) for s in checklist_raw]

    return CrewOperationResponse(
        operation_id=operation_id,
        title=op.get("title", ""),
        operation_type=op.get("operation_type", ""),
        pipe_id=pipe_id or None,
        pipe_road=pipe_road,
        scheduled_start=op.get("scheduled_start", ""),
        scheduled_end=op.get("scheduled_end", ""),
        status=op.get("status", "PLANNED"),
        operation_class=op.get("operation_class", "PLANNED"),
        checklist=checklist,
        completion=completion,
        crew_link=_crew_link(request, operation_id),
    )


@router.patch("/crew/{operation_id}/steps/{step_number}")
async def update_step(
    operation_id: str,
    step_number: int,
    body: UpdateStepRequest,
) -> dict:
    """Update the status of a single checklist step."""
    op = get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")

    if body.status == "FLAGGED" and not body.flag_note:
        raise HTTPException(status_code=422, detail="flag_note is required when status is FLAGGED.")

    try:
        update_step_status(
            operation_id=operation_id,
            step_number=step_number,
            status=body.status,
            flag_note=body.flag_note,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    completion = get_completion_rate(operation_id)
    return {
        "operation_id": operation_id,
        "step_number": step_number,
        "status": body.status,
        "completion": completion,
    }


@router.get("/crew/{operation_id}/notes", response_model=list[CrewNoteResponse])
async def get_notes(operation_id: str) -> list[CrewNoteResponse]:
    """Return all crew notes for an operation, newest first."""
    op = get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")
    notes = get_crew_notes(operation_id)
    return [
        CrewNoteResponse(
            id=n["id"],
            step_number=n.get("step_number"),
            message=n["message"],
            created_at=n["created_at"],
        )
        for n in notes
    ]


@router.post("/crew/{operation_id}/notes", response_model=CrewNoteResponse)
async def post_crew_note(operation_id: str, body: CrewNoteRequest) -> CrewNoteResponse:
    """Add a complication note or general update from field crew."""
    op = get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")

    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message cannot be empty.")

    note_id = add_crew_note(
        operation_id=operation_id,
        message=body.message.strip(),
        step_number=body.step_number,
    )

    notes = get_crew_notes(operation_id)
    note = next((n for n in notes if n["id"] == note_id), None)
    if note is None:
        raise HTTPException(status_code=500, detail="Note was saved but could not be retrieved.")

    return CrewNoteResponse(
        id=note["id"],
        step_number=note.get("step_number"),
        message=note["message"],
        created_at=note["created_at"],
    )


@router.get("/crew/{operation_id}/progress", response_model=CrewProgressResponse)
async def get_crew_progress(operation_id: str) -> CrewProgressResponse:
    """Completion rate for ops planner polling — lightweight endpoint."""
    op = get_operation(operation_id)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{operation_id}' not found.")

    stats = get_completion_rate(operation_id)
    return CrewProgressResponse(
        operation_id=operation_id,
        **stats,
    )
