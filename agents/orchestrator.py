import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import mlflow
from mlflow.entities import SpanType
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver

from config.settings import get_settings, get_azure_openai_client, get_together_client
from schemas.graph_state import OrchestratorState
from agents.calendar_agent import calendar_agent_node, _operations_in_month
from agents.neo4j_agent import neo4j_agent_node
from agents.sop_agent import sop_agent_node
from agents.historical_agent import historical_agent_node
from agents.ops_plan_generator import ops_plan_generator_node
from prompts.sop_walkthrough_prompt import format_sop_walkthrough_table
from tools.calendar_tools import create_scheduled_operation, reschedule_operation, get_active_operations
from tools import scheduling_rules as sr
from tools import valve_operation_rules as vor

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
  "operation_class": "PLANNED" | "EMERGENCY" | null,
  "confidence": 0.0
}
Rules:
- SHUTDOWN/INSPECTION/MAINTENANCE: user wants to perform a network operation on a specific pipe.
- GENERAL_QUERY: user is asking a question about the network, SOPs, schedules, or system without requesting a new operation.
- UNKNOWN: message is off-topic or ambiguous.
- Extract pipe_id exactly as stated (e.g. "pipe_151", "P-001").
- target_date is the requested START date of the operation. The system computes the
  end date itself from the operation's effort, so do NOT extract any time of day or
  end date.
- operation_class: "EMERGENCY" if the user signals urgency (emergency, urgent, burst,
  leak, main break, pipe failure); "PLANNED" if they say planned/scheduled/routine;
  otherwise null.
- Resolve relative dates (today, tomorrow, next Monday) against the current date below.
- Dates may be written day-first, e.g. "16-07-26" or "16/07/2026" means DD-MM-YY(YY).
  Interpret short numeric dates day-first and still output ISO YYYY-MM-DD.
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
    system_content = f"{_INTENT_SYSTEM}\n\nCurrent date: {datetime.now().date().isoformat()}"

    # Include recent transcript so follow-ups ("make it Monday instead") resolve
    # against the prior turn's pipe/date/class.
    msgs = [{"role": "system", "content": system_content}]
    for m in state.get("messages", [])[-4:]:
        msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    msgs.append({"role": "user", "content": user_query})

    try:
        response = client.chat.completions.create(
            model=s.azure_openai_chat_deployment_name,
            max_completion_tokens=512,
            messages=msgs,
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

    # Preserve a class already supplied in an earlier turn so re-parsing a
    # clarification answer never drops it.
    op_class = parsed.get("operation_class") or state.get("operation_class")
    if isinstance(op_class, str):
        op_class = op_class.upper()

    return {
        "pipe_id": parsed.get("pipe_id") or state.get("pipe_id"),
        "target_date": parsed.get("target_date") or state.get("target_date"),
        "operation_class": op_class,
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


# Up to 3 slots (pipe, start date, planned/emergency) may each need a turn.
MAX_CLARIFICATION_ROUNDS = 4


# ─── Helper: merge a clarification answer back into the running query ────────
def _merge_clarification(state: OrchestratorState, user_response: Any) -> str:
    """Append the user's clarification answer to the prior query so the intent
    parser re-parses the *full* context (pipe + start date + class), not just the
    fragment. Replacing user_query_raw outright would drop slots already known."""
    answer = user_response if isinstance(user_response, str) else str(user_response)
    prior = (state.get("user_query_raw") or "").strip()
    if not prior:
        return answer
    return f"{prior}. {answer}"


# ─── Node: Clarification (slot-aware, one missing slot at a time) ────────────
def _is_near_term(target_date: str | None) -> bool:
    """True if the requested start date is today or tomorrow (short notice)."""
    if not target_date:
        return False
    try:
        d = datetime.fromisoformat(target_date).date()
    except (ValueError, TypeError):
        return False
    today = datetime.now().date()
    return d in (today, today + timedelta(days=1))


def _example_date() -> str:
    """Today's date in DD-MM-YY, used as the example in clarification prompts."""
    return datetime.now().strftime("%d-%m-%y")


def _next_clarification_slot(state: OrchestratorState) -> tuple[str, str]:
    """First missing slot (pipe_id -> date -> operation_class) and its question.

    When the class is still unknown but the start date is today/tomorrow, the
    question proactively asks whether it's an emergency — short notice usually
    means urgency.
    """
    if not state.get("pipe_id"):
        return "pipe_id", "Which pipe is this operation on? (e.g. `pipe_151`)"
    if not state.get("target_date"):
        return "date", f"What date should the operation start? (DD-MM-YY, e.g. `{_example_date()}`)"
    if _is_near_term(state.get("target_date")):
        return "operation_class", (
            "That's very short notice — is this an **emergency** shutdown? "
            "Reply `emergency`, or `planned` if it can be scheduled normally."
        )
    return "operation_class", "Is this a **planned** operation or an **emergency**?"


def _month_schedule_preview(target_date: str | None) -> str:
    """A look at what's already booked in the requested month, shown the moment
    the operator gives the date (no clash flags yet — the window isn't sized)."""
    try:
        label = datetime.fromisoformat(target_date).strftime("%B %Y")
    except (ValueError, TypeError):
        return ""
    try:
        ops = _operations_in_month(get_active_operations(), target_date, "", "")
    except Exception as e:
        logger.warning("Could not load month schedule preview: %s", e)
        return ""
    if not ops:
        return f"📅 Nothing else is scheduled in **{label}** — the calendar is clear."
    rows = ["| Operation | Pipe | When |", "|-----------|------|------|"]
    for o in sorted(ops, key=lambda x: x.get("scheduled_start", "")):
        rows.append(f"| {o.get('operation_id', '')} | `{o.get('pipe_id', '')}` | "
                    f"{_fmt_dt(o.get('scheduled_start'))} → {_fmt_dt(o.get('scheduled_end'))} |")
    return f"📅 **Already scheduled in {label}:**\n\n" + "\n".join(rows)


@mlflow.trace(name="clarification", span_type=SpanType.AGENT)
def clarification_node(state: OrchestratorState) -> dict:
    round_num = state.get("clarification_round", 0)
    if round_num >= MAX_CLARIFICATION_ROUNDS:
        return {
            "final_response": (
                "To plan an operation I need three things: the **pipe ID** "
                f"(e.g. `pipe_151`), the **start date** (DD-MM-YY, e.g. `{_example_date()}`), and "
                "whether it is a **planned** operation or an **emergency**. "
                "Please provide these and try again."
            ),
            "agents_completed": ["clarification_maxed"],
        }

    slot, question = _next_clarification_slot(state)
    # The date is now known and we're about to ask planned/emergency — show the
    # month's existing schedule first for a holistic view.
    if slot == "operation_class":
        preview = _month_schedule_preview(state.get("target_date"))
        if preview:
            question = f"{preview}\n\n{question}"
    user_response = interrupt({"clarification_question": question})

    return {
        "user_query_raw": _merge_clarification(state, user_response),
        "clarification_round": round_num + 1,
        "awaiting_clarification": slot,
    }


# ─── Node: Orchestrator Response ──────────────────────────────────────────────
def _fmt_dt(iso: str) -> str:
    """'2026-06-19T08:00:00' -> '2026-06-19 08:00'."""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso or ""


def _format_scheduling_section(state: OrchestratorState) -> list[str]:
    """Render the deterministic scheduling assessment from calendar_context."""
    cal = state.get("calendar_context") or {}
    op_class = (cal.get("operation_class") or "PLANNED").upper()
    lines: list[str] = []

    if op_class == "EMERGENCY":
        proposals = state.get("schedule_proposals") or []
        lines.append("### 🚨 Emergency Scheduling")
        lines.append("Emergency shutdown — scheduling rules bypassed; this operation takes priority.")
        conflicts = cal.get("conflicting_emergencies") or []
        if conflicts:
            ids = ", ".join(f"`{c.get('operation_id', '')}`" for c in conflicts)
            lines.append(f"⚠️ Overlaps existing emergency {ids} — you'll be asked which runs first.")
        if proposals:
            lines.append("\nThe following planned operations are displaced and need rescheduling:")
            lines.append("\n| Operation | Pipe | Was | Proposed new slot |")
            lines.append("|-----------|------|-----|-------------------|")
            for p in proposals:
                lines.append(
                    f"| {p['operation_id']} | `{p.get('pipe_id','')}` | "
                    f"{_fmt_dt(p['old_start'])} → {_fmt_dt(p['old_end'])} | "
                    f"**{_fmt_dt(p['proposed_start'])} → {_fmt_dt(p['proposed_end'])}** |"
                )
            lines.append("")
        else:
            lines.append("No planned operations are displaced by this window.\n")
        return lines

    # PLANNED
    violations = cal.get("rule_violations") or []
    if violations:
        lines.append("### 🗓️ Scheduling — Rule Violations")
        for v in violations:
            lines.append(f"- ❌ {v}")
        suggested = cal.get("suggested_start")
        if suggested:
            lines.append(f"\n**Suggested next valid start:** {_fmt_dt(suggested)}")
        lines.append("")
    elif cal.get("is_feasible_date"):
        lines.append("### 🗓️ Scheduling")
        lines.append("✅ Requested window satisfies all scheduling rules (holiday "
                     "blackout, working-day gap, no Friday start).\n")
    return lines


@mlflow.trace(name="orchestrator_response", span_type=SpanType.AGENT)
def orchestrator_response_node(state: OrchestratorState) -> dict:
    plan = state.get("operations_plan")
    if not plan:
        return {"final_response": "I was unable to generate an operations plan. Please try again."}

    pipe_id = state.get("pipe_id", "")
    cal = state.get("calendar_context") or {}
    lines: list[str] = []

    # Conversational summary. The full step-by-step walkthrough (steps 1-12) is
    # kept in state and served on request ("show the steps") rather than dumped.
    chain = state.get("sop_chain")
    if chain:
        try:
            n_actions = len(vor.chain_valve_actions(chain))
            lines.append(
                f"I've worked through the steps to isolate `{pipe_id}` — "
                f"**{n_actions} valve operations** in the shutdown sequence."
            )
        except Exception as e:
            logger.warning("Could not size SOP chain: %s", e)
            lines.append(f"I've worked through the steps to isolate `{pipe_id}`.")

    # System-computed window + effort.
    cs, ce = state.get("scheduled_start"), state.get("scheduled_end")
    duration = cal.get("estimated_duration_hours") or plan.get("estimated_duration_hours")
    wd = cal.get("working_days_count")
    if cs and ce:
        span = f" — {wd} working day{'s' if (wd or 0) != 1 else ''}" if wd else ""
        effort = f", ~{float(duration):.1f} h of valve work" if duration else ""
        lines.append(f"\n📅 **Proposed slot:** {_fmt_dt(cs)} → {_fmt_dt(ce)}{span}{effort}.")

    # Conflicts / scheduling assessment, conversationally.
    pipe_conflicts = cal.get("conflicts") or []
    if pipe_conflicts:
        lines.append("\n⚠️ This clashes with an existing operation on the same pipe:")
        for c in pipe_conflicts:
            lines.append(
                f"- {c.get('title', 'scheduled operation')} "
                f"({_fmt_dt(c.get('scheduled_start'))} → {_fmt_dt(c.get('scheduled_end'))})"
            )

    sched = _format_scheduling_section(state)
    if sched:
        lines.append("")
        lines += sched

    # Holistic month view — what's already on the calendar for the requested month.
    month_ops = cal.get("month_operations")
    if state.get("scheduled_start") and month_ops is not None:
        try:
            label = datetime.fromisoformat(state.get("target_date")).strftime("%B %Y")
        except (ValueError, TypeError):
            label = "that month"
        if month_ops:
            lines.append(f"\n#### 📅 Already scheduled in {label}")
            lines.append("| Operation | Pipe | When | Clash |")
            lines.append("|-----------|------|------|-------|")
            for o in sorted(month_ops, key=lambda x: x.get("scheduled_start", "")):
                clash = "⚠️ **clash**" if o.get("clash") else "—"
                lines.append(
                    f"| {o.get('operation_id', '')} | `{o.get('pipe_id', '')}` | "
                    f"{_fmt_dt(o.get('scheduled_start'))} → {_fmt_dt(o.get('scheduled_end'))} | {clash} |"
                )
        else:
            lines.append(f"\n📅 Nothing else is scheduled in {label} — the calendar is clear.")

    # One-line customer impact (full safety/checks detail stays in the plan object).
    if plan.get("affected_consumers_summary"):
        lines.append(f"👥 {plan['affected_consumers_summary']}")

    if chain:
        lines.append('\n_Ask me to **"show the steps"** for the full isolation walkthrough._')

    return {"final_response": "\n".join(lines)}


# ─── Node: Booking Gate (HITL confirm, then write to the calendar) ───────────
_AFFIRMATIVE_WORDS = {"confirm", "yes", "y", "ok", "okay", "book", "proceed", "sure", "go"}


def _is_affirmative(answer: Any) -> bool:
    """True only on a clear yes — anything ambiguous declines (never books by accident)."""
    text = (answer if isinstance(answer, str) else str(answer)).strip().lower()
    first = text.split()[0] if text.split() else ""
    return first in _AFFIRMATIVE_WORDS


def _window_to_offer(state: OrchestratorState):
    """Return (start_iso, end_iso, prompt) for the bookable window, or None."""
    start = state.get("scheduled_start")
    end = state.get("scheduled_end")
    if not start or not end:
        return None

    cal = state.get("calendar_context") or {}
    op_class = (state.get("operation_class") or "PLANNED").upper()
    pipe_id = state.get("pipe_id", "")

    if op_class == "EMERGENCY":
        prompt = (
            f"**Confirm this EMERGENCY booking** for `{pipe_id}` "
            f"{_fmt_dt(start)} → {_fmt_dt(end)}? Displaced operations will be "
            f"rescheduled as shown above. Reply `confirm` or `cancel`."
        )
        return start, end, prompt

    # PLANNED — offer the requested window if valid, else the next valid slot.
    if cal.get("is_feasible_date") and not cal.get("blocking_conflict"):
        prompt = (
            f"**Confirm booking** for `{pipe_id}` {_fmt_dt(start)} → {_fmt_dt(end)}? "
            f"Reply `confirm` or `cancel`."
        )
        return start, end, prompt

    suggested = cal.get("suggested_start")
    if suggested:
        duration = cal.get("estimated_duration_hours") or 0.0
        s_dt, e_dt, _days = sr.layout_working_window(suggested[:10], duration)
        prompt = (
            f"The requested window isn't valid. **Book `{pipe_id}` for the next valid "
            f"slot, {_fmt_dt(s_dt.isoformat())} → {_fmt_dt(e_dt.isoformat())}, instead?** "
            f"Reply `confirm` or `cancel`."
        )
        return s_dt.isoformat(), e_dt.isoformat(), prompt

    return None


def _commit_booking(state: OrchestratorState, answer: Any, start: str, end: str) -> dict:
    if not _is_affirmative(answer):
        return {"final_response": "Understood — I haven't booked anything. "
                                  "Just ask again whenever you're ready."}

    op_class = (state.get("operation_class") or "PLANNED").upper()
    pipe_id = state.get("pipe_id", "")
    op_type = state.get("operation_type", "SHUTDOWN")
    valves = (state.get("sop_chain") or {}).get("shutdown_valves") or []

    op_id = create_scheduled_operation(
        title=f"{op_class.title()} {op_type.lower()} — {pipe_id}",
        operation_type=op_type,
        pipe_id=pipe_id,
        scheduled_start=start,
        scheduled_end=end,
        priority="HIGH" if op_class == "EMERGENCY" else "NORMAL",
        valve_ids=valves,
        operation_class=op_class,
        created_by="chat",
    )

    lines = [f"✅ Booked **{op_id}** — `{pipe_id}` {_fmt_dt(start)} → {_fmt_dt(end)}."]
    if op_class == "EMERGENCY":
        for p in state.get("schedule_proposals") or []:
            if reschedule_operation(p["operation_id"], p["proposed_start"], p["proposed_end"]):
                lines.append(
                    f"↪ Rescheduled {p['operation_id']} → "
                    f"{_fmt_dt(p['proposed_start'])} → {_fmt_dt(p['proposed_end'])}."
                )

    return {"final_response": "\n".join(lines), "booked_operation_id": op_id}


# ── Emergency-vs-emergency: operator decides which runs first ────────────────
def _emergency_priority_question(state: OrchestratorState, conflicts: list[dict]) -> str:
    pipe_id = state.get("pipe_id", "")
    start, end = state.get("scheduled_start"), state.get("scheduled_end")
    rows = [
        "### ⚠️ Two emergencies coincide",
        "Both bypass scheduling rules, so you decide which runs first:",
        "",
        "| Choice | Operation | Pipe | Window |",
        "|--------|-----------|------|--------|",
        f"| `new` | this request | `{pipe_id}` | {_fmt_dt(start)} → {_fmt_dt(end)} |",
    ]
    for c in conflicts:
        rows.append(
            f"| `{c.get('operation_id', '')}` | {c.get('operation_id', '')} | "
            f"`{c.get('pipe_id', '')}` | {_fmt_dt(c.get('scheduled_start'))} → "
            f"{_fmt_dt(c.get('scheduled_end'))} |"
        )
    ids = ", ".join(f"`{c.get('operation_id', '')}`" for c in conflicts)
    rows.append("")
    rows.append(
        f"Which runs first? Reply `new` to run this request first (the other moves to "
        f"right after), {ids} to run that one first, or `cancel`."
    )
    return "\n".join(rows)


def _resolve_emergency_priority(answer: Any, conflicts: list[dict]):
    """-> 'new' | <op_id> | None (cancel / unrecognised => safe no-op)."""
    text = (answer if isinstance(answer, str) else str(answer)).strip().lower()
    if not text or text.split()[0] in {"cancel", "no", "abort", "stop"}:
        return None
    if "new" in text or "this" in text or "mine" in text:
        return "new"
    for c in conflicts:
        oid = str(c.get("operation_id", "")).lower()
        if oid and oid in text:
            return c.get("operation_id")
    return None


def _commit_emergency_priority(state: OrchestratorState, choice, conflicts: list[dict]) -> dict:
    if choice is None:
        return {"final_response": "Understood — I haven't booked anything. Tell me which "
                "operation should run first (`new` or the operation ID) when you're ready."}

    pipe_id = state.get("pipe_id", "")
    op_type = state.get("operation_type", "SHUTDOWN")
    valves = (state.get("sop_chain") or {}).get("shutdown_valves") or []
    cal = state.get("calendar_context") or {}
    duration = cal.get("estimated_duration_hours") or sr.estimate_duration_hours(2)

    if choice == "new":
        book_start, book_end = state.get("scheduled_start"), state.get("scheduled_end")
    else:  # the chosen existing emergency keeps its slot; this op runs after it
        chosen = next((c for c in conflicts if c.get("operation_id") == choice), None)
        after = datetime.fromisoformat(chosen["scheduled_end"]).date() + timedelta(days=1)
        s_dt, e_dt, _ = sr.layout_working_window(after, duration)
        book_start, book_end = s_dt.isoformat(), e_dt.isoformat()

    op_id = create_scheduled_operation(
        title=f"Emergency {op_type.lower()} — {pipe_id}",
        operation_type=op_type, pipe_id=pipe_id,
        scheduled_start=book_start, scheduled_end=book_end,
        priority="HIGH", valve_ids=valves, operation_class="EMERGENCY", created_by="chat",
    )
    lines = [f"✅ Booked **{op_id}** — `{pipe_id}` {_fmt_dt(book_start)} → {_fmt_dt(book_end)}."]

    if choice == "new":
        cursor = datetime.fromisoformat(book_end).date() + timedelta(days=1)
        for c in conflicts:
            hours = sr.window_working_hours(c["scheduled_start"], c["scheduled_end"])
            s_dt, e_dt, _ = sr.layout_working_window(cursor, hours)
            if reschedule_operation(c["operation_id"], s_dt.isoformat(), e_dt.isoformat()):
                lines.append(f"↪ Moved {c['operation_id']} → "
                             f"{_fmt_dt(s_dt.isoformat())} → {_fmt_dt(e_dt.isoformat())}.")
            cursor = e_dt.date() + timedelta(days=1)
    else:
        lines.append(f"`{choice}` keeps its slot; this operation is scheduled right after it.")

    # Any displaced PLANNED ops still get rebooked.
    for p in state.get("schedule_proposals") or []:
        if reschedule_operation(p["operation_id"], p["proposed_start"], p["proposed_end"]):
            lines.append(f"↪ Rescheduled {p['operation_id']} → "
                         f"{_fmt_dt(p['proposed_start'])} → {_fmt_dt(p['proposed_end'])}.")

    return {"final_response": "\n".join(lines), "booked_operation_id": op_id}


@mlflow.trace(name="booking_gate", span_type=SpanType.AGENT)
def booking_gate_node(state: OrchestratorState) -> dict:
    """Pause for operator confirmation, then persist the operation (HITL write gate).

    When the op is an emergency that overlaps another emergency, the gate instead
    asks which runs first and auto-sequences the other (the choice is the confirm).
    """
    cal = state.get("calendar_context") or {}
    op_class = (state.get("operation_class") or "PLANNED").upper()
    conflicts = cal.get("conflicting_emergencies") or []

    if op_class == "EMERGENCY" and conflicts and state.get("scheduled_start"):
        question = ((state.get("final_response") or "") + "\n\n---\n"
                    + _emergency_priority_question(state, conflicts))
        answer = interrupt({"clarification_question": question})
        choice = _resolve_emergency_priority(answer, conflicts)
        return _commit_emergency_priority(state, choice, conflicts)

    offer = _window_to_offer(state)
    if offer is None:
        return {}  # nothing bookable — the plan has already been shown

    start, end, prompt = offer
    answer = interrupt({"clarification_question": (state.get("final_response") or "") + f"\n\n---\n{prompt}"})
    return _commit_booking(state, answer, start, end)


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
def route_after_intent(state: OrchestratorState) -> str:
    op_type = state.get("operation_type", "UNKNOWN")

    if op_type in ("GENERAL_QUERY", "UNKNOWN"):
        return "general_response"

    # OPS query — require pipe, start date, and planned/emergency before proceeding.
    if not state.get("pipe_id") or not state.get("target_date") or not state.get("operation_class"):
        return "clarification"

    # Complete — Neo4j first; it produces the topology + shutdown chain the
    # calendar agent needs to size the operation's working-day window.
    return "neo4j_agent"


def route_after_clarification(state: OrchestratorState) -> str:
    if state.get("agents_completed") and "clarification_maxed" in state["agents_completed"]:
        return END
    return "intent_parser"


def route_after_neo4j(state: OrchestratorState) -> list | str:
    if state.get("topology_context") is None:
        return "error_handler"
    # Calendar joins the fan-out here (not in parallel with neo4j) because it
    # sizes the window from the shutdown chain neo4j just produced.
    return [
        Send("calendar_agent", state),
        Send("sop_agent", state),
        Send("historical_agent", state),
    ]


def route_after_plan(state: OrchestratorState) -> str:
    if state.get("operations_plan") is None:
        return "error_handler"
    return "orchestrator_response"


# ─── Graph Builder ────────────────────────────────────────────────────────────
# Durable checkpoint store so session context (slot-filling, pending bookings,
# transcript) survives a backend restart. Sits alongside calendar.db.
CHECKPOINT_DB_PATH = "./data/checkpoints.db"


def _default_checkpointer() -> SqliteSaver:
    Path(CHECKPOINT_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CHECKPOINT_DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def build_orchestrator_graph(checkpointer=None):
    graph = StateGraph(OrchestratorState)

    graph.add_node("intent_parser",         intent_parser_node)
    graph.add_node("general_response",      general_response_node)
    graph.add_node("clarification",         clarification_node)
    graph.add_node("calendar_agent",        calendar_agent_node)
    graph.add_node("neo4j_agent",           neo4j_agent_node)
    graph.add_node("sop_agent",             sop_agent_node)
    graph.add_node("historical_agent",      historical_agent_node)
    graph.add_node("ops_plan_generator",    ops_plan_generator_node)
    graph.add_node("orchestrator_response", orchestrator_response_node)
    graph.add_node("booking_gate",          booking_gate_node)
    graph.add_node("error_handler",         error_handler_node)

    graph.add_edge(START, "intent_parser")

    graph.add_conditional_edges(
        "intent_parser",
        route_after_intent,
        ["general_response", "clarification", "neo4j_agent"],
    )

    # Clarification loops back to intent parser to re-parse the updated query
    graph.add_conditional_edges(
        "clarification",
        route_after_clarification,
        ["intent_parser", END],
    )

    # After neo4j, fan out calendar + sop + historical
    graph.add_conditional_edges(
        "neo4j_agent",
        route_after_neo4j,
        ["calendar_agent", "sop_agent", "historical_agent", "error_handler"],
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

    # After the plan is rendered, pause for booking confirmation (HITL write gate).
    graph.add_edge("orchestrator_response", "booking_gate")
    graph.add_edge("booking_gate",          END)

    graph.add_edge("general_response",      END)
    graph.add_edge("error_handler",         END)

    return graph.compile(checkpointer=checkpointer or _default_checkpointer())


# Compiled graph singleton
_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_orchestrator_graph()
    return _graph


_STEPS_REQUEST_VERBS = ("show", "see", "view", "list", "what are", "what's", "give me", "display", "full", "detail")
_STEPS_REQUEST_NOUNS = ("step", "procedure", "walkthrough", "walk through", "isolation sequence", "sop")


def _is_steps_request(message: str) -> bool:
    """Detect a request to see the stored isolation walkthrough."""
    m = (message or "").lower()
    return any(v in m for v in _STEPS_REQUEST_VERBS) and any(n in m for n in _STEPS_REQUEST_NOUNS)


def _assistant_text(result: dict[str, Any]) -> str:
    """The reply shown to the user this turn — the interrupt question if paused,
    otherwise the final response."""
    interrupts = result.get("__interrupt__")
    if interrupts:
        try:
            return interrupts[0].value.get("clarification_question", "") or ""
        except (AttributeError, IndexError):
            return ""
    return result.get("final_response") or ""


def _record_turn(graph, config: dict, user_text: str, assistant_text: str) -> None:
    """Append the user + assistant turn to the session transcript. Uses
    update_state (HITL-safe — preserves any pending interrupt); never fatal."""
    try:
        graph.update_state(config, {"messages": [
            {"role": "user", "content": user_text or ""},
            {"role": "assistant", "content": assistant_text or ""},
        ]})
    except Exception as e:
        logger.warning("Could not record conversation turn: %s", e)


def invoke_graph(user_message: str, session_id: str | None = None) -> dict[str, Any]:
    """Invoke the orchestrator graph and return the final state."""
    if not session_id:
        session_id = str(uuid4())

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    snapshot = graph.get_state(config)

    # Serve the stored step-by-step isolation walkthrough on request. Read-only:
    # it does not start a new operation or disturb a pending interrupt, so a later
    # "confirm" still resumes a paused booking.
    if _is_steps_request(user_message):
        chain = (snapshot.values or {}).get("sop_chain")
        if chain:
            text = format_sop_walkthrough_table(chain)
        else:
            text = ("I don't have an isolation procedure stored yet — ask me about a "
                    "pipe shutdown first, then I can walk you through the steps.")
        _record_turn(graph, config, user_message, text)
        return {"final_response": text, "pipe_id": (snapshot.values or {}).get("pipe_id")}

    # If this thread is paused mid-run on a clarification interrupt, the user's
    # message is the answer to that question — resume the graph instead of
    # starting a fresh run (which would discard the pending operation context).
    if snapshot.next:
        result = graph.invoke(Command(resume=user_message), config=config)
        _record_turn(graph, config, user_message, _assistant_text(result))
        return result

    initial_state: OrchestratorState = {
        "messages": [],
        "session_id": session_id,
        "user_query_raw": user_message,
        "pipe_id": None,
        "target_date": None,
        "scheduled_start": None,
        "scheduled_end": None,
        "operation_type": "UNKNOWN",
        "operation_class": None,
        "date_range_end": None,
        "intent_confidence": 0.0,
        "clarification_round": 0,
        "awaiting_clarification": "",
        "schedule_proposals": None,
        "calendar_context": None,
        "topology_context": None,
        "sop_context": None,
        "historical_context": None,
        "operations_plan": None,
        "sop_chain": None,
        "booked_operation_id": None,
        "agents_completed": [],
        "error_messages": [],
        "final_response": None,
    }

    result = graph.invoke(initial_state, config=config)
    _record_turn(graph, config, user_message, _assistant_text(result))
    return result
