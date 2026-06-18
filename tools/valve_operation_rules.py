"""Deterministic valve-operation timing (see data/seed/sop_documents/valve_operation_sop.md).

Computes how long it takes to open/close a valve from its diameter, and the total
duration of an isolation operation (closing the shutdown chain + the re-feed /
reverse-isolation opens when an alternate feed exists), including travel between
valves. No LLM — pure arithmetic, so the schedule end time is reproducible.
"""
from __future__ import annotations

import math
from typing import Any, Literal

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


def chain_valve_actions(chain: dict[str, Any]) -> list[tuple[float, str]]:
    """Map an SOP shutdown chain to its (diameter_mm, action) valve operations.

    CLOSE every shutdown-chain valve (isolation); if an alternate feed exists,
    OPEN the alternate-feed valve and one valve per reverse pair (re-feed /
    reverse-isolation). Diameters come from chain['valve_diameters'].
    """
    diam = chain.get("valve_diameters") or {}

    def d(vid: str) -> float:
        return diam.get(vid, _DEFAULT_DIAMETER_MM)

    actions: list[tuple[float, str]] = [
        (d(vid), "CLOSE") for vid in chain.get("shutdown_valves", [])
    ]

    alt = chain.get("alternate_feed")
    if alt:
        actions.append((d(alt["from_valve_id"]), "OPEN"))
        for pair in chain.get("reverse_checks", []):
            actions.append((d(pair["from_valve"]), "OPEN"))

    return actions


def operation_duration_hours(
    chain: dict[str, Any],
    travel_minutes: float = DAILY_TRAVEL_MINUTES,
) -> float:
    """Total isolation-operation duration in hours for an SOP shutdown chain."""
    return operation_minutes(chain_valve_actions(chain), travel_minutes) / 60.0
