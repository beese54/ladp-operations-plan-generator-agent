import time
from datetime import datetime
from typing import Optional
import mlflow
from fastapi import APIRouter, BackgroundTasks
from schemas.api_models import ChatRequest, ChatResponse
from agents.orchestrator import invoke_graph
from tools.calendar_tools import get_operation, log_chat_session
from evaluation.auto_eval import AutoEvaluator

router = APIRouter()
_evaluator = AutoEvaluator()


def _year_month(iso_value: str) -> dict[str, int]:
    d = datetime.fromisoformat(iso_value)
    return {"year": d.year, "month": d.month}


def _schedule_view_for(result: dict) -> Optional[dict[str, int]]:
    """Non-null exactly on a turn the left-panel calendar should switch to:
    a schedule-listing question was answered, or a booking was just
    committed. Uses the booking's ACTUAL scheduled_start (a fresh DB lookup),
    not target_date — if the scheduling engine auto-shifted the booking off
    a blackout/conflict date, target_date would still hold the operator's
    original ask, not where it actually landed."""
    if result.get("operation_type") == "SCHEDULE_QUERY" and result.get("target_date"):
        return _year_month(result["target_date"])
    booked_id = result.get("booked_operation_id")
    if booked_id:
        booked = get_operation(booked_id)
        if booked and booked.get("scheduled_start"):
            return _year_month(booked["scheduled_start"])
    return None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks) -> ChatResponse:
    t0 = time.monotonic()

    # Wrap the full request in a named MLflow run so all child spans are grouped
    with mlflow.start_run(
        run_name=f"chat-{(request.session_id or 'anon')[:8]}",
        tags={
            "session_id": request.session_id or "",
            "source": "api",
        },
    ):
        result = invoke_graph(request.message, session_id=request.session_id)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # Non-blocking: log metrics after response is sent
        background_tasks.add_task(
            _evaluator.log_request,
            request.session_id or "anon",
            request.message,
            result,
            float(elapsed_ms),
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # The graph may pause on a human-in-the-loop interrupt() to ask for a
    # missing pipe_id / date / time window. LangGraph surfaces this as an
    # "__interrupt__" key on the returned state — the clarification question is
    # the response to show, not an error.
    awaiting_clarification = False
    interrupts = result.get("__interrupt__")
    if interrupts:
        awaiting_clarification = True
        payload = getattr(interrupts[0], "value", {}) or {}
        final_response = payload.get(
            "clarification_question",
            "Could you provide a bit more detail so I can continue?",
        )
    else:
        final_response = result.get("final_response") or "I could not process your request. Please try again."

    plan = result.get("operations_plan")
    feasibility = plan.get("feasibility_verdict") if plan else None
    schedule_view = _schedule_view_for(result)

    # Audit log
    try:
        log_chat_session(
            session_id=request.session_id,
            user_query=request.message,
            pipe_id=result.get("pipe_id"),
            target_date=result.get("target_date"),
            feasibility=feasibility,
            plan_generated=plan is not None,
            response_summary=final_response[:500],
        )
    except Exception:
        pass  # Non-fatal; don't surface logging errors to user

    return ChatResponse(
        session_id=request.session_id,
        message=final_response,
        feasibility=feasibility,
        pipe_id=result.get("pipe_id"),
        target_date=result.get("target_date"),
        has_plan=plan is not None,
        operations_plan=dict(plan) if plan else None,
        awaiting_clarification=awaiting_clarification,
        booked_operation_id=result.get("booked_operation_id"),
        processing_time_ms=elapsed_ms,
        schedule_view=schedule_view,
        answer_path=result.get("answer_path"),
        retrieved_chunks=result.get("retrieved_chunks"),
    )
