"""Deterministic answers about how THIS system works.

Why this module exists
----------------------
Phase 13 made `general_response_node` answer every general question from the
ingested SOP corpus, which correctly stopped content hallucination. But it left
the chat path with the 4 SOP documents as its ONLY knowledge source, so
questions whose answers are already implemented in code came back as
"not part of the documented procedure". A probe run (scripts/probe_chatbot.py)
found 10 such questions, including:

    "How do you calculate how long a shutdown will take?"  -> estimate_duration_hours()
    "Why can't I schedule the week before Chinese New Year?" -> rule R1
    "What happens when an emergency overlaps planned ops?"   -> rules E1-E3
    "How do I mark a step as done?"                          -> the crew checklist

Adding documents cannot fix those — the knowledge isn't missing, it's unreachable.

Design
------
Every answer here is DETERMINISTIC text with no LLM involved, and every number is
interpolated from the real constant in the engine that implements it. If
BLACKOUT_RADIUS_DAYS or MINUTES_PER_VALVE changes, these answers change with it,
so they cannot drift out of sync with behaviour. Same philosophy as
format_sop_walkthrough(): if it must be correct, don't let a model write it.

Matching is deliberately CONSERVATIVE. A question is only claimed when it clearly
asks about system mechanics; anything ambiguous falls through (returns None) to
the SOP-grounded path, which remains the default. Over-claiming here would
silently shadow the real corpus, which is the worse failure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from tools import scheduling_rules as sr
from tools import valve_operation_rules as vr


# ── Answer builders ───────────────────────────────────────────────────────────
# Each returns finished Markdown. Numbers come from the engine constants, never
# hardcoded prose, so the text and the behaviour can't disagree.

def _answer_blackout_rule() -> str:
    d = sr.BLACKOUT_RADIUS_DAYS
    return (
        f"**Festive blackout (rule R1).** A *planned* operation cannot fall within "
        f"±{d} calendar days of any Singapore public holiday. The window is measured "
        f"from both the gazetted date and its in-lieu observed date where one applies, "
        f"so a holiday that falls on a Sunday blocks around the following Monday too.\n\n"
        f"Chinese New Year is two consecutive holidays, so its combined blackout is "
        f"wider than a single-day holiday's.\n\n"
        f"If you request a blacked-out date I'll tell you which rule it breaks and "
        f"offer the earliest date that satisfies R1, R2 and R3.\n\n"
        f"*Emergency operations bypass this rule entirely.*"
    )


def _answer_gap_rule() -> str:
    n = sr.MIN_WORKING_DAYS_GAP
    return (
        f"**Working-day gap (rule R2).** At least **{n} working days** must be clear "
        f"between one operation and the next, so officers aren't scheduled back-to-back. "
        f"A working day is Monday–Friday excluding public holidays, which means a gap "
        f"spanning a holiday needs more calendar days to satisfy the same rule.\n\n"
        f"Directly overlapping operations on the same pipe are rejected outright.\n\n"
        f"*Emergency operations bypass this rule entirely.*"
    )


def _answer_friday_rule() -> str:
    return (
        "**No Friday start (rule R3).** A *planned* operation may not begin on a Friday, "
        "so an over-running job doesn't get stranded across the weekend. If you ask for a "
        "Friday I'll flag R3 and propose the following Monday instead.\n\n"
        "*Emergency operations bypass this rule entirely.*"
    )


def _answer_all_rules() -> str:
    return (
        "**Scheduling rules for planned operations**\n\n"
        f"| Rule | Requirement |\n"
        f"|------|-------------|\n"
        f"| R1 | No operation within ±{sr.BLACKOUT_RADIUS_DAYS} calendar days of a "
        f"public holiday (including in-lieu dates) |\n"
        f"| R2 | At least {sr.MIN_WORKING_DAYS_GAP} clear working days before the next "
        f"scheduled operation |\n"
        f"| R3 | An operation may not start on a Friday |\n\n"
        "All three are checked deterministically, so a date is either valid or it isn't — "
        "no judgement call. When a request fails, I name the rule(s) broken and offer the "
        "earliest compliant slot.\n\n"
        "**Emergency operations bypass R1, R2 and R3** and can be scheduled at any time."
    )


def _answer_duration_calc() -> str:
    mins = sr.MINUTES_PER_VALVE
    setup = sr.SETUP_HOURS
    start = sr.DAILY_START_HOUR
    hours = sr.DAILY_WORK_HOURS
    end = int(start + hours)
    return (
        "**How operation duration is calculated**\n\n"
        f"Effort is sized from the valve chain, not estimated:\n\n"
        f"- **{mins:.0f} minutes per valve** in the shutdown chain (operate + verify)\n"
        f"- **+ {setup:.0f} hour** fixed setup/mobilisation per operation\n\n"
        f"That total effort is then laid across working days in a fixed daily window of "
        f"**{start:02d}:00–{end:02d}:00** ({hours:.0f} hours/day). If the work doesn't fit "
        f"in one day it spills to the next *working* day, skipping weekends and public "
        f"holidays — which is how the end date is derived rather than asked for.\n\n"
        f"Valve-level timing is finer than the flat per-valve figure where diameters are "
        f"known: handwheel turns are `ceil(inches × 2 + 1)`, and large valves "
        f"(> {vr.LARGE_VALVE_MM} mm) close more slowly than they open, plus "
        f"{vr.DAILY_TRAVEL_MINUTES:.0f} minutes travel between consecutive valves."
    )


def _answer_working_window() -> str:
    start = sr.DAILY_START_HOUR
    hours = sr.DAILY_WORK_HOURS
    end = int(start + hours)
    return (
        f"**Daily working window.** Operations run **{start:02d}:00–{end:02d}:00** "
        f"({hours:.0f} hours) on working days only. You don't specify times — you give a "
        f"start date and the system computes the end date by laying the operation's total "
        f"effort across working days, skipping weekends and public holidays."
    )


def _answer_emergency_behaviour() -> str:
    return (
        "**Emergency operations**\n\n"
        "- **Bypass all scheduling rules** (R1 holiday blackout, R2 working-day gap, "
        "R3 no-Friday-start) — an emergency can be scheduled at any time.\n"
        "- **Preempt overlapping planned operations.** Any planned operation whose window "
        "overlaps the emergency is displaced.\n"
        "- **Each displaced operation gets a proposed new slot** — the earliest date that "
        "satisfies R1–R3 — which is shown to you for confirmation before anything is "
        "rebooked. Nothing moves silently.\n\n"
        "**Two emergencies overlapping:** because both legitimately bypass the rules, the "
        "system won't pick for you. It shows both windows and asks which runs first, then "
        "sequences the other immediately after your choice."
    )


def _answer_crew_flagging() -> str:
    return (
        "**Raising a problem from site.** On the crew checklist, set the step's status "
        "dropdown to **🚩 Flagged**. A note box appears — describe what's happening and "
        "press **Send Flag**.\n\n"
        "That immediately surfaces to the ops planning team: the operation shows a 🚩 on "
        "the operations calendar, and opening that day shows your note alongside the step "
        "it relates to. You can also use **Notes & Updates** at the bottom of the "
        "checklist for anything not tied to a specific step.\n\n"
        "This replaces reporting by chat message — it's attached to the operation record, "
        "so nothing gets lost in a thread."
    )


def _answer_crew_marking_steps() -> str:
    return (
        "**Marking checklist steps.** Each step has a status dropdown with three options:\n\n"
        "| Status | Use it when |\n"
        "|--------|-------------|\n"
        "| ⬜ Pending | Not started (the default) |\n"
        "| ✅ Done | Step completed as written |\n"
        "| 🚩 Flagged | Something is wrong — a note box opens for you to explain |\n\n"
        "The progress bar at the top updates as you go, and the ops planning team sees the "
        "same completion percentage on their operations calendar."
    )


def _answer_crew_link() -> str:
    return (
        "**Getting the checklist to the crew.** Once an operation is confirmed and booked, "
        "the booking message includes a **Share with crew** link. You can also retrieve it "
        "later from the **Ops Calendar**: click the operation's day and use **🔗 Get Crew "
        "Link** (copies it) or **👷 Open Crew View**.\n\n"
        "The link opens a mobile-friendly checklist with the valve sequence, so it can be "
        "sent straight to whoever is on site. Anyone with the link can use it — there's no "
        "separate login.\n\n"
        "A printable **isolation report (PDF)** is available from the same places, "
        "including on the crew page itself."
    )


def _answer_capabilities() -> str:
    return (
        "**What I can help with**\n\n"
        "1. **Plan an operation** — a shutdown, inspection or maintenance job on a specific "
        "pipe from a specific start date. I check the network topology, apply the "
        "scheduling rules, compute the working window, and produce the valve sequence. "
        "You confirm before anything is booked.\n"
        "2. **Answer calendar questions** — what's already booked in a given month, and "
        "whether a date is available.\n"
        "3. **Explain how the system works** — the scheduling rules, how duration is "
        "calculated, how the crew checklist works.\n"
        "4. **Answer SOP questions** — grounded in the documented isolation procedures. "
        "If something isn't in those documents I'll say so rather than guess.\n\n"
        "Things I genuinely cannot do: read images or file attachments, show live pressure "
        "or valve telemetry, dispatch resources, or approve an operation on someone's "
        "behalf. If you ask, I'll tell you plainly rather than improvise."
    )


# ── Topic registry ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Topic:
    """A matchable system-knowledge topic.

    require: every group must contribute >=1 term (AND across groups, OR within).
             This is what keeps matching tight — a bare mention of "valve" or
             "emergency" is never enough on its own.
    exclude: any hit here vetoes the match, used to hand a question back to the
             SOP corpus when it's really asking about field procedure.
    """
    name: str
    require: tuple[tuple[str, ...], ...]
    build: Callable[[], str]
    exclude: tuple[str, ...] = ()


_SCHEDULING_WORDS = ("schedul", "book", "plan", "date", "when", "calendar", "slot", "plann")

_TOPICS: tuple[Topic, ...] = (
    # ── Scheduling rules ──
    Topic(
        name="blackout_rule",
        require=(
            ("holiday", "festive", "chinese new year", "cny", "deepavali", "christmas",
             "hari raya", "vesak", "national day", "blackout"),
            _SCHEDULING_WORDS + ("rule", "why", "cannot", "can't", "block", "avoid", "near"),
        ),
        build=_answer_blackout_rule,
    ),
    Topic(
        name="gap_rule",
        require=(
            ("gap", "back-to-back", "back to back", "consecutive", "between operations",
             "working day", "working days", "rest"),
            _SCHEDULING_WORDS + ("rule", "why", "need", "require", "many", "much"),
        ),
        build=_answer_gap_rule,
    ),
    Topic(
        name="friday_rule",
        require=(
            ("friday",),
            _SCHEDULING_WORDS + ("rule", "why", "cannot", "can't", "start", "shut"),
        ),
        build=_answer_friday_rule,
    ),
    Topic(
        name="all_rules",
        require=(
            ("scheduling rule", "scheduling rules", "what rules", "which rules",
             "rules apply", "rules for scheduling", "r1", "r2", "r3"),
        ),
        build=_answer_all_rules,
    ),
    # ── Duration / window ──
    Topic(
        name="duration_calc",
        require=(
            ("how long", "duration", "how much time", "estimate", "calculat", "sizing",
             "size the", "end date"),
            ("shutdown", "operation", "isolation", "job", "work", "take", "takes",
             "computed", "compute", "derive"),
        ),
        # A crew member asking how long a *specific valve* takes to turn is a
        # field-mechanics question for the valve SOP, not a scheduling one.
        exclude=("turn", "handwheel", "spindle", "torque"),
        build=_answer_duration_calc,
    ),
    Topic(
        name="working_window",
        require=(
            ("working window", "daily window", "what time", "what hours", "start time",
             "10:00", "16:00", "working hours"),
            ("operation", "work", "day", "shutdown", "window", "hours", "time"),
        ),
        build=_answer_working_window,
    ),
    # ── Emergency behaviour ──
    Topic(
        name="emergency_behaviour",
        require=(
            ("emergency", "emergencies", "burst", "urgent"),
            ("overlap", "clash", "conflict", "displace", "preempt", "priority",
             "same time", "bypass", "rule", "rules", "what happens", "two", "reschedul",
             "affect"),
        ),
        build=_answer_emergency_behaviour,
    ),
    # ── Crew app features ──
    Topic(
        name="crew_flagging",
        require=(
            ("flag", "flagged", "problem", "issue", "complication", "cannot complete",
             "can't complete", "report", "contact", "escalat", "stuck on a step"),
            ("step", "steps", "checklist", "crew", "site", "who do i", "how do i",
             "notify", "planner", "planning team", "supervisor"),
        ),
        # Physical valve problems belong to the valve/troubleshooting corpus, not
        # to an explanation of the reporting UI.
        exclude=("valve is stuck", "will not turn", "won't turn", "leaking", "spraying",
                 "air lock", "dirty water", "torque"),
        build=_answer_crew_flagging,
    ),
    Topic(
        name="crew_marking_steps",
        require=(
            ("mark", "marking", "tick", "check off", "checkbox", "complete a step",
             "status", "done"),
            ("step", "steps", "checklist", "progress", "crew"),
        ),
        build=_answer_crew_marking_steps,
    ),
    Topic(
        name="crew_link",
        require=(
            ("crew link", "share", "send", "give", "get the", "how do i get",
             "link", "hand over", "pdf", "report"),
            ("crew", "field", "site", "team", "operator", "checklist", "sequence",
             "ground"),
        ),
        build=_answer_crew_link,
    ),
    # ── Capabilities ──
    Topic(
        name="capabilities",
        require=(
            ("what can you", "what do you do", "how can you help", "what are you able",
             "your capabilities", "help me with"),
        ),
        build=_answer_capabilities,
    ),
)


def _norm(text: str) -> str:
    """Lowercase and normalise typographic punctuation.

    The apostrophe matters: users and LLM-echoed text both produce U+2019, so a
    matcher written with a straight quote silently misses "can't". Same
    false-negative class as the Phase 12 guardrail bug.
    """
    t = (text or "").lower()
    for src, dst in (("\u2019", "'"), ("\u2018", "'"), ("\u02bc", "'"),
                     ("\u2014", " "), ("\u2013", " ")):
        t = t.replace(src, dst)
    return re.sub(r"\s+", " ", t)


def _matches(topic: Topic, query: str) -> bool:
    if any(x in query for x in topic.exclude):
        return False
    return all(any(term in query for term in group) for group in topic.require)


def match_topic(user_query: str) -> Optional[str]:
    """Return the name of the matching topic, or None. Exposed for tests/debugging."""
    q = _norm(user_query)
    if not q:
        return None
    for topic in _TOPICS:
        if _matches(topic, q):
            return topic.name
    return None


def answer_system_question(user_query: str) -> Optional[str]:
    """Deterministic answer about how this system works, or None to fall through.

    None is the common case and the safe default: unmatched questions continue to
    the SOP-grounded retrieval path.
    """
    q = _norm(user_query)
    if not q:
        return None
    for topic in _TOPICS:
        if _matches(topic, q):
            return topic.build()
    return None


def all_topic_names() -> list[str]:
    """Topic names in match order (used by tests to assert coverage)."""
    return [t.name for t in _TOPICS]


def all_answers() -> dict[str, str]:
    """Every rendered answer, for tests that assert invariants across all of them."""
    return {t.name: t.build() for t in _TOPICS}
