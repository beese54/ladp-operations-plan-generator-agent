"""Deterministic answers to factual questions about a specific pipe or valve.

Companion to prompts/system_knowledge.py. That module answers "how does this
system work" from constants; this one answers "what is true about pipe_084"
from live Neo4j.

Why this exists
---------------
The probe run (scripts/probe_chatbot.py) found the chat path answering
"Which valves isolate pipe_084?" and "What road is pipe_033 on?" with
"not part of the documented procedure" — because general_response only had the
SOP corpus to draw on, and the SOP documents describe the *procedure*, not the
network. The network facts were sitting in Neo4j the whole time.

Answers are rendered deterministically from query results, never written by a
model, so a returned road name or valve ID is always exactly what the graph
holds. Returns None whenever it can't answer confidently, so the caller falls
through to the SOP-grounded path.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Accepts pipe_084, pipe 84, PIPE_84, valve_021, valve 21 — operators are not
# consistent about the separator or zero padding.
_PIPE_RE = re.compile(r"\bpipe[\s_-]*0*(\d{1,4})\b", re.IGNORECASE)
_VALVE_RE = re.compile(r"\bvalve[\s_-]*0*(\d{1,4})\b", re.IGNORECASE)

# Intent signals within a question that already names a pipe/valve.
_ISOLATION_WORDS = (
    "isolate", "isolation", "shut", "shutdown", "close", "which valve",
    "what valve", "valves", "chain", "sequence", "affected",
)
_PROPERTY_WORDS = (
    "road", "street", "where", "made of", "material", "diameter", "size",
    "length", "status", "pressure", "installed", "year", "about",
)
_TURN_WORDS = ("turn", "turns", "handwheel", "how many turns")

# Water supply / alternate feed questions — "if pipe X is down, would valve Y
# still have water?" This is the exact question format the LADP lecturers asked.
_SUPPLY_WORDS = (
    "still have water", "still get water", "still receive water", "still supply",
    "still supplied", "lose water", "have water", "get water",
    "water supply", "alternate feed", "alternative feed", "alt feed",
    "is down", "goes down", "shut down",
    "out of service", "no water",
)

# Requests for LIVE telemetry must never be served from the static graph. The
# graph holds design/reference values (nominal pressure, diameter), not sensor
# readings, so answering "what's the current pressure at valve_014" with the
# stored figure would be confidently wrong in exactly the way that matters.
# There is no telemetry integration — these fall through to be declined.
_LIVE_DATA_WORDS = (
    "live", "real-time", "real time", "realtime", "current reading", "right now",
    "currently", "at the moment", "latest reading", "sensor", "telemetry",
    "actual pressure", "current pressure", "current status", "reading at",
)


def _canonical_pipe(n: str) -> str:
    return f"pipe_{int(n):03d}"


def _canonical_valve(n: str) -> str:
    return f"valve_{int(n):03d}"


def _extract_ids(query: str) -> tuple[Optional[str], Optional[str]]:
    pipe_m = _PIPE_RE.search(query)
    valve_m = _VALVE_RE.search(query)
    return (
        _canonical_pipe(pipe_m.group(1)) if pipe_m else None,
        _canonical_valve(valve_m.group(1)) if valve_m else None,
    )


def _fmt(value: Any, suffix: str = "") -> str:
    if value in (None, ""):
        return "not recorded"
    return f"{value}{suffix}"


# ── Answer builders ───────────────────────────────────────────────────────────

def _answer_pipe_properties(pipe_id: str) -> Optional[str]:
    from tools.neo4j_tools import get_pipe_and_valves

    data = get_pipe_and_valves(pipe_id)
    if not data:
        return None

    p = data.get("pipe_props", {}) or {}
    frm = data.get("from_valve", {}) or {}
    to = data.get("to_valve", {}) or {}

    lines = [
        f"**`{pipe_id}`**",
        "",
        "| Property | Value |",
        "|----------|-------|",
        f"| Road | {_fmt(p.get('road_name'))} |",
        f"| Material | {_fmt(p.get('material'))} |",
        f"| Diameter | {_fmt(p.get('diameter_mm'), ' mm')} |",
        f"| Length | {_fmt(p.get('length_m'), ' m')} |",
        f"| Pressure | {_fmt(p.get('pressure_mRL'), ' mRL')} |",
        f"| Status | {_fmt(p.get('status'))} |",
        f"| Year installed | {_fmt(p.get('year_installed'))} |",
        f"| Connects | `{_fmt(frm.get('id'))}` → `{_fmt(to.get('id'))}` |",
    ]
    lines.append("")
    lines.append("*Live from the network graph.*")
    return "\n".join(lines)


def _answer_isolation_chain(pipe_id: str) -> Optional[str]:
    from prompts.sop_walkthrough_prompt import build_sop_chain_data

    try:
        chain = build_sop_chain_data(pipe_id)
    except ValueError:
        return None
    except Exception as e:
        logger.warning("Isolation chain lookup failed for %s: %s", pipe_id, e)
        return None

    valves = chain.get("shutdown_valves") or []
    pipes = chain.get("shutdown_pipes") or []
    tail = chain.get("tail_valve_id")
    alt = chain.get("alternate_feed")

    if not valves:
        return None

    lines = [
        f"**Isolating `{pipe_id}`** — {_fmt(chain.get('pipe_road_name'))}",
        "",
        f"**Valves to close ({len(valves)}):** "
        + ", ".join(f"`{v}`" for v in valves),
        "",
        f"**Pipes in the shutdown chain ({len(pipes)}):** "
        + ", ".join(f"`{p}`" for p in pipes),
    ]
    if tail:
        lines += ["", f"**Tail-end valve:** `{tail}`"]

    lines.append("")
    if alt:
        lines.append(
            f"**Alternate feed available** via `{alt['pipe_id']}` from "
            f"`{alt['from_valve_id']}`, so `{tail}` can stay supplied — the "
            f"re-feed sequence reopens valves in reverse order."
        )
    else:
        affected = chain.get("downstream_valves_with_roads") or []
        if affected:
            roads = sorted({a.get("road_name", "") for a in affected if a.get("road_name")})
            lines.append(
                f"**No alternate feed** — {len(affected)} downstream valve(s) lose supply"
                + (f", affecting: {', '.join(roads)}." if roads else ".")
            )
        else:
            lines.append("**No alternate feed** was found for this chain.")

    lines += ["", "*Traced live from the network graph. "
                  "Ask me to plan the shutdown for the full step-by-step sequence.*"]
    return "\n".join(lines)


def _answer_supply_question(pipe_id: str, valve_id: Optional[str]) -> Optional[str]:
    """Answer 'if pipe X is down, would valve Y still have water?'

    Builds the SOP chain to determine alternate feed availability, then gives
    a clear yes/no with explanation.
    """
    from prompts.sop_walkthrough_prompt import build_sop_chain_data

    try:
        chain = build_sop_chain_data(pipe_id)
    except ValueError:
        return None
    except Exception as e:
        logger.warning("Supply-question chain lookup failed for %s: %s", pipe_id, e)
        return None

    alt = chain.get("alternate_feed")
    tail = chain.get("tail_valve_id")
    shutdown_valves = chain.get("shutdown_valves") or []
    downstream = chain.get("downstream_valves_with_roads") or []
    road = chain.get("pipe_road_name") or ""

    # Determine which valve the user is asking about
    asked_valve = valve_id
    if not asked_valve and tail:
        asked_valve = tail  # default to the tail valve if no specific valve named

    lines = [f"**If `{pipe_id}` is shut down** ({road}):"]
    lines.append("")

    if alt:
        # Alternate feed exists — tail valve stays supplied
        alt_pipe = alt["pipe_id"]
        alt_from = alt["from_valve_id"]

        if asked_valve and asked_valve == tail:
            lines.append(
                f"✅ **Yes, `{asked_valve}` would still have water.**"
            )
            lines.append("")
            lines.append(
                f"An alternate feed exists via `{alt_pipe}` from `{alt_from}`. "
                f"When the shutdown chain is isolated (valves {', '.join(f'`{v}`' for v in shutdown_valves)} closed), "
                f"`{tail}` remains supplied through this alternate path."
            )
        elif asked_valve and asked_valve in shutdown_valves:
            lines.append(
                f"⚠️ **`{asked_valve}` is part of the isolation chain** — it will be "
                f"closed during the shutdown, not receiving supply."
            )
            lines.append("")
            lines.append(
                f"However, the tail-end valve `{tail}` stays supplied via alternate "
                f"feed `{alt_pipe}` from `{alt_from}`, so customers downstream of "
                f"`{tail}` are not affected."
            )
        else:
            lines.append(
                f"✅ **An alternate feed exists** via `{alt_pipe}` from `{alt_from}`."
            )
            lines.append("")
            lines.append(
                f"The tail-end valve `{tail}` stays supplied. Customers downstream "
                f"of `{tail}` will not lose water."
            )

        # List who's affected vs not
        affected_in_chain = [v for v in shutdown_valves if v != tail]
        if affected_in_chain:
            lines.append("")
            lines.append(
                f"**Valves that WILL lose supply during isolation:** "
                + ", ".join(f"`{v}`" for v in affected_in_chain)
            )
        lines.append(f"**Valve that stays supplied (via alternate feed):** `{tail}`")

    else:
        # No alternate feed — everyone downstream loses water
        if asked_valve:
            lines.append(
                f"❌ **No, `{asked_valve}` would NOT have water.**"
            )
        else:
            lines.append(
                f"❌ **No alternate feed available.**"
            )
        lines.append("")
        lines.append(
            f"There is no alternate supply path. All valves in the shutdown chain "
            f"({', '.join(f'`{v}`' for v in shutdown_valves)}) and their downstream "
            f"customers will lose water for the duration of the operation."
        )
        if downstream:
            roads = sorted({d.get("road_name", "") for d in downstream if d.get("road_name")})
            if roads:
                lines.append("")
                lines.append(f"**Affected areas:** {', '.join(roads)}")
        lines.append("")
        lines.append(
            "**Mitigation:** Prepare water wagon and water bags for affected customers. "
            "Notify them one week before and again one day before the operation."
        )

    lines.append("")
    lines.append("*Traced live from the network graph.*")
    return "\n".join(lines)


def _answer_valve_turns(valve_id: str) -> Optional[str]:
    from tools.neo4j_tools import get_neighborhood_pipes
    from tools import valve_operation_rules as vr

    rows = get_neighborhood_pipes(valve_id)
    if not rows:
        return None

    # A valve's own diameter isn't stored on every dataset consistently, so infer
    # from the largest connected pipe — the valve must at least match the main it
    # sits on. Stated explicitly in the answer so it's not mistaken for a spec.
    diameters = [r.get("diameter_mm") for r in rows if r.get("diameter_mm")]
    if not diameters:
        return None
    diameter = max(diameters)

    turns = vr.valve_turns(diameter)
    close_min = vr.valve_action_minutes(diameter, "CLOSE")
    open_min = vr.valve_action_minutes(diameter, "OPEN")
    large = diameter > vr.LARGE_VALVE_MM

    lines = [
        f"**`{valve_id}`** — {diameter:.0f} mm "
        f"({'large' if large else 'standard'} valve)",
        "",
        "| | |",
        "|---|---|",
        f"| Handwheel turns | **{turns}** |",
        f"| Time to close | ~{close_min:.0f} min |",
        f"| Time to open | ~{open_min:.0f} min |",
        "",
        f"Turns are `ceil(inches × 2 + 1)`.",
    ]
    if large:
        lines.append(
            f"Valves over {vr.LARGE_VALVE_MM} mm close more slowly than they open — "
            f"the final travel is deliberately slow to limit pressure surge."
        )
    lines += ["", f"*Diameter inferred from the largest main connected to this valve "
                  f"({diameter:.0f} mm). Confirm against the valve marker plate on site.*"]
    return "\n".join(lines)


# ── Entry point ───────────────────────────────────────────────────────────────

def answer_topology_question(user_query: str) -> Optional[str]:
    """Deterministic answer about a named pipe/valve, or None to fall through.

    Only fires when the question names a specific asset AND asks something the
    graph can actually answer. Anything else returns None so the SOP-grounded
    path stays the default.
    """
    q = (user_query or "").lower()
    if not q:
        return None

    # Never answer a live-telemetry request from stored reference data.
    if any(w in q for w in _LIVE_DATA_WORDS):
        logger.info("Declining topology answer for live-data request: %r", user_query)
        return None

    pipe_id, valve_id = _extract_ids(q)
    if not pipe_id and not valve_id:
        return None

    wants_isolation = any(w in q for w in _ISOLATION_WORDS)
    wants_property = any(w in q for w in _PROPERTY_WORDS)
    wants_turns = any(w in q for w in _TURN_WORDS)
    wants_supply = any(w in q for w in _SUPPLY_WORDS)

    try:
        # Turn counts are valve-specific and the most concrete crew question.
        if valve_id and wants_turns:
            return _answer_valve_turns(valve_id)

        # Supply/alternate-feed questions: "if pipe X is down, would valve Y
        # still have water?" — the exact question the LADP lecturers asked.
        if pipe_id and wants_supply:
            return _answer_supply_question(pipe_id, valve_id)

        if pipe_id:
            # "which valves isolate X" is an isolation question even though it
            # also contains the word "valve"; check isolation before properties.
            if wants_isolation:
                return _answer_isolation_chain(pipe_id)
            if wants_property:
                return _answer_pipe_properties(pipe_id)

        if valve_id and wants_property:
            return _answer_valve_turns(valve_id)
    except Exception as e:
        # Never let a graph hiccup break the chat turn — fall through instead.
        logger.warning("Topology answer failed for %r: %s", user_query, e)
        return None

    return None
