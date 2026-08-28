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
from agents.calendar_agent import calendar_agent_node, _operations_in_month, _operations_in_range
from agents.neo4j_agent import neo4j_agent_node
from agents.sop_agent import sop_agent_node
from agents.historical_agent import historical_agent_node
from agents.ops_plan_generator import ops_plan_generator_node
from prompts.sop_walkthrough_prompt import format_sop_walkthrough_table
from prompts.system_knowledge import answer_system_question
from prompts.topology_answers import answer_topology_question
from tools.calendar_tools import create_scheduled_operation, reschedule_operation, get_active_operations
from tools.chroma_tools import search_sop_documents
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
  "operation_type": "SHUTDOWN" | "INSPECTION" | "MAINTENANCE" | "SCHEDULE_QUERY" | "GENERAL_QUERY" | "UNKNOWN",
  "pipe_id": "<pipe ID string or null>",
  "target_date": "<ISO date YYYY-MM-DD or null>",
  "target_end_date": "<ISO date YYYY-MM-DD or null>",
  "end_date_mode": "USER" | "AUTO" | null,
  "operation_class": "PLANNED" | "EMERGENCY" | null,
  "confidence": 0.0
}
Rules:
- SHUTDOWN/INSPECTION/MAINTENANCE: user wants to perform a network operation on a specific pipe.
- SCHEDULE_QUERY: user wants to see/list/review operations already on the calendar for a month
  or date (e.g. "show me the operations plans for November 2026", "what's scheduled next
  month", "list planned jobs for Nov 2026", "any clashes in December?") — a read-only look at
  the schedule, not a request to create or perform a new operation.
- GENERAL_QUERY: user is asking a question about the network, SOPs, or system without
  requesting a new operation or a schedule listing.
- UNKNOWN: message is off-topic or ambiguous.
- Extract pipe_id exactly as stated (e.g. "pipe_151", "P-001").
- target_date is the requested START date of the operation (SHUTDOWN/INSPECTION/MAINTENANCE),
  or the start of the period being asked about (SCHEDULE_QUERY). For a bare month/year mention
  (e.g. "November 2026", "next month"), use the 1st of that month, e.g. "2026-11-01". Do NOT
  extract any time of day.
- target_end_date is the operator's intended END date for SHUTDOWN/INSPECTION/MAINTENANCE —
  when the pipe should be back in service (e.g. "from 17 to 20 August", "until 20-08-26", "back
  in service by 25 August", "ends on the 20th"). When one is stated, set end_date_mode to "USER".
  For SCHEDULE_QUERY, set target_end_date instead when the user asks for a range spanning more
  than one month (e.g. "August to November 2026", "between June and September 2026", "Q1 2026"
  -> target_date="2026-01-01", target_end_date="2026-03-01") — use the 1st of the end month,
  same rule as target_date. Leave target_end_date null for a single month/date query.
- end_date_mode is "AUTO" whenever the operator defers the end date/duration to
  the system, in ANY phrasing to that effect — e.g. "plan it for me", "plan for
  me", "you plan it", "you decide", "estimate it", "however long it takes", "no
  end date", "not sure, you figure it out". Match the MEANING (deferring the
  decision), not one exact wording. "USER" when target_end_date is given;
  otherwise null.
- operation_class: "EMERGENCY" if the user signals urgency (emergency, urgent, burst,
  leak, main break, pipe failure); "PLANNED" if they say planned/scheduled/routine;
  otherwise null.
- Resolve relative dates (today, tomorrow, next Monday) against the current date below.
- Dates may be written day-first, e.g. "16-07-26" or "16/07/2026" means DD-MM-YY(YY).
  Interpret short numeric dates day-first and still output ISO YYYY-MM-DD.
- IMPORTANT: A question asking whether an area or valve "would still have water" or
  "still get supply" IF a pipe is down is a GENERAL_QUERY, NOT a SHUTDOWN request.
  The user is asking a hypothetical question about the network, not requesting an
  operation. Examples:
    "If pipe_084 is down, would valve_037 still have water?" → GENERAL_QUERY
    "Would valve_002 lose water if pipe_003 is shut down?" → GENERAL_QUERY
    "Does pipe_084 have an alternate feed?" → GENERAL_QUERY
    "What happens to the supply if pipe_033 goes down?" → GENERAL_QUERY
Return ONLY the JSON object."""

# Casual pipe references ("pipe 67", "Pipe67", "shut down 67") are normalized
# to the canonical `pipe_NNN` key deterministically, rather than relying on the
# LLM to get zero-padding/underscore formatting right — the LLM only needs to
# find the number, not format it.
_PIPE_ID_WORD_RE = re.compile(r"pipe[\s_-]*0*(\d+)\b", re.IGNORECASE)
_PIPE_ID_BARE_NUM_RE = re.compile(r"^0*(\d+)$")


def _normalize_pipe_id(raw: str | None) -> str | None:
    if not raw:
        return raw
    text = raw.strip()
    match = _PIPE_ID_WORD_RE.search(text) or _PIPE_ID_BARE_NUM_RE.match(text)
    if not match:
        return raw
    return f"pipe_{int(match.group(1)):03d}"


_OFF_TOPIC_DECLINE = (
    "I'm a water network operations assistant and can only help with "
    "topics related to water network management, SOPs, and operations planning."
)

# Closed capability list. The model is only ever routed here for GENERAL_QUERY
# (in-scope, non-operation) messages — UNKNOWN/off-topic is handled deterministically
# by off_topic_node below with no LLM call. Enumerating the exact three real
# capabilities (and explicitly banning invented ones) exists because this prompt
# used to say "answer helpfully using your knowledge," which let the model
# improvise features that don't exist anywhere in this codebase (photo/document
# upload, pump/tank coordination, work orders, troubleshooting-as-a-service).
_GENERAL_SYSTEM = """You are a water network operations assistant.

You are only ever asked meta/help questions here (e.g. "how do I start?", "what can you
do?") — never SOP, safety, or network-topology content questions; those are answered
elsewhere from the real documented SOP corpus, not from your own knowledge. Explain
exactly these THREE capabilities and nothing else:
1. Generate a SHUTDOWN / INSPECTION / MAINTENANCE operations plan for a specific pipe
   on a specific date. If the user wants this, ask for the pipe ID and date.
2. Answer read-only questions about what is already booked on the operations calendar.
3. Answer questions about water network SOPs, safety procedures, and topology, grounded
   in the documented corpus. Tell the user they can just ask their specific question.

Hard rules:
- You do NOT accept photos, screenshots, scanned documents, or file uploads of any kind.
  You have no image or document intake — if asked, say so plainly.
- You do NOT coordinate pump or tank operations, prepare work orders or switching plans,
  or provide troubleshooting/diagnostics as a standalone service. These are not
  implemented. Do not offer them as options, even as a suggestion.
- If asked about specific real-time data (current pressure values, live valve status),
  say they should query the network directly — do not fabricate a value.
- If a request falls outside the three capabilities above, say plainly that it isn't
  supported and point to whichever of the three capabilities is the closest fit. Do not
  invent a fourth option.

SCOPE: Water utility operations only. If the request is unrelated to water network
management, decline with exactly: "I'm a water network operations assistant and can
only help with topics related to water network management, SOPs, and operations
planning."
"""

# Phrases that indicate the model claimed a capability this system doesn't have.
# Backstop for _GENERAL_SYSTEM above — a prompt instruction is not a guarantee,
# so the actual output is checked before it reaches the user. "pump"/"tank" +
# "coordinat" are matched in EITHER order since "coordinate a pump operation"
# and "pump coordination" both occur in practice.
#
# The add/amend/rewrit branch is the same backstop for _SOP_GROUNDED_SYSTEM below:
# a user asking the assistant to add/amend a step "into the SOP" should always be
# refused, but observed behavior was the model asking the user to supply the exact
# wording first ("I can rewrite the SOP excerpt to include it...") — a compliance
# signal, not a refusal. Wider window (35 vs 25) than pump/tank because realistic
# phrasing has more words between the verb and "sop"/"procedure" (e.g. "add one
# more step for me in the sop").
_BANNED_CAPABILITY_RE = re.compile(
    r"photo|screenshot|scanned? document|upload|work order|switching plan|"
    r"i can\b[^.\n]{0,30}\btroubleshoot|troubleshoot\w*[^.\n]{0,20}\bservice|"
    r"(pump|tank)\b[^.\n]{0,25}\bcoordinat|coordinat\w*[^.\n]{0,25}\b(pump|tank)|"
    r"(add|amend|incorporat|insert|rewrit)\w*[^.\n]{0,35}\b(sop|excerpt|procedure|document)\b|"
    r"\b(sop|excerpt|procedure|document)\b[^.\n]{0,35}(add|amend|incorporat|insert|rewrit)\w*",
    re.IGNORECASE,
)

# A banned-phrase hit near a negation ("can't", "don't", "no ...") means the
# model is correctly DISCLAIMING that capability, not claiming it — e.g.
# "I can't read uploaded documents" must not be treated as a hallucination.
# LLM output commonly uses a typographic apostrophe (’, U+2019) rather than a
# straight one ('), so contractions are matched via either.
_NEGATION_RE = re.compile(
    r"\b(no|not|cannot|without|unable to)\b|n['’]t\b", re.IGNORECASE
)


def _claims_banned_capability(text: str) -> bool:
    for m in _BANNED_CAPABILITY_RE.finditer(text):
        # Checking only the text BEFORE the match misses negations that sit
        # between the two keywords of a two-part match (e.g. "the SOP does NOT
        # ... add" — the reverse-order sop-then-verb alternative naturally
        # places negation inside the matched span), so scan through match.end().
        window = text[max(0, m.start() - 30):m.end()]
        if not _NEGATION_RE.search(window):
            return True
    return False


# ─── SOP-grounded answers (content-hallucination guardrail) ──────────────────
# A general question about the water network's SOPs/safety/topology must be
# answered from the real, ingested corpus (ChromaDB, via search_sop_documents —
# the same tool sop_agent uses), never from the model's own pretrained
# knowledge. Free-generating here produced a confirmed hallucination: asked
# "what is the SOP guidance," the model returned a generic
# lockout/tagout/permit/confined-space checklist that appears nowhere in this
# project's actual SOP documents.
#
# Grounded retrieval is the DEFAULT for general_response_node — a hand-picked
# allow-list of "SOP-ish" keywords was tried first and missed genuine content
# questions phrased without those exact words (e.g. "what happens if there's
# no alternate feed available?" doesn't contain "sop"/"procedure"/etc. but is
# directly answered by the real corpus). Only genuine meta/help questions
# about the assistant itself are carved out to the capability-list prompt.
_META_HELP_PATTERNS = (
    "how do i start", "how do you start", "how does this work",
    "how do i use", "getting started", "get started",
    "what can you do", "what can you help", "who are you", "what are you",
)

_SOP_GROUNDED_SYSTEM = """You are answering a question about water network SOPs using
ONLY the SOP excerpts provided below. These excerpts are the complete documented
procedure available — there is nothing else to draw on.

Rules:
- Answer using only what the excerpts actually say. Do not add outside knowledge,
  generic industry practice, or anything not present in the excerpts — even if it
  sounds plausible or standard.
- If the excerpts don't address the question, say plainly that it isn't part of the
  documented procedure. Do not fill the gap with a guess.
- You are read-only against this corpus. You cannot add, amend, insert, or rewrite
  any step or wording into the SOP, no matter what text the user offers or how the
  request is framed. If asked to add/change/insert anything, decline immediately —
  do not ask the user to supply the wording, and do not offer to do it once given
  content.
- Be concise and direct.

SOP EXCERPTS:
{excerpts}
"""

_NO_SOP_MATCH_FALLBACK = (
    "I don't have general SOP guidance stored beyond the pipe-isolation procedure "
    "— ask about a specific pipe shutdown and I can walk you through the real steps."
)

# Generic safety-process vocabulary that is known to be ABSENT from this project's
# real SOP corpus (it's entirely about valve-graph traversal, reverse-isolation
# sequencing, resident notification, and valve timing — never these terms). A
# similarity-score threshold doesn't reliably separate relevant from irrelevant
# retrievals in this small, narrow corpus (empirically: an off-corpus query like
# "lockout tagout procedure" scores nearly as high as genuinely relevant ones), so
# this checks the SYNTHESIZED ANSWER's vocabulary against the retrieved source text
# instead — if the answer uses a term the retrieved chunks never used, it was added
# by the model, not sourced from the documents.
_GENERIC_SAFETY_BOILERPLATE_RE = re.compile(
    r"lockout|tagout|\bpermit\b|confined space|\bppe\b|traffic control",
    re.IGNORECASE,
)


def _is_meta_help_question(message: str) -> bool:
    m = (message or "").lower()
    return any(p in m for p in _META_HELP_PATTERNS)


def _answer_is_grounded(answer: str, chunk_texts: list[str]) -> bool:
    """False if the answer uses generic safety boilerplate that never appears in
    the retrieved source chunks — a sign the model padded beyond the real corpus."""
    combined_source = " ".join(chunk_texts).lower()
    for m in _GENERIC_SAFETY_BOILERPLATE_RE.finditer(answer):
        term = m.group(0).lower()
        if term not in combined_source:
            return False
    return True


def _sop_grounded_answer(user_query: str) -> tuple[str, str]:
    """Return (answer, retrieved_chunks_text) grounded in the SOP corpus.

    The second element is the concatenated chunk text used for RAG triad scoring
    (groundedness + context relevance). Empty string if nothing was retrieved.
    """
    chunks = search_sop_documents(user_query, n_results=5)
    if not chunks:
        return _NO_SOP_MATCH_FALLBACK, ""

    excerpts = "\n\n---\n\n".join(c["text"] for c in chunks)
    s = get_settings()
    provider = s.agent_providers.get("general_response", "azure")
    client = get_azure_openai_client() if provider == "azure" else get_together_client()
    model = s.azure_openai_chat_deployment_name if provider == "azure" else s.together_model
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SOP_GROUNDED_SYSTEM.format(excerpts=excerpts)},
                {"role": "user", "content": user_query},
            ],
            max_completion_tokens=1024,
            temperature=0.2,
        )
        answer = response.choices[0].message.content or ""
    except Exception as e:
        logger.error("SOP-grounded answer error: %s", e)
        return _NO_SOP_MATCH_FALLBACK, excerpts

    if not _answer_is_grounded(answer, [c["text"] for c in chunks]):
        logger.warning(
            "SOP-grounded answer used vocabulary absent from the retrieved chunks "
            "for query %r — replacing with the honest fallback. Raw answer: %r",
            user_query, answer,
        )
        return _NO_SOP_MATCH_FALLBACK, excerpts

    # Source attribution: show which document(s) the answer was grounded in.
    # Chunks carry metadata with the source filename — dedupe and format as a
    # footer so the operator can verify the answer against the real document.
    sources = sorted({c.get("metadata", {}).get("source_file", "") for c in chunks
                      if c.get("metadata", {}).get("source_file")})
    if sources:
        source_line = "\n\n---\n*Sources: " + ", ".join(f"`{s}`" for s in sources) + "*"
        answer += source_line

    return answer, excerpts


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

    # Preserve slots already supplied in earlier turns so re-parsing a
    # clarification answer never drops them.
    op_class = parsed.get("operation_class") or state.get("operation_class")
    if isinstance(op_class, str):
        op_class = op_class.upper()
    end_mode = parsed.get("end_date_mode") or state.get("end_date_mode")
    if isinstance(end_mode, str):
        end_mode = end_mode.upper()

    # operation_type needs the same protection: mid-clarification, user_query_raw
    # is a merged, fragment-heavy string (e.g. "shut pipe 84. 9 septmeber. planned.
    # plan for me") that can occasionally read as ambiguous to the classifier and
    # come back UNKNOWN — which would otherwise silently discard an already-
    # established SHUTDOWN/INSPECTION/MAINTENANCE and route to the off-topic
    # decline mid-flow, even though the answer was perfectly valid for the slot
    # actually being asked about. Only guards the UNKNOWN failure mode: a genuine
    # SCHEDULE_QUERY/GENERAL_QUERY tangent mid-flow still takes over normally.
    op_type = parsed.get("operation_type") or "UNKNOWN"
    if (
        op_type == "UNKNOWN"
        and state.get("awaiting_clarification")
        and state.get("operation_type") in ("SHUTDOWN", "INSPECTION", "MAINTENANCE")
    ):
        op_type = state["operation_type"]

    return {
        "pipe_id": _normalize_pipe_id(parsed.get("pipe_id")) or state.get("pipe_id"),
        "target_date": parsed.get("target_date") or state.get("target_date"),
        "target_end_date": parsed.get("target_end_date") or state.get("target_end_date"),
        "end_date_mode": end_mode,
        "operation_class": op_class,
        "operation_type": op_type,
        "intent_confidence": float(parsed.get("confidence", 0.0)),
        "agents_completed": [],
        "error_messages": [],
        "clarification_round": state.get("clarification_round", 0),
        "awaiting_clarification": "",
    }


# ─── Node: General Response ───────────────────────────────────────────────────
@mlflow.trace(name="general_response", span_type=SpanType.AGENT)
def general_response_node(state: OrchestratorState) -> dict:
    user_query = state.get("user_query_raw", "")
    retrieved_chunks = None  # set by the sop_rag path if it runs

    # Strip the crew-page context prefix before routing — it contains words like
    # "crew", "site", "link" that confuse topic matching. The prefix should only
    # influence the LLM's tone on the sop_rag path, not the routing decision.
    import re as _re
    routing_query = _re.sub(r"^\[FIELD CREW[^\]]*\]\s*", "", user_query, count=1)

    # FIRST: questions about how this system works (scheduling rules, duration
    # sizing, emergency handling, the crew checklist) are answered deterministically
    # from the engines that implement them. Without this, they fell through to SOP
    # retrieval and returned "not part of the documented procedure" — the corpus
    # has no reason to describe our own rules engine. Returns None for anything it
    # doesn't clearly own, so the SOP corpus remains the default path.
    system_answer = answer_system_question(routing_query)
    if system_answer:
        logger.info("general_response answered from system knowledge: %r", user_query)
        return {
            "final_response": system_answer,
            "agents_completed": ["general_response"],
            "answer_path": "system_knowledge",
        }

    # SECOND: factual questions about a named pipe or valve are answered from the
    # live network graph. The SOP corpus documents the procedure, not the network,
    # so "what road is pipe_033 on?" had no chance of being answered from it.
    topology_answer = answer_topology_question(routing_query)
    if topology_answer:
        logger.info("general_response answered from topology graph: %r", user_query)
        return {
            "final_response": topology_answer,
            "agents_completed": ["general_response"],
            "answer_path": "topology",
        }

    # Otherwise default to grounded retrieval from the real ingested corpus — never
    # the model's own pretrained knowledge (see _sop_grounded_answer). Only genuine
    # meta/help questions about the assistant itself get the capability-list path.
    if _is_meta_help_question(routing_query):
        s = get_settings()
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
    else:
        answer, retrieved_chunks = _sop_grounded_answer(user_query)

    if _claims_banned_capability(answer):
        logger.warning(
            "general_response emitted a hallucinated-capability phrase for query %r "
            "— replacing with the safe capability redirect. Raw answer: %r",
            user_query, answer,
        )
        answer = (
            "I can't do that — here's what I can actually help with: generate a "
            "shutdown/inspection/maintenance plan for a specific pipe and date, "
            "answer read-only questions about the operations calendar, or answer "
            "general questions about water network SOPs and safety principles (text only)."
        )

    return {
        "final_response": answer,
        "agents_completed": ["general_response"],
        "answer_path": "sop_rag",
        "retrieved_chunks": retrieved_chunks,
    }


# ─── Node: Off-Topic (deterministic, no LLM call) ─────────────────────────────
# Split out from general_response so a fully off-topic message ("what's the
# capital of france") gets the exact same decline every time, with zero risk
# of the model drifting into an improvised "helpful" tangent — and without
# paying for an LLM round-trip.
@mlflow.trace(name="off_topic", span_type=SpanType.AGENT)
def off_topic_node(state: OrchestratorState) -> dict:
    # The intent classifier is nondeterministic at the UNKNOWN/GENERAL_QUERY
    # boundary, and it sometimes lands a legitimate question about OUR OWN
    # mechanics here ("how do I mark a step as done?", "who do I contact if I
    # can't finish a step?"). Declining those as off-topic is plainly wrong, so
    # check system knowledge before refusing. Genuinely off-topic messages don't
    # match any topic and still get the identical fixed decline.
    user_query = state.get("user_query_raw", "")

    system_answer = answer_system_question(user_query)
    if system_answer:
        logger.info("off_topic recovered a system-knowledge question: %r", user_query)
        return {
            "final_response": system_answer,
            "agents_completed": ["general_response"],
        }

    # Same reasoning for a named pipe/valve — a question about a real asset in the
    # network is never off-topic, whatever the classifier decided.
    topology_answer = answer_topology_question(user_query)
    if topology_answer:
        logger.info("off_topic recovered a topology question: %r", user_query)
        return {
            "final_response": topology_answer,
            "agents_completed": ["general_response"],
        }

    return {
        "final_response": _OFF_TOPIC_DECLINE,
        "agents_completed": ["off_topic"],
    }


# Up to 4 slots (pipe, start date, planned/emergency, end date) may each need a turn.
MAX_CLARIFICATION_ROUNDS = 5


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
    """First missing slot (pipe_id -> date -> operation_class -> end date) and its
    question.

    When the class is still unknown but the start date is today/tomorrow, the
    question proactively asks whether it's an emergency — short notice usually
    means urgency. The end-date question is PLANNED-only: emergencies are sized
    from the valve work without an extra round-trip.
    """
    if not state.get("pipe_id"):
        return "pipe_id", "Which pipe is this operation on? (e.g. `pipe_151`)"
    if not state.get("target_date"):
        return "date", f"What date should the operation start? (DD-MM-YY, e.g. `{_example_date()}`)"
    if not state.get("operation_class"):
        if _is_near_term(state.get("target_date")):
            return "operation_class", (
                "That's very short notice — is this an **emergency** shutdown? "
                "Reply `emergency`, or `planned` if it can be scheduled normally."
            )
        return "operation_class", (
            "Is your requested shutdown date considered a **planned** or an "
            "**emergency** operation?"
        )
    return "end_date", (
        "Is there an intended **end date** — when the pipe should be back in "
        f"service (DD-MM-YY, e.g. `{_example_date()}`)? Reply with a date, or "
        "`plan it for me` and I'll size the duration from the valve work involved."
    )


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
    return f"📅 **Operation plans that are already scheduled in {label}:**\n\n" + "\n".join(rows)


def _schedule_range_preview(target_date: str | None, target_end_date: str | None) -> str:
    """A look at what's already booked across a date range. Falls back to the
    single-month preview when no end date is given, or the end date lands in
    the same month as the start — so the existing single-month wording/tests
    are unaffected and only genuine multi-month ranges take the range path."""
    if not target_end_date:
        return _month_schedule_preview(target_date)
    try:
        start = datetime.fromisoformat(target_date)
        end = datetime.fromisoformat(target_end_date)
    except (ValueError, TypeError):
        return _month_schedule_preview(target_date)
    if (start.year, start.month) == (end.year, end.month):
        return _month_schedule_preview(target_date)

    start_label = start.strftime("%B %Y")
    end_label = end.strftime("%B %Y")
    try:
        ops = _operations_in_range(get_active_operations(), target_date, target_end_date)
    except Exception as e:
        logger.warning("Could not load range schedule preview: %s", e)
        return ""
    if not ops:
        return (f"📅 Nothing is scheduled between **{start_label}** and **{end_label}** "
                 "— the calendar is clear.")
    rows = ["| Operation | Pipe | When |", "|-----------|------|------|"]
    for o in sorted(ops, key=lambda x: x.get("scheduled_start", "")):
        rows.append(f"| {o.get('operation_id', '')} | `{o.get('pipe_id', '')}` | "
                    f"{_fmt_dt(o.get('scheduled_start'))} → {_fmt_dt(o.get('scheduled_end'))} |")
    return (f"📅 **Operation plans scheduled between {start_label} and {end_label}:**\n\n"
            + "\n".join(rows))


# ─── Node: Schedule Query (read-only "what's on the calendar for month X") ───
@mlflow.trace(name="schedule_query", span_type=SpanType.AGENT)
def schedule_query_node(state: OrchestratorState) -> dict:
    """Answer a schedule-listing question directly from the calendar, instead of
    falling through to the tool-less general_response LLM (which has no access
    to live bookings and can only ask the user to paste the schedule in).
    No month/date stated -> default to the current month, matching how a
    calendar view naturally defaults to "now" rather than asking a clarifying
    question for a read-only look.
    """
    target_date = state.get("target_date") or datetime.now().date().isoformat()
    preview = _schedule_range_preview(target_date, state.get("target_end_date"))
    if not preview:
        preview = "I couldn't read the schedule for that period — please try again."
    return {"final_response": preview, "agents_completed": ["schedule_query"]}


@mlflow.trace(name="clarification", span_type=SpanType.AGENT)
def clarification_node(state: OrchestratorState) -> dict:
    round_num = state.get("clarification_round", 0)
    if round_num >= MAX_CLARIFICATION_ROUNDS:
        return {
            "final_response": (
                "To plan an operation I need three things: the **pipe ID** "
                f"(e.g. `pipe_151`), the **start date** (DD-MM-YY, e.g. `{_example_date()}`), and "
                "whether it is a **planned** operation or an **emergency**. "
                "For planned operations you can also give an intended **end date**, "
                "or ask me to plan the duration. Please provide these and try again."
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


# Old vs new dates in reschedule tables (tones readable on the dark chat theme).
_OLD_DATE_COLOR = "#f87171"   # red — previous planned date
_NEW_DATE_COLOR = "#4ade80"   # green — proposed new date


def _fmt_date(iso: str) -> str:
    """'2026-06-19T08:00:00' -> '2026-06-19'."""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d")
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
                    f'<span style="color:{_OLD_DATE_COLOR}">{_fmt_dt(p["old_start"])} → {_fmt_dt(p["old_end"])}</span> | '
                    f'<span style="color:{_NEW_DATE_COLOR}">{_fmt_dt(p["proposed_start"])} → {_fmt_dt(p["proposed_end"])}</span> |'
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
        honored = cal.get("requested_end_date") and not cal.get("window_auto_extended")
        suffix = " — ends on your requested date" if honored else ""
        lines.append(f"\n📅 **Proposed slot:** {_fmt_dt(cs)} → {_fmt_dt(ce)}{span}{effort}{suffix}.")
        if cal.get("window_auto_extended"):
            lines.append(
                f"⚠️ Your requested end date {_fmt_date(cal.get('requested_end_date'))} "
                f"is too short for the valve work involved — I've extended the "
                f"window to {_fmt_dt(ce)}."
            )

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
            # Emergency flow: displaced ops get an extra column showing the
            # previous planned date (red) → proposed new date (green).
            proposals_by_id = {
                p["operation_id"]: p for p in state.get("schedule_proposals") or []
            }
            rescheduling = any(o.get("operation_id") in proposals_by_id for o in month_ops)
            lines.append(f"\n#### 📅 Operation plans that are already scheduled in {label}")
            header = "| Operation | Pipe | When | Clash |"
            divider = "|-----------|------|------|-------|"
            if rescheduling:
                header += " Reschedule (old → new) |"
                divider += "------------------------|"
            lines.append(header)
            lines.append(divider)
            for o in sorted(month_ops, key=lambda x: x.get("scheduled_start", "")):
                clash = "⚠️ **clash**" if o.get("clash") else "—"
                row = (
                    f"| {o.get('operation_id', '')} | `{o.get('pipe_id', '')}` | "
                    f"{_fmt_dt(o.get('scheduled_start'))} → {_fmt_dt(o.get('scheduled_end'))} | {clash} |"
                )
                if rescheduling:
                    p = proposals_by_id.get(o.get("operation_id"))
                    if p:
                        row += (
                            f' <span style="color:{_OLD_DATE_COLOR}">{_fmt_date(p["old_start"])}</span> → '
                            f'<span style="color:{_NEW_DATE_COLOR}">{_fmt_date(p["proposed_start"])}</span> |'
                        )
                    else:
                        row += " — |"
                lines.append(row)
            lines.append("")  # terminate the table so following text isn't absorbed into it
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

    # Save checklist snapshot for crew fallback (non-fatal if Neo4j unavailable)
    sop_chain = state.get("sop_chain")
    if sop_chain:
        try:
            from tools.crew_tools import save_checklist_snapshot
            save_checklist_snapshot(op_id, sop_chain)
        except Exception as _e:
            logger.warning("Could not save crew checklist snapshot for %s: %s", op_id, _e)

    lines.append(f"\n📄 [Download isolation report (PDF)](/api/v1/operations/{op_id}/report)")
    lines.append(f"👷 [Share with crew](/crew/{op_id})")
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

    # Save checklist snapshot for crew fallback
    sop_chain = state.get("sop_chain")
    if sop_chain:
        try:
            from tools.crew_tools import save_checklist_snapshot
            save_checklist_snapshot(op_id, sop_chain)
        except Exception as _e:
            logger.warning("Could not save crew checklist snapshot for %s: %s", op_id, _e)

    lines.append(f"\n📄 [Download isolation report (PDF)](/api/v1/operations/{op_id}/report)")
    lines.append(f"👷 [Share with crew](/crew/{op_id})")
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

    if op_type == "SCHEDULE_QUERY":
        return "schedule_query"

    if op_type == "UNKNOWN":
        return "off_topic"

    if op_type == "GENERAL_QUERY":
        return "general_response"

    # OPS query — require pipe, start date, and planned/emergency before proceeding.
    if not state.get("pipe_id") or not state.get("target_date") or not state.get("operation_class"):
        return "clarification"

    # PLANNED ops also need the end-date preference (an intended end date, or
    # explicit deferral to the system). Emergencies skip this round-trip.
    if (state.get("operation_class") or "").upper() == "PLANNED" and not state.get("end_date_mode"):
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
    graph.add_node("off_topic",             off_topic_node)
    graph.add_node("schedule_query",        schedule_query_node)
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
        ["general_response", "off_topic", "schedule_query", "clarification", "neo4j_agent"],
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
    graph.add_edge("off_topic",             END)
    graph.add_edge("schedule_query",        END)
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

    # ── Crew read-only restriction ────────────────────────────────────────────
    # The crew page prefixes messages with "[FIELD CREW ...]". Crew members can
    # ask questions (SOP, troubleshooting, supply checks) but CANNOT initiate
    # operations planning or booking. They should contact their supervisor for that.
    _CREW_PREFIX_RE = re.compile(r"^\[FIELD CREW[^\]]*\]")
    is_crew = bool(_CREW_PREFIX_RE.match(user_message or ""))

    if is_crew:
        # Strip prefix for routing, keep for context
        clean_msg = _CREW_PREFIX_RE.sub("", user_message).strip()
        # Detect ops-planning intent keywords
        _OPS_KEYWORDS = (
            "shut down", "shutdown", "schedule", "book", "plan",
            "maintenance", "inspection", "emergency",
        )
        wants_ops = any(k in clean_msg.lower() for k in _OPS_KEYWORDS)
        # Also check if they're asking a question (read-only) vs commanding an action
        _QUESTION_WORDS = ("?", "would", "will", "can", "does", "is", "are", "how", "what", "if")
        is_question = any(w in clean_msg.lower().split()[:5] for w in _QUESTION_WORDS) or "?" in clean_msg

        if wants_ops and not is_question:
            return {
                "final_response": (
                    "I can help you with questions about the operation, valve procedures, "
                    "and safety — but **booking or scheduling operations must be done by the "
                    "ops planning team**.\n\n"
                    "If you need an operation planned or an emergency shutdown initiated, "
                    "contact your supervisor directly. You can flag the situation using the "
                    "🚩 button on your checklist so the planning team is notified."
                ),
                "answer_path": "crew_restriction",
            }

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    snapshot = graph.get_state(config)

    # ── Supply / alternate-feed questions — deterministic, skip the intent parser ─
    # "If pipe_084 is down, would valve_037 still have water?" is a hypothetical
    # question about network topology, NOT a shutdown request. The intent parser
    # sometimes misclassifies it as SHUTDOWN (because it mentions a pipe + "down"),
    # which sends it to the clarification node asking for a date. Catching it here
    # guarantees it is answered from the live graph regardless of the LLM's mood.
    # Only intercept supply-pattern questions; other topology questions (isolation
    # chain, properties, turns) already route correctly via GENERAL_QUERY.
    #
    # Guard: require a CONDITIONAL framing word ("if", "would", "still", "lose",
    # "have water") so that imperative shutdown requests like "shut down pipe_084
    # next Monday" don't get caught by the "shut down" entry in _SUPPLY_WORDS.
    from prompts.topology_answers import _SUPPLY_WORDS, _extract_ids as _topo_ids
    _user_lower = (user_message or "").lower()
    _SUPPLY_CONDITIONALS = ("if ", "would", "still", "lose water", "have water",
                            "get water", "alternate feed", "alternative feed",
                            "alt feed", "supply")
    _has_supply_signal = (
        any(w in _user_lower for w in _SUPPLY_WORDS)
        and any(c in _user_lower for c in _SUPPLY_CONDITIONALS)
    )
    _has_pipe, _ = _topo_ids(_user_lower)
    if _has_supply_signal and _has_pipe:
        _supply_answer = answer_topology_question(user_message)
        if _supply_answer:
            _record_turn(graph, config, user_message, _supply_answer)
            return {"final_response": _supply_answer, "answer_path": "topology"}

    # Serve the stored step-by-step isolation walkthrough on request. Read-only:
    # it does not start a new operation or disturb a pending interrupt, so a later
    # "confirm" still resumes a paused booking. Only short-circuits when there's
    # actually a chain to show — a general SOP question with no stored operation
    # (e.g. "what is the SOP guidance") falls through to the normal graph instead
    # of getting a guessed, misleading "ask about a pipe shutdown first" reply.
    if _is_steps_request(user_message):
        chain = (snapshot.values or {}).get("sop_chain")
        if chain:
            text = format_sop_walkthrough_table(chain)
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
        "answer_path": None,
        "retrieved_chunks": None,
    }

    result = graph.invoke(initial_state, config=config)
    _record_turn(graph, config, user_message, _assistant_text(result))
    return result
