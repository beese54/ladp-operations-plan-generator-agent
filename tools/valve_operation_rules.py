"""Deterministic valve-operation timing (see data/seed/sop_documents/valve_operation_sop.md).

Computes how long it takes to open/close a valve from its diameter, and the total
duration of an isolation operation (closing the shutdown chain + the re-feed /
reverse-isolation opens when an alternate feed exists), including travel between
valves. No LLM — pure arithmetic, so the schedule end time is reproducible.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Optional

MM_PER_INCH = 25.4
LARGE_VALVE_MM = 500           # > 500 mm uses the slow closing tail
DAILY_TRAVEL_MINUTES = 20.0    # officer travel between consecutive valves
_DEFAULT_DIAMETER_MM = 300     # fallback when a valve diameter is unknown

Action = Literal["OPEN", "CLOSE"]


def valve_turns(diameter_mm: float) -> int:
    """Handwheel turns for a valve: ceil(inches × 2 + 1)."""
    return math.ceil(diameter_mm / MM_PER_INCH * 2 + 1)


def valve_action_minutes(diameter_mm: float, action: str) -> float:
    """Minutes to OPEN or CLOSE one valve, per the phase rates in the SOP."""
    t = valve_turns(diameter_mm)
    if action.upper() == "OPEN":
        return 0.3 * t * 2 + 0.7 * t * 1          # 1.3T (all sizes)
    if diameter_mm <= LARGE_VALVE_MM:
        return 0.7 * t * 1 + 0.3 * t * 2          # 1.3T (small close)
    return 0.7 * t * 1 + 0.3 * t * 4              # 1.9T (large close)


def operation_minutes(
    actions: list[tuple[float, str]],
    travel_minutes: float = DAILY_TRAVEL_MINUTES,
) -> float:
    """Total minutes for a sequence of (diameter_mm, action), with (K-1) travels."""
    if not actions:
        return 0.0
    work = sum(valve_action_minutes(d, a) for d, a in actions)
    return work + (len(actions) - 1) * travel_minutes


@dataclass(frozen=True)
class ValveStep:
    """A single identified, timed valve action within an isolation operation."""
    seq: int                      # 1-based order within the operation
    valve_id: str
    action: Action                 # "OPEN" | "CLOSE"
    diameter_mm: float
    pipe_id: Optional[str]         # contextual pipe this action closes/opens, if any
    action_minutes: float
    travel_minutes: float = 0.0    # travel consumed immediately before this step (0.0 for seq=1)

    @property
    def total_minutes(self) -> float:
        return self.action_minutes + self.travel_minutes


def chain_valve_steps(
    chain: dict[str, Any],
    travel_minutes: float = DAILY_TRAVEL_MINUTES,
) -> list[ValveStep]:
    """Map an SOP shutdown chain to its per-step valve operations, with identity.

    Same CLOSE-then-OPEN sequencing as chain_valve_actions (do not re-derive it
    elsewhere — chain_valve_actions is now a thin projection of this function):
    CLOSE every shutdown-chain valve (isolation), in order; if an alternate feed
    exists, OPEN the alternate-feed valve, then OPEN one valve per reverse pair
    (re-feed / reverse-isolation), keyed by `pair['from_valve']` to match the
    engine that already sizes every real booking.

    Pipe mapping for CLOSE steps: shutdown_valves[i] is paired with the pipe it
    is the from-valve of (shutdown_pipes[i]); the tail valve (last CLOSE) has no
    following pipe, so pipe_id=None. OPEN steps use the alt-feed/reverse-check
    pipe_id directly from the chain data.
    """
    diam = chain.get("valve_diameters") or {}

    def d(vid: str) -> float:
        return diam.get(vid, _DEFAULT_DIAMETER_MM)

    shutdown_valves = chain.get("shutdown_valves", [])
    shutdown_pipes = chain.get("shutdown_pipes", [])

    raw: list[tuple[str, Action, Optional[str]]] = [
        (vid, "CLOSE", shutdown_pipes[i] if i < len(shutdown_pipes) else None)
        for i, vid in enumerate(shutdown_valves)
    ]

    alt = chain.get("alternate_feed")
    if alt:
        raw.append((alt["from_valve_id"], "OPEN", alt.get("pipe_id")))
        for pair in chain.get("reverse_checks", []):
            raw.append((pair["from_valve"], "OPEN", pair.get("pipe_id")))

    return [
        ValveStep(
            seq=i + 1,
            valve_id=vid,
            action=action,
            diameter_mm=d(vid),
            pipe_id=pipe_id,
            action_minutes=valve_action_minutes(d(vid), action),
            travel_minutes=travel_minutes if i > 0 else 0.0,
        )
        for i, (vid, action, pipe_id) in enumerate(raw)
    ]


def chain_valve_actions(chain: dict[str, Any]) -> list[tuple[float, str]]:
    """Map an SOP shutdown chain to its (diameter_mm, action) valve operations.

    CLOSE every shutdown-chain valve (isolation); if an alternate feed exists,
    OPEN the alternate-feed valve and one valve per reverse pair (re-feed /
    reverse-isolation). Diameters come from chain['valve_diameters'].

    Thin projection of chain_valve_steps — see its docstring for the sequencing.
    """
    return [(s.diameter_mm, s.action) for s in chain_valve_steps(chain)]


def operation_duration_hours(
    chain: dict[str, Any],
    travel_minutes: float = DAILY_TRAVEL_MINUTES,
) -> float:
    """Total isolation-operation duration in hours for an SOP shutdown chain."""
    return operation_minutes(chain_valve_actions(chain), travel_minutes) / 60.0
