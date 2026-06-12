import time
import mlflow
from fastapi import APIRouter, BackgroundTasks
from schemas.api_models import ChatRequest, ChatResponse
from agents.orchestrator import invoke_graph
from tools.calendar_tools import log_chat_session
from evaluation.auto_eval import AutoEvaluator

router = APIRouter()
_evaluator = AutoEvaluator()


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
    final_response = result.get("final_response") or "I could not process your request. Please try again."
    plan = result.get("operations_plan")
    feasibility = plan.get("feasibility_verdict") if plan else None

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
        processing_time_ms=elapsed_ms,
    )
