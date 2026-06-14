import json
import logging

import mlflow
from mlflow.entities import SpanType

from config.settings import get_settings, get_llm_client
from prompts.sop_walkthrough_prompt import build_sop_chain_data
from schemas.graph_state import OrchestratorState, OperationsPlan, OpsValveAction

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior water network operations engineer.
You generate detailed, safety-compliant operations plans for water network maintenance tasks.
The network topology data from Neo4j is ground truth — do not invent network elements.

## DETERMINISTIC SOP CHAIN — use this as ground truth when present

When a "DETERMINISTIC SOP CHAIN (GROUND TRUTH)" section is provided, it is the
authoritative result of the SOP traversal. Build valve_sequence directly from it
instead of re-deriving the chain from the pipe topology list:
- Use its tail-end valve, alternate-feed result, affected valves, and re-feed
  sequence exactly as given — do not recompute or second-guess them.
- If it reports an alternate feed AVAILABLE, emit the re-feed sequence as ordered
  valve_sequence steps: for each pair, an OPEN action on the reverse pipe's
  downstream valve, then a CLOSE action on the forward pipe's downstream valve,
  tail-first, ending with the shutdown of the originally isolated pipe.
- Treat the listed affected valves as the customers losing supply.
- With this chain present, the verdict should be FEASIBLE (or NOT_FEASIBLE only
  for a real blocking reason such as a calendar conflict) — not CONDITIONAL for
  lack of topology, since the chain already resolves the topology.

## SOP Hierarchy — follow this exactly when building valve_sequence

Step 1 — Identification (always run first):
  Trace downstream from the pipe's downstream valve to the tail-end valve.
  Check for an alternate feed at the tail-end valve.
  Record the shutdown chain (pipes and valves).
  Verify reverse isolation pipes are closed.

Step 2 — Branch on alternate feed result:

  If alternate feed AVAILABLE — Alternate Feed Available SOP:
    Working backwards from the tail-end valve through the reverse isolation pipes:
    - For each reverse isolation pipe (tail-end to origin): verify status closed, then operate its downstream valve.
    - Final action: operate the valve immediately downstream of the originally isolated pipe.
    - Record total valves operated.

  If NO alternate feed — No Alternate Feed SOP:
    - Notify the operator that no alternate feed is available.
    - List every valve downstream of the isolated pipe with its road name.
    - Arrange temporary water supply via water wagon and water bags for affected residents.

The valve_sequence in your JSON output must reflect the correct SOP branch above.

You must return ONLY a valid JSON object matching this exact schema:
{
  "feasibility_verdict": "FEASIBLE" | "NOT_FEASIBLE" | "CONDITIONAL",
  "feasibility_reason": "<one sentence explaining the verdict>",
  "pre_operation_checks": ["<check 1>", "<check 2>"],
  "valve_sequence": [
    {
      "valve_id": "<valve ID>",
      "road_name": "<road name>",
      "action": "CLOSE" | "OPEN" | "CHECK" | "MONITOR",
      "sequence_number": 1,
      "reason": "<why this action>",
      "timing_note": "<e.g. wait 10 min after step 2>",
      "current_status": "OPEN" | "CLOSED" | "UNKNOWN"
    }
  ],
  "estimated_duration_hours": 0.0,
  "affected_consumers_summary": "<summary of customer impact>",
  "notifications_required": ["<notification 1>"],
  "post_operation_steps": ["<step 1>"],
  "safety_warnings": ["<warning 1>"],
  "alternative_recommendation": null | "<recommendation if NOT_FEASIBLE>"
}
Return ONLY the JSON object. No markdown fences, no preamble."""


def _fmt_topo(topo: dict | None) -> str:
    if not topo:
        return "No topology data available."
    fv = topo.get("from_valve", {})
    tv = topo.get("to_valve", {})
    pp = topo.get("pipe_props", {})
    return (
        f"Pipe: {topo['pipe_id']} (partner: {topo.get('partner_pipe_id', 'N/A')})\n"
        f"Material: {pp.get('material')} | Diameter: {pp.get('diameter_mm')}mm | "
        f"Length: {pp.get('length_m')}m | Road: {pp.get('road_name')}\n"
        f"From valve: {fv.get('id')} ({fv.get('road_name')}, status={fv.get('status')}, elevation={fv.get('elevation')})\n"
        f"To valve:   {tv.get('id')} ({tv.get('road_name')}, status={tv.get('status')}, elevation={tv.get('elevation')})\n"
        f"Alternative supply path exists: {topo.get('alternative_path_exists', False)}\n"
        f"Downstream pipes affected: {len(topo.get('downstream_pipes', []))}\n"
        f"Downstream pipe details: {json.dumps(topo.get('downstream_pipes', []), indent=2)}"
    )


def _fmt_chain(chain: dict | None) -> str:
    """Render the deterministic SOP chain (from build_sop_chain_data) as ground truth.

    Supplies the valve adjacency the flat topology lacks: the downstream chain,
    affected valves, and the exact re-feed open/close pairs — so the LLM formats
    the plan from computed truth instead of re-deriving it from a pipe list.
    """
    if not chain:
        return "No deterministic SOP chain available."

    alt = chain.get("alternate_feed")
    tail = chain.get("tail_valve_id", "")
    lines = [
        f"Origin pipe: {chain.get('pipe_id')} "
        f"({chain.get('from_valve_id')} -> {chain.get('to_valve_id')}), "
        f"road: {chain.get('pipe_road_name')}, status: {chain.get('pipe_status')}",
        f"Tail-end valve: {tail}",
        f"Shutdown chain pipes: {' -> '.join(chain.get('shutdown_pipes', []))}",
        f"Shutdown chain valves: {' -> '.join(chain.get('shutdown_valves', []))}",
    ]

    if alt:
        lines.append(
            f"Alternate feed: AVAILABLE via {alt['pipe_id']} "
            f"(from {alt['from_valve_id']}, status {alt['status']}) at tail-end {tail}"
        )
        # Affected = downstream valves except the tail-end valve, which is
        # independently supplied by the alternate feed and therefore spared.
        downstream = chain.get("downstream_valves_with_roads", [])
        affected = [v for v in downstream if v["valve_id"] != tail]
        if affected:
            lines.append("Affected valves (lose supply during shutdown):")
            for v in affected:
                lines.append(f"  - {v['valve_id']} ({v['road_name']})")

        # Re-feed / reverse-isolation: per adjacent pair from tail back to the
        # shut pipe, OPEN the reverse pipe then CLOSE its forward counterpart.
        reverse = chain.get("reverse_checks", [])
        forward = chain.get("shutdown_pipes", [])[::-1]
        if reverse:
            lines.append(
                "Re-feed sequence (tail-first; per pair open reverse pipe, then "
                "close forward counterpart):"
            )
            for i, c in enumerate(reverse):
                fwd = forward[i] if i < len(forward) else "unknown"
                lines.append(
                    f"  Seq {i + 1} ({c['from_valve']} -> {c['to_valve']}): "
                    f"open {c['pipe_id']} (reverse, currently {c['status']}), "
                    f"then close {fwd} (forward, the shutdown for this pair)"
                )
    else:
        lines.append(f"Alternate feed: NONE found at tail-end {tail}.")
        downstream = chain.get("downstream_valves_with_roads", [])
        if downstream:
            lines.append("Affected valves downstream (no alternate feed — notify residents):")
            for v in downstream:
                lines.append(f"  - {v['valve_id']} ({v['road_name']})")

    return "\n".join(lines)


def _fmt_calendar(cal: dict | None) -> str:
    if not cal:
        return "No calendar data available."
    lines = [
        f"Feasible date window: {cal.get('is_feasible_date')}",
        f"Blocking conflict: {cal.get('blocking_conflict')}",
        f"Window: {cal.get('checked_start')} → {cal.get('checked_end')}",
    ]
    for c in cal.get("conflicts", []):
        lines.append(f"  CONFLICT [{c['severity']}]: {c['title']} ({c['scheduled_start']} – {c['scheduled_end']})")
    return "\n".join(lines)


def _fmt_sop(sop: dict | None) -> str:
    if not sop or not sop.get("relevant_principles"):
        return "No SOP principles available."
    return "\n".join(f"- {p}" for p in sop["relevant_principles"])


def _fmt_history(hist: dict | None) -> str:
    if not hist or not hist.get("similar_plans"):
        return "No historical plans available."
    parts = []
    for plan in hist["similar_plans"]:
        parts.append(
            f"Plan {plan['plan_id']} (outcome: {plan.get('outcome', 'unknown')}):\n"
            f"{plan['combined_text'][:600]}"
        )
    return "\n\n".join(parts)


@mlflow.trace(name="llm_call", span_type=SpanType.LLM)
def _call_llm(user_content: str, sop_text: str) -> str:
    s = get_settings()
    client = get_llm_client("ops_plan_generator")

    response = client.chat.completions.create(
        model=s.azure_openai_chat_deployment_name,
        messages=[
            {"role": "system", "content": f"{_SYSTEM_PROMPT}\n\n## SOP PRINCIPLES\n{sop_text}"},
            {"role": "user", "content": user_content},
        ],
        max_completion_tokens=4096,
        temperature=0.0,
    )
    return response.choices[0].message.content or "{}"


def _parse_plan(raw: str) -> dict | None:
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


@mlflow.trace(name="ops_plan_generator", span_type=SpanType.AGENT)
def ops_plan_generator_node(state: OrchestratorState) -> dict:
    topo = state.get("topology_context")
    cal = state.get("calendar_context")
    sop = state.get("sop_context")
    hist = state.get("historical_context")
    pipe_id = state.get("pipe_id", "")
    target_date = state.get("target_date", "")
    start = state.get("scheduled_start", "")
    end = state.get("scheduled_end", "")
    op_type = state.get("operation_type", "SHUTDOWN")

    # Deterministic SOP chain (ground truth from Neo4j traversal). Supplies the
    # valve adjacency, affected valves, and re-feed open/close pairs the flat
    # topology lacks. Degrade gracefully to topology-only if it cannot be built.
    chain = None
    if pipe_id:
        try:
            chain = build_sop_chain_data(pipe_id)
        except Exception as e:
            logger.warning("Could not build deterministic SOP chain for %s: %s", pipe_id, e)

    sop_text = _fmt_sop(sop)
    user_content = (
        f"## DETERMINISTIC SOP CHAIN (GROUND TRUTH)\n{_fmt_chain(chain)}\n\n"
        f"## PIPE TOPOLOGY\n{_fmt_topo(topo)}\n\n"
        f"## CALENDAR\n{_fmt_calendar(cal)}\n\n"
        f"## HISTORICAL PRECEDENTS\n{_fmt_history(hist)}\n\n"
        f"## REQUEST\nGenerate a {op_type} operations plan for pipe {pipe_id} "
        f"on {target_date} from {start} to {end}.\n"
        f"Verdict must reflect both the calendar feasibility and network topology."
    )

    try:
        raw = _call_llm(user_content, sop_text)
    except Exception as e:
        logger.error("Ops plan generator LLM call failed: %s", e)
        return {
            "error_messages": state.get("error_messages", []) + [
                "Failed to generate operations plan. Please try again."
            ],
            "agents_completed": state.get("agents_completed", []) + ["ops_plan_generator"],
        }

    plan_dict = _parse_plan(raw)

    # Retry once with explicit format reminder if JSON parse failed
    if plan_dict is None:
        logger.warning("JSON parse failed on first attempt, retrying with format reminder")
        try:
            retry_content = (
                user_content + "\n\nIMPORTANT: Return ONLY the raw JSON object. "
                "No markdown fences, no explanation, just the JSON."
            )
            raw2 = _call_llm(retry_content, sop_text)
            plan_dict = _parse_plan(raw2)
        except Exception as e:
            logger.error("Retry also failed: %s", e)

    if plan_dict is None:
        return {
            "error_messages": state.get("error_messages", []) + [
                "Could not parse operations plan. Please try again."
            ],
            "agents_completed": state.get("agents_completed", []) + ["ops_plan_generator"],
        }

    # Normalise valve_sequence entries to OpsValveAction TypedDict shape
    valve_seq = []
    for item in plan_dict.get("valve_sequence", []):
        valve_seq.append(OpsValveAction(
            valve_id=item.get("valve_id", ""),
            road_name=item.get("road_name", ""),
            action=item.get("action", "CHECK"),
            sequence_number=int(item.get("sequence_number", 0)),
            reason=item.get("reason", ""),
            timing_note=item.get("timing_note", ""),
            current_status=item.get("current_status", "UNKNOWN"),
        ))

    plan = OperationsPlan(
        feasibility_verdict=plan_dict.get("feasibility_verdict", "CONDITIONAL"),
        feasibility_reason=plan_dict.get("feasibility_reason", ""),
        pre_operation_checks=plan_dict.get("pre_operation_checks", []),
        valve_sequence=valve_seq,
        estimated_duration_hours=float(plan_dict.get("estimated_duration_hours", 0.0)),
        affected_consumers_summary=plan_dict.get("affected_consumers_summary", ""),
        notifications_required=plan_dict.get("notifications_required", []),
        post_operation_steps=plan_dict.get("post_operation_steps", []),
        safety_warnings=plan_dict.get("safety_warnings", []),
        alternative_recommendation=plan_dict.get("alternative_recommendation"),
    )

    return {
        "operations_plan": plan,
        "agents_completed": state.get("agents_completed", []) + ["ops_plan_generator"],
    }
