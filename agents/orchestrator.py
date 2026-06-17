import json
import logging
from typing import Any
from uuid import uuid4

import mlflow
from mlflow.entities import SpanType
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

from config.settings import get_settings, get_azure_openai_client, get_together_client
from schemas.graph_state import OrchestratorState
from agents.calendar_agent import calendar_agent_node
from agents.neo4j_agent import neo4j_agent_node
from agents.sop_agent import sop_agent_node
from agents.historical_agent import historical_agent_node
from agents.ops_plan_generator import ops_plan_generator_node
from prompts.sop_walkthrough_prompt import format_sop_walkthrough

logger = logging.getLogger(__name__)

# ─── Scope definition for guardrails ─────────────────────────────────────────
_IN_SCOPE_TOPICS = (
    "water network", "pipe", "valve", "tank", "pressure", "flow", "shutdown",
    "isolation", "maintenance", "inspection", "SOP", "operations plan",
    "schedule", "calendar", "junction", "customer", "supply", "bypass",
)

_INTENT_SYSTEM = """You are an intent classifier for a water network operations assistant.
Classify the user's message and extract relevant fields.
Return ONLY a JSON object:
{
  "operation_type": "SHUTDOWN" | "INSPECTION" | "MAINTENANCE" | "GENERAL_QUERY" | "UNKNOWN",
  "pipe_id": "<pipe ID string or null>",
  "target_date": "<ISO date YYYY-MM-DD or null>",
  "scheduled_start": "<ISO datetime YYYY-MM-DDTHH:MM:SS or null>",
  "scheduled_end": "<ISO datetime YYYY-MM-DDTHH:MM:SS or null>",
  "confidence": 0.0
}
Rules:
- SHUTDOWN/INSPECTION/MAINTENANCE: user wants to perform a network operation on a specific pipe.
- GENERAL_QUERY: user is asking a question about the network, SOPs, schedules, or system without requesting a new operation.
- UNKNOWN: message is off-topic or ambiguous.
- Extract pipe_id exactly as stated (e.g. "pipe_151", "P-001").
- If time is given (e.g. "08:00 to 16:00"), populate scheduled_start and scheduled_end combining with target_date.
- If only date given, set scheduled_start and scheduled_end to null.
Return ONLY the JSON object."""

_GENERAL_SYSTEM = """You are a water network operations assistant.
You help operators with questions about the water network, SOPs, scheduling, and operations.
Answer helpfully and concisely using your knowledge. If asked about specific real-time data
(e.g. current pressure values, live valve status), note that they should query the network directly.

SCOPE: Water utility operations only. If asked about anything unrelated to water network management,
politely decline and redirect: "I'm a water network operations assistant and can only help with
topics related to water network management, SOPs, and operations planning."
"""


# ─── Node: Intent Parser ──────────────────────────────────────────────────────
@mlflow.trace(name="intent_parser", span_type=SpanType.AGENT)
def intent_parser_node(state: OrchestratorState) -> dict:
    s = get_settings()
    client = get_azure_openai_client()
    user_query = state.get("user_query_raw", "")

    try:
        response = client.chat.completions.create(
            model=s.azure_openai_chat_deployment_name,
            max_completion_tokens=512,
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM},
                {"role": "user", "content": user_query},
            ],
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model adds them
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        parsed = json.loads(raw)
    except Exception as e:
        logger.error("Intent parser error: %s", e)
        parsed = {"operation_type": "UNKNOWN", "confidence": 0.0}

    return {
        "pipe_id": parsed.get("pipe_id"),
        "target_date": parsed.get("target_date"),
        "scheduled_start": parsed.get("scheduled_start"),
        "scheduled_end": parsed.get("scheduled_end"),
        "operation_type": parsed.get("operation_type", "UNKNOWN"),
        "intent_confidence": float(parsed.get("confidence", 0.0)),
        "agents_completed": [],
        "error_messages": [],
        "clarification_round": state.get("clarification_round", 0),
        "awaiting_clarification": "",
    }


# ─── Node: General Response ───────────────────────────────────────────────────
@mlflow.trace(name="general_response", span_type=SpanType.AGENT)
def general_response_node(state: OrchestratorState) -> dict:
    s = get_settings()
    user_query = state.get("user_query_raw", "")

    # Guardrail: check if in scope
    query_lower = user_query.lower()
    in_scope = any(topic in query_lower for topic in _IN_SCOPE_TOPICS)

    provider = s.agent_providers.get("general_response", "azure")
    try:
        client = get_azure_openai_client() if provider == "azure" else get_together_client()
        model = s.azure_openai_chat_deployment_name if provider == "azure" else s.together_model
        msgs = [{"role": "system", "content": _GENERAL_SYSTEM}]
        if in_scope:
            for m in state.get("messages", [])[-6:]:  # last 3 turns
                msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        msgs.append({"role": "user", "content": user_query})
        response = client.chat.completions.create(
            model=model,
            messages=msgs,
            max_completion_tokens=1024,
            temperature=0.3,
        )
        answer = response.choices[0].message.content or ""
    except Exception as e:
        logger.error("General response error: %s", e)
        answer = "I'm sorry, I encountered an error. Please try again."

    return {
        "final_response": answer,
        "agents_completed": ["general_response"],
    }


# ─── Helper: merge a clarification answer back into the running query ────────
def _merge_clarification(state: OrchestratorState, user_response: Any) -> str:
    """Append the user's clarification answer to the prior query so the intent
    parser re-parses the *full* context (pipe + date + time), not just the
    fragment. Replacing user_query_raw outright would drop slots already known."""
    answer = user_response if isinstance(user_response, str) else str(user_response)
    prior = (state.get("user_query_raw") or "").strip()
    if not prior:
        return answer
    return f"{prior}. {answer}"


# ─── Node: Clarification (missing pipe_id or date) ───────────────────────────
@mlflow.trace(name="clarification", span_type=SpanType.AGENT)
def clarification_node(state: OrchestratorState) -> dict:
    round_num = state.get("clarification_round", 0)
    if round_num >= 2:
        return {
            "final_response": (
                "To generate an operations plan I need: the **pipe ID** (e.g. `pipe_151`) "
                "and the **scheduled date and time window** (e.g. `2026-06-01 08:00 to 16:00`). "
                "Please provide these details."
            ),
            "agents_completed": ["clarification_maxed"],
        }

    missing = []
    if not state.get("pipe_id"):
        missing.append("the **pipe ID** (e.g. `pipe_151`)")
    if not state.get("target_date"):
        missing.append("the **date** for the operation (e.g. `2026-06-01`)")

    question = f"To proceed, could you please provide {' and '.join(missing)}?"

    user_response = interrupt({"clarification_question": question})

    return {
        "user_query_raw": _merge_clarification(state, user_response),
        "clarification_round": round_num + 1,
    }


# ─── Node: Time Clarification (date given, no time) ──────────────────────────
@mlflow.trace(name="time_clarification", span_type=SpanType.AGENT)
def time_clarification_node(state: OrchestratorState) -> dict:
    round_num = state.get("clarification_round", 0)
    date = state.get("target_date", "the requested date")

    if round_num >= 2:
        return {
            "final_response": (
                f"I need the start and end time for the operation on {date}. "
                "For example: `08:00 to 16:00`. Please re-submit with the time included."
            ),
            "agents_completed": ["clarification_maxed"],
        }

    question = (
        f"What start and end time do you require for the operation on **{date}**? "
        f"(e.g. `08:00 to 16:00`)"
    )

    user_response = interrupt({"clarification_question": question})

    return {
        "user_query_raw": _merge_clarification(state, user_response),
        "clarification_round": round_num + 1,
    }


# ─── Node: Orchestrator Response ──────────────────────────────────────────────
@mlflow.trace(name="orchestrator_response", span_type=SpanType.AGENT)
def orchestrator_response_node(state: OrchestratorState) -> dict:
    plan = state.get("operations_plan")
    if not plan:
        return {"final_response": "I was unable to generate an operations plan. Please try again."}

    verdict = plan.get("feasibility_verdict", "CONDITIONAL")
    verdict_emoji = {"FEASIBLE": "✅", "NOT_FEASIBLE": "❌", "CONDITIONAL": "⚠️"}.get(verdict, "")

    lines: list[str] = []

    # Lead with the deterministic SOP sequential logic, then the plan sections below.
    chain = state.get("sop_chain")
    if chain:
        try:
            lines.append(format_sop_walkthrough(chain))
            lines.append("")
        except Exception as e:
            logger.warning("Could not render SOP walkthrough: %s", e)

    lines += [
        f"## Operations Plan — Pipe `{state.get('pipe_id', '')}` | {state.get('target_date', '')}",
        f"\n**Feasibility:** {verdict_emoji} **{verdict}**",
        f"> {plan.get('feasibility_reason', '')}",
        "",
    ]

    if plan.get("safety_warnings"):
        lines.append("### ⚠️ Safety Warnings")
        for w in plan["safety_warnings"]:
            lines.append(f"- {w}")
        lines.append("")

    if plan.get("pre_operation_checks"):
        lines.append("### Pre-Operation Checks")
        for i, c in enumerate(plan["pre_operation_checks"], 1):
            lines.append(f"{i}. {c}")
        lines.append("")

    if plan.get("valve_sequence"):
        lines.append("### Valve Operation Sequence")
        lines.append("| Step | Valve | Location | Action | Notes |")
        lines.append("|------|-------|----------|--------|-------|")
        for v in sorted(plan["valve_sequence"], key=lambda x: x.get("sequence_number", 0)):
            lines.append(
                f"| {v.get('sequence_number')} | `{v.get('valve_id')}` | {v.get('road_name')} "
                f"| **{v.get('action')}** | {v.get('timing_note', '')} |"
            )
        lines.append("")

    if plan.get("affected_consumers_summary"):
        lines.append("### Customer Impact")
        lines.append(plan["affected_consumers_summary"])
        lines.append("")

    if plan.get("notifications_required"):
        lines.append("### Notifications Required")
        for n in plan["notifications_required"]:
            lines.append(f"- {n}")
        lines.append("")

    if plan.get("post_operation_steps"):
        lines.append("### Post-Operation Steps")
        for i, s in enumerate(plan["post_operation_steps"], 1):
            lines.append(f"{i}. {s}")
        lines.append("")

    if plan.get("estimated_duration_hours"):
        lines.append(f"**Estimated Duration:** {plan['estimated_duration_hours']} hours")

    if plan.get("alternative_recommendation"):
        lines.append(f"\n**Alternative Recommendation:** {plan['alternative_recommendation']}")

    return {"final_response": "\n".join(lines)}


# ─── Node: Error Handler ──────────────────────────────────────────────────────
@mlflow.trace(name="error_handler", span_type=SpanType.AGENT)
def error_handler_node(state: OrchestratorState) -> dict:
    errors = state.get("error_messages", [])
    if errors:
        msg = "I encountered the following issue(s):\n" + "\n".join(f"- {e}" for e in errors)
    else:
        msg = "Something went wrong. Please check the pipe ID and try again."
    return {"final_response": msg}


# ─── Routing Functions ────────────────────────────────────────────────────────
def route_after_intent(state: OrchestratorState) -> list | str:
    op_type = state.get("operation_type", "UNKNOWN")
    pipe_id = state.get("pipe_id")
    target_date = state.get("target_date")
    scheduled_start = state.get("scheduled_start")
    scheduled_end = state.get("scheduled_end")

    if op_type in ("GENERAL_QUERY", "UNKNOWN"):
        return "general_response"

    # OPS query — check completeness
    if not pipe_id or not target_date:
        return "clarification"

    if not scheduled_start or not scheduled_end:
        return "time_clarification"

    # Complete — fan out calendar + neo4j in parallel
    return [
        Send("calendar_agent", state),
        Send("neo4j_agent", state),
    ]


def route_after_clarification(state: OrchestratorState) -> str:
    if state.get("agents_completed") and "clarification_maxed" in state["agents_completed"]:
        return END
    return "intent_parser"


def route_after_neo4j(state: OrchestratorState) -> list | str:
    if state.get("topology_context") is None:
        return "error_handler"
    return [
        Send("sop_agent", state),
        Send("historical_agent", state),
    ]


def route_after_plan(state: OrchestratorState) -> str:
    if state.get("operations_plan") is None:
        return "error_handler"
    return "orchestrator_response"


# ─── Graph Builder ────────────────────────────────────────────────────────────
def build_orchestrator_graph():
    graph = StateGraph(OrchestratorState)

    graph.add_node("intent_parser",         intent_parser_node)
    graph.add_node("general_response",      general_response_node)
    graph.add_node("clarification",         clarification_node)
    graph.add_node("time_clarification",    time_clarification_node)
    graph.add_node("calendar_agent",        calendar_agent_node)
    graph.add_node("neo4j_agent",           neo4j_agent_node)
    graph.add_node("sop_agent",             sop_agent_node)
    graph.add_node("historical_agent",      historical_agent_node)
    graph.add_node("ops_plan_generator",    ops_plan_generator_node)
    graph.add_node("orchestrator_response", orchestrator_response_node)
    graph.add_node("error_handler",         error_handler_node)

    graph.add_edge(START, "intent_parser")

    graph.add_conditional_edges(
        "intent_parser",
        route_after_intent,
        ["general_response", "clarification", "time_clarification",
         "calendar_agent", "neo4j_agent"],
    )

    # Clarification loops back to intent parser to re-parse the updated query
    graph.add_conditional_edges(
        "clarification",
        route_after_clarification,
        ["intent_parser", END],
    )
    graph.add_conditional_edges(
        "time_clarification",
        route_after_clarification,
        ["intent_parser", END],
    )

    # After neo4j, fan out sop + historical
    graph.add_conditional_edges(
        "neo4j_agent",
        route_after_neo4j,
        ["sop_agent", "historical_agent", "error_handler"],
    )

    # All three converge at ops_plan_generator
    graph.add_edge("calendar_agent",   "ops_plan_generator")
    graph.add_edge("sop_agent",        "ops_plan_generator")
    graph.add_edge("historical_agent", "ops_plan_generator")

    graph.add_conditional_edges(
        "ops_plan_generator",
        route_after_plan,
        ["orchestrator_response", "error_handler"],
    )

    graph.add_edge("general_response",      END)
    graph.add_edge("orchestrator_response", END)
    graph.add_edge("error_handler",         END)

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# Compiled graph singleton
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_orchestrator_graph()
    return _graph


def invoke_graph(user_message: str, session_id: str | None = None) -> dict[str, Any]:
    """Invoke the orchestrator graph and return the final state."""
    if not session_id:
        session_id = str(uuid4())

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    # If this thread is paused mid-run on a clarification interrupt, the user's
    # message is the answer to that question — resume the graph instead of
    # starting a fresh run (which would discard the pending operation context).
    snapshot = graph.get_state(config)
    if snapshot.next:
        return graph.invoke(Command(resume=user_message), config=config)

    initial_state: OrchestratorState = {
        "messages": [],
        "session_id": session_id,
        "user_query_raw": user_message,
        "pipe_id": None,
        "target_date": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "operation_type": "UNKNOWN",
        "intent_confidence": 0.0,
        "clarification_round": 0,
        "awaiting_clarification": "",
        "calendar_context": None,
        "topology_context": None,
        "sop_context": None,
        "historical_context": None,
        "operations_plan": None,
        "sop_chain": None,
        "agents_completed": [],
        "error_messages": [],
        "final_response": None,
    }

    result = graph.invoke(initial_state, config=config)
    return result
