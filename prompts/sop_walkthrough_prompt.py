"""
prompts/sop_walkthrough_prompt.py
----------------------------------
Model-agnostic SOP walkthrough prompt template.

Public API:
  SOP_WALKTHROUGH_SYSTEM_PROMPT  — registered in MLflow; import in evaluation/prompts.py
  SOP_WALKTHROUGH_USER_TEMPLATE  — Jinja2 template string; rendered at call time
  build_sop_chain_data(pipe_id)  — runs Neo4j traversal, returns template variable dict
  render_sop_prompt(pipe_id)     — convenience: build_sop_chain_data + template render

Usage (model-agnostic):
    from prompts.sop_walkthrough_prompt import SOP_WALKTHROUGH_SYSTEM_PROMPT, render_sop_prompt

    user_msg = render_sop_prompt("pipe_084")

    # OpenAI-compatible (Azure OpenAI, Together.ai, etc.)
    response = client.chat.completions.create(
        model=model, temperature=0.0, max_completion_tokens=2048,
        messages=[
            {"role": "system", "content": SOP_WALKTHROUGH_SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )

temperature=0.0 is strongly recommended — the output is deterministic given the data.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment, StrictUndefined

from db.neo4j_client import execute_read
from tools.neo4j_tools import get_pipe_and_valves


# ── System prompt ──────────────────────────────────────────────────────────────
# Registered in MLflow via evaluation/prompts.py.
# Keep model-agnostic: no provider-specific fields (cache_control, etc.).
# Uses only concrete values in the few-shot example — no {{ }} syntax — so
# mlflow.register_prompt() won't try to interpolate any variables.

SOP_WALKTHROUGH_SYSTEM_PROMPT = """\
You are a water network field operations specialist following a strict Standard \
Operating Procedure (SOP) for pipe isolation.

Your task is to produce a structured SOP walkthrough that exactly matches the format \
rules and example below. Follow the step numbering, section headers, and indentation \
precisely. Do not add commentary, disclaimers, or extra explanation outside the template.

## Phase 1 — Identification output format rules
- Separator line uses exactly 60 dashes: ------------------------------------------------------------
- Section headers:    -- <title> --
- Step lines:         Step N  <valve_id>  ->  <pipe_id>  ->  <valve_id>   (<status>)
- No-next-pipe line:  Step N  <valve_id>  ->  no further open same-road pipe
- Tail-end marker:            *** TAIL-END VALVE: <valve_id> ***
- Alternate feed:       Candidate pipe: <pipe_id>  from <valve_id>  status: <status>
- Isolation lines:    <valve_id> -> <valve_id>  <pipe_id>  status: <status>  [OK|FAIL]

## Phase 2 — Action output format rules (output immediately after Phase 1)

If alternate feed AVAILABLE — output Phase 2A block:
  -- Phase 2A: Alternate Feed Available — Valve Operation Sequence --
    Working backwards through reverse isolation pipes from tail-end <tail_valve_id>:

    Seq N  <pipe_id>  (<from_valve> -> <to_valve>)  status: <status>
           Action: operate <to_valve>

    (one Seq block per reverse isolation pipe, tail-end to origin)

    Final step: operate <to_valve_id>  (valve immediately after <originally_isolated_pipe_id>)

    Total valves operated: <N>

If NO alternate feed — output Phase 2B block:
  -- Phase 2B: No Alternate Feed — Resident Notification Required --
    Status  : No alternate feed available. Service interruption confirmed.
    Affected valves downstream of <pipe_id>:
      <valve_id>  <road_name>
      (one line per affected downstream valve)
    Action  : Inform affected residents. Deploy water wagon and water bags to affected roads.

## Summary section (always last)
Free-form prose covering: chain pipe count, valve count, tail-end valve, \
alternate feed result, isolation result, and which Phase 2 action applies.

Produce ONLY the walkthrough text. No markdown fences, no preamble, no trailing notes.

## Example (pipe_084)

  SOP Walkthrough -- pipe_084
  ------------------------------------------------------------
  Origin pipe : pipe_084  (valve_034 -> valve_035)
  Road name   : Bukit Batok Street 22
  Pipe status : open

  -- Steps 1-9: Downstream trace to tail-end valve --
  Step 1  valve_035  ->  pipe_086  ->  valve_036   (open)
  Step 2  valve_036  ->  pipe_088  ->  valve_037   (open)
  Step 3  valve_037  ->  no further open same-road pipe
          *** TAIL-END VALVE: valve_037 ***

  -- Step 9: Alternate feed check --
    Candidate pipe: pipe_091  from valve_038  status: open
    Result: Alternate feed AVAILABLE via pipe_091

  -- Step 10: Sequential shutdown chain --
    Pipes  : pipe_084 -> pipe_086 -> pipe_088
    Valves : valve_034 -> valve_035 -> valve_036 -> valve_037

  -- Step 11: Branch --
    Alternate feed exists. Proceeding to step 12.

  -- Step 12: Backwards trace (isolation verification) --
    valve_037 -> valve_036  pipe_089  status: closed  [OK]
    valve_036 -> valve_035  pipe_087  status: closed  [OK]
    valve_035 -> valve_034  pipe_085  status: closed  [OK]
    All reverse pipes are closed. Isolation verified.

  -- Phase 2A: Alternate Feed Available — Valve Operation Sequence --
    Working backwards through reverse isolation pipes from tail-end valve_037:

    Seq 1  pipe_089  (valve_037 -> valve_036)  status: closed
           Action: operate valve_036

    Seq 2  pipe_087  (valve_036 -> valve_035)  status: closed
           Action: operate valve_035

    Seq 3  pipe_085  (valve_035 -> valve_034)  status: closed
           Action: operate valve_034

    Final step: operate valve_035  (valve immediately after pipe_084)

    Total valves operated: 4
  ------------------------------------------------------------

  Summary of what the SOP found for pipe_084:
  - Shutdown chain: 3 pipes (pipe_084 → pipe_086 → pipe_088), 4 valves
  - Tail-end valve: valve_037
  - Alternate feed: pipe_091 (from valve_038, status open) — service can be maintained via alternate feed
  - Isolation check: all 3 reverse-direction pipes (pipe_089, pipe_087, pipe_085) are closed — isolation valid
  - Phase 2A applies: 4 valve operations required (valve_036, valve_035, valve_034 operated; valve_035 operated as final step)
"""


# ── User message template (Jinja2) ────────────────────────────────────────────
# NOT registered in MLflow: the {{ }} syntax conflicts with MLflow's own
# variable interpolation. Versioned through Git alongside the system prompt.

SOP_WALKTHROUGH_USER_TEMPLATE = """\
Produce the SOP walkthrough for the pipe below. Use exactly the data provided — \
do not invent any network elements. Follow the output format from the system prompt.

=== NETWORK DATA FOR {{ pipe_id }} ===

Origin pipe : {{ pipe_id }}  ({{ from_valve_id }} -> {{ to_valve_id }})
Road name   : {{ pipe_road_name }}
Pipe status : {{ pipe_status }}

--- Downstream trace result (Steps 1-9) ---
{% for step in steps -%}
Step {{ loop.index }}  {{ step.from_valve }}  ->  {{ step.pipe_id }}  ->  {{ step.to_valve }}   ({{ step.status }})
{% endfor -%}
Step {{ steps | length + 1 }}  {{ tail_valve_id }}  ->  no further open same-road pipe
        *** TAIL-END VALVE: {{ tail_valve_id }} ***

--- Alternate feed check result (Step 9) ---
{% if alternate_feed -%}
  Candidate pipe: {{ alternate_feed.pipe_id }}  from {{ alternate_feed.from_valve_id }}  status: {{ alternate_feed.status }}
  Result: Alternate feed AVAILABLE via {{ alternate_feed.pipe_id }}
{% else -%}
  No pipes feeding into {{ tail_valve_id }} from outside the shutdown chain.
  Result: NO alternate feed available. Stopping at step 9.
{% endif %}
--- Shutdown chain (Step 10) ---
  Pipes  : {{ shutdown_pipes | join(' -> ') }}
  Valves : {{ shutdown_valves | join(' -> ') }}

--- Branch decision (Step 11) ---
{% if alternate_feed -%}
  Alternate feed exists. Proceeding to step 12.
{% else -%}
  No alternate feed found in step 9. Stopping here.
{% endif %}
{% if alternate_feed -%}
--- Isolation verification (Step 12) ---
{% for chk in reverse_checks -%}
  {{ chk.from_valve }} -> {{ chk.to_valve }}  {{ chk.pipe_id }}  status: {{ chk.status }}  [{{ 'OK' if chk.ok else 'FAIL' }}]
{% endfor -%}
{% if reverse_checks | selectattr('ok', 'equalto', false) | list | length == 0 -%}
  All reverse pipes are closed. Isolation verified.
{% else -%}
  WARNING: One or more reverse pipes are NOT closed. Isolation incomplete.
{% endif -%}
{% endif %}
--- Phase 2 data ---
{% if alternate_feed -%}
Phase 2A applies (alternate feed available).
Reverse isolation pipes in order (tail-end to origin):
{% for chk in reverse_checks -%}
  Seq {{ loop.index }}  {{ chk.pipe_id }}  ({{ chk.from_valve }} -> {{ chk.to_valve }})  status: {{ chk.status }}
         Action: operate {{ chk.to_valve }}
{% endfor -%}
  Final step: operate {{ to_valve_id }}  (valve immediately after {{ pipe_id }})
  Total valves operated: {{ reverse_checks | length + 1 }}
{% else -%}
Phase 2B applies (no alternate feed).
Affected valves downstream of {{ pipe_id }}:
{% for v in downstream_valves_with_roads -%}
  {{ v.valve_id }}  {{ v.road_name }}
{% endfor -%}
  Action: Inform affected residents. Deploy water wagon and water bags to affected roads.
{% endif %}
Now produce the formatted SOP walkthrough for {{ pipe_id }} using exactly the data \
above and the format from the example in the system prompt.
"""


# ── Jinja2 environment ────────────────────────────────────────────────────────

_env = Environment(
    undefined=StrictUndefined,  # raise on missing variables — fail fast, not silently
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
_user_tmpl = _env.from_string(SOP_WALKTHROUGH_USER_TEMPLATE)


# ── Neo4j query helpers ───────────────────────────────────────────────────────
# Use direct Cypher queries (mirrors sop_walkthrough.py exactly) rather than
# get_neighborhood_pipes(), which does not return pipe status and therefore
# cannot filter for open pipes in the downstream trace.

def _q(cypher: str, params: dict) -> list[dict]:
    try:
        return execute_read(cypher, params)
    except Exception:
        return []


# ── Public: build template variable dict from Neo4j ──────────────────────────

def build_sop_chain_data(pipe_id: str) -> dict[str, Any]:
    """
    Run the SOP traversal against Neo4j and return a dict of template variables.

    Mirrors the algorithm in scripts/sop_walkthrough.py but returns structured
    data instead of printing. Raises ValueError if the pipe is not found.

    Returns keys:
      pipe_id, from_valve_id, to_valve_id, pipe_road_name, pipe_status,
      steps            list[{from_valve, pipe_id, to_valve, status}],
      tail_valve_id,
      alternate_feed   {pipe_id, from_valve_id, status} | None,
      shutdown_pipes   list[str],
      shutdown_valves  list[str] (deduplicated),
      reverse_checks   list[{from_valve, to_valve, pipe_id, status, ok}]
    """
    pipe_data = get_pipe_and_valves(pipe_id)
    if not pipe_data:
        raise ValueError(f"Pipe '{pipe_id}' not found in Neo4j.")

    from_id = pipe_data["from_valve"].get("id", "")
    to_id   = pipe_data["to_valve"].get("id", "")
    road    = pipe_data["pipe_props"].get("road_name", "")
    status  = pipe_data["pipe_props"].get("status", "unknown")

    # ── Steps 1-9: forward trace (same query as sop_walkthrough.py) ───────────
    steps:           list[dict] = []
    shutdown_pipes:  list[str]  = [pipe_id]
    shutdown_valves: list[str]  = [from_id, to_id]
    current_valve = to_id

    while True:
        nxt = _q(
            "MATCH (v:Valve {id: $vid})-[p:PIPE]->(v2:Valve) "
            "WHERE toLower(p.road_name) = toLower($road) AND p.status = 'open' "
            "RETURN p.pipe_id AS pipe_id, v2.id AS next_valve, p.status AS pstatus LIMIT 1",
            {"vid": current_valve, "road": road},
        )
        if not nxt:
            tail_valve_id = current_valve
            break
        r = nxt[0]
        steps.append({
            "from_valve": current_valve,
            "pipe_id":    r["pipe_id"],
            "to_valve":   r["next_valve"],
            "status":     r["pstatus"],
        })
        shutdown_pipes.append(r["pipe_id"])
        shutdown_valves.append(r["next_valve"])
        current_valve = r["next_valve"]

    # ── Step 9: alternate feed (same query as sop_walkthrough.py) ────────────
    visited_valves = set(shutdown_valves)
    all_touching = _q(
        "MATCH ()-[p:PIPE]->(v:Valve {id: $vid}) "
        "RETURN p.pipe_id AS pipe_id, p.from_id AS from_id, p.status AS status",
        {"vid": tail_valve_id},
    )
    candidates = [r for r in all_touching if r["from_id"] not in visited_valves]
    alternate_feed: dict | None = None
    for r in candidates:
        if r["status"] == "open":
            alternate_feed = {
                "pipe_id":       r["pipe_id"],
                "from_valve_id": r["from_id"],
                "status":        r["status"],
            }
            break

    # ── Step 12: reverse isolation checks ────────────────────────────────────
    reverse_checks: list[dict] = []
    if alternate_feed:
        reverse_chain = list(dict.fromkeys(shutdown_valves))[::-1]
        for i in range(len(reverse_chain) - 1):
            curr     = reverse_chain[i]
            nxt_val  = reverse_chain[i + 1]
            rows = _q(
                "MATCH (v1:Valve {id: $fid})-[p:PIPE]->(v2:Valve {id: $tid}) "
                "RETURN p.pipe_id AS pipe_id, p.status AS status LIMIT 1",
                {"fid": curr, "tid": nxt_val},
            )
            if rows:
                s = rows[0]["status"] or "unknown"
                reverse_checks.append({
                    "from_valve": curr,
                    "to_valve":   nxt_val,
                    "pipe_id":    rows[0]["pipe_id"],
                    "status":     s,
                    "ok":         s == "closed",
                })
            else:
                reverse_checks.append({
                    "from_valve": curr,
                    "to_valve":   nxt_val,
                    "pipe_id":    "not-found",
                    "status":     "unknown",
                    "ok":         False,
                })

    # Downstream valves with road names (for Phase 2B resident notification)
    downstream_valve_ids = list(dict.fromkeys(shutdown_valves))[1:]  # exclude from_id
    if downstream_valve_ids:
        road_rows = _q(
            "MATCH (v:Valve) WHERE v.id IN $ids RETURN v.id AS id, v.road_name AS road_name",
            {"ids": downstream_valve_ids},
        )
        road_map = {r["id"]: r.get("road_name", "") for r in road_rows}
        downstream_valves_with_roads = [
            {"valve_id": vid, "road_name": road_map.get(vid, "")}
            for vid in downstream_valve_ids
        ]
    else:
        downstream_valves_with_roads = []

    # Valve diameters for every valve the operation touches — used by the valve
    # operation timing SOP to size the schedule (valve_operation_rules.py).
    involved_ids = set(shutdown_valves) | {from_id, to_id}
    if alternate_feed:
        involved_ids.add(alternate_feed["from_valve_id"])
    for r in reverse_checks:
        involved_ids.update([r["from_valve"], r["to_valve"]])
    involved_ids.discard(None)
    valve_diameters: dict[str, Any] = {}
    if involved_ids:
        diam_rows = _q(
            "MATCH (v:Valve) WHERE v.id IN $ids RETURN v.id AS id, v.diameter_mm AS d",
            {"ids": list(involved_ids)},
        )
        valve_diameters = {r["id"]: r["d"] for r in diam_rows if r.get("d") is not None}

    return {
        "pipe_id":                    pipe_id,
        "from_valve_id":              from_id,
        "to_valve_id":                to_id,
        "pipe_road_name":             road,
        "pipe_status":                status,
        "steps":                      steps,
        "tail_valve_id":              tail_valve_id,
        "alternate_feed":             alternate_feed,
        "shutdown_pipes":             shutdown_pipes,
        "shutdown_valves":            list(dict.fromkeys(shutdown_valves)),
        "reverse_checks":             reverse_checks,
        "downstream_valves_with_roads": downstream_valves_with_roads,
        "valve_diameters":            valve_diameters,
    }


# ── Public: deterministic walkthrough renderer (no LLM) ───────────────────────
# Turns build_sop_chain_data() output into the step-by-step SOP walkthrough text,
# numbered to match data/seed/sop_documents/SOP_document.docx:
#   Steps 1-8 downstream trace, 9 alternate feed, 10 shutdown chain,
#   11 affected valves, 12 re-feed reversal (or no-alternate-feed branch).
# Deterministic so the output always matches the SOP exactly — no model variance.

_SEP = "-" * 60


def format_sop_walkthrough(chain: dict[str, Any]) -> str:
    """Render the deterministic SOP chain as a sequential walkthrough block."""
    pipe_id = chain["pipe_id"]
    from_v  = chain["from_valve_id"]
    to_v    = chain["to_valve_id"]
    road    = chain.get("pipe_road_name", "")
    status  = chain.get("pipe_status", "unknown")
    steps   = chain.get("steps", [])
    tail    = chain.get("tail_valve_id", "")
    alt     = chain.get("alternate_feed")
    sp      = chain.get("shutdown_pipes", [])
    sv      = chain.get("shutdown_valves", [])
    rev     = chain.get("reverse_checks", [])
    downstream = chain.get("downstream_valves_with_roads", [])

    L: list[str] = [
        f"SOP Walkthrough — {pipe_id}",
        _SEP,
        f"Origin pipe : {pipe_id}  ({from_v} -> {to_v})",
        f"Road name   : {road}",
        f"Pipe status : {status}",
        "",
        "-- Steps 1-8: Downstream trace to tail-end valve --",
    ]
    for i, s in enumerate(steps, 1):
        L.append(f"Step {i}  {s['from_valve']}  ->  {s['pipe_id']}  ->  {s['to_valve']}   ({s['status']})")
    L.append(f"Step {len(steps) + 1}  {tail}  ->  no further open same-road pipe")
    L.append(f"        *** TAIL-END VALVE: {tail} ***")
    L.append("")

    L.append("-- Step 9: Alternate feed check --")
    if alt:
        L.append(f"  Candidate pipe: {alt['pipe_id']}  from {alt['from_valve_id']}  status: {alt['status']}")
        L.append(f"  Result: Alternate feed AVAILABLE via {alt['pipe_id']}")
    else:
        L.append(f"  No pipes feed into {tail} from outside the shutdown chain.")
        L.append("  Result: NO alternate feed available.")
    L.append("")

    L.append("-- Step 10: Sequential shutdown chain --")
    L.append(f"  Pipes  : {' -> '.join(sp)}")
    L.append(f"  Valves : {' -> '.join(sv)}")
    L.append("")

    # Step 11 — affected valves. With an alternate feed the tail-end valve is
    # independently supplied and therefore spared; without one, all downstream lose supply.
    affected = [v for v in downstream if v["valve_id"] != tail] if alt else list(downstream)
    L.append("-- Step 11: Affected valves (consumers lose supply) --")
    if affected:
        for v in affected:
            L.append(f"  {v['valve_id']}  {v['road_name']}")
    else:
        L.append("  None.")
    if alt:
        L.append(f"  ({tail} spared — supplied by alternate feed {alt['pipe_id']})")
    L.append("")

    if alt:
        L.append("-- Step 12: Branch — alternate feed exists → re-feed sequence --")
        L.append("  Reverse flow, tail-first; per pair OPEN reverse pipe, then CLOSE forward counterpart:")
        forward = sp[::-1]
        for i, c in enumerate(rev):
            fwd = forward[i] if i < len(forward) else "unknown"
            final = "   ← actual SHUTDOWN" if i == len(rev) - 1 else ""
            L.append(
                f"  Pair {i + 1}  open {c['pipe_id']} ({c['from_valve']}->{c['to_valve']}), "
                f"then close {fwd}{final}"
            )
    else:
        L.append("-- Step 12: No alternate feed — resident notification required --")
        L.append("  Notify operator: no alternate feed; the affected area loses supply for the shutdown.")
        L.append("  Deploy water wagon and water bags to the affected roads above.")
    L.append(_SEP)
    return "\n".join(L)


# ── Public: deterministic walkthrough as a markdown table ─────────────────────
def format_sop_walkthrough_table(chain: dict[str, Any]) -> str:
    """Render the SOP chain as a neat markdown table (steps 1-12), for the chat UI."""
    pid = chain["pipe_id"]
    from_v = chain["from_valve_id"]
    to_v = chain["to_valve_id"]
    road = chain.get("pipe_road_name", "")
    status = chain.get("pipe_status", "unknown")
    steps = chain.get("steps", [])
    tail = chain.get("tail_valve_id", "")
    alt = chain.get("alternate_feed")
    sp = chain.get("shutdown_pipes", [])
    sv = chain.get("shutdown_valves", [])
    rev = chain.get("reverse_checks", [])
    downstream = chain.get("downstream_valves_with_roads", [])

    L = [
        f"### Isolation procedure — `{pid}`",
        f"Origin `{pid}` ({from_v} → {to_v}) · {road} · status **{status}**",
        "",
        "| Step | Stage | Detail |",
        "|------|-------|--------|",
    ]

    n = 0
    for s in steps:
        n += 1
        L.append(f"| {n} | Downstream trace | `{s['from_valve']}` → `{s['pipe_id']}` "
                 f"→ `{s['to_valve']}` ({s['status']}) |")
    n += 1
    L.append(f"| {n} | Tail-end valve | `{tail}` — no further open same-road pipe |")

    if alt:
        L.append(f"| 9 | Alternate feed | ✅ available via `{alt['pipe_id']}` "
                 f"from `{alt['from_valve_id']}` ({alt['status']}) |")
    else:
        L.append("| 9 | Alternate feed | ❌ none — affected area loses supply |")

    chain_str = " → ".join(f"`{v}`" for v in sv) or "—"
    L.append(f"| 10 | Shutdown chain | close in order: {chain_str} |")

    affected = [v for v in downstream if v["valve_id"] != tail] if alt else list(downstream)
    if affected:
        items = ", ".join(f"`{v['valve_id']}` ({v['road_name']})" for v in affected)
    else:
        items = "none"
    spared = f" — `{tail}` spared (alternate feed)" if alt else ""
    L.append(f"| 11 | Affected valves | {items}{spared} |")

    if alt:
        forward = sp[::-1]
        pairs = []
        for i, c in enumerate(rev):
            fwd = forward[i] if i < len(forward) else "?"
            tag = " — **final shutdown**" if i == len(rev) - 1 else ""
            pairs.append(f"open `{c['pipe_id']}` (`{c['from_valve']}`→`{c['to_valve']}`), "
                         f"then close `{fwd}`{tag}")
        if pairs:
            L.append(f"| 12 | Re-feed reversal | {pairs[0]} |")
            for p in pairs[1:]:
                L.append(f"|  | Re-feed reversal | {p} |")
        else:
            L.append("| 12 | Re-feed reversal | (no reverse pairs) |")
    else:
        L.append("| 12 | No alternate feed | notify residents; deploy water wagon "
                 "& bags to affected roads |")

    return "\n".join(L)


# ── Public: render user message ───────────────────────────────────────────────

def render_sop_prompt(pipe_id: str) -> str:
    """
    Convenience: run Neo4j traversal then render the user message template.

    Returns the fully rendered user message string ready to be passed to any
    OpenAI-compatible chat completions API alongside SOP_WALKTHROUGH_SYSTEM_PROMPT.
    """
    data = build_sop_chain_data(pipe_id)
    return _user_tmpl.render(**data)
