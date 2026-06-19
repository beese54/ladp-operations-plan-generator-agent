"""Deterministic scheduling rules engine for water-pipe shutdown operations.

No LLM. Pure stdlib date math, so the agent never hallucinates a schedule and
every rule is unit-testable. Implements (for PLANNED operations):

  R1 - holiday blackout: no op within +/-7 calendar days of any SG public
       holiday (actual OR in-lieu observed date).
  R2 - working-day gap: >=3 working days must be clear between an operation and
       its neighbours (no back-to-back; officer rest). Overlaps are rejected.
  R3 - no-Friday-start: an op may not START on a Friday.

EMERGENCY operations bypass R1/R2/R3 (see validate_emergency / find_displaced).

Holiday data is loaded from data/seed/sg_public_holidays.json (editable config).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Union

# tools/ lives one level under the project root.
_DEFAULT_HOLIDAYS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "seed" / "sg_public_holidays.json"
)

BLACKOUT_RADIUS_DAYS = 7
MIN_WORKING_DAYS_GAP = 3
FRIDAY = 4  # date.weekday(): Mon=0 .. Sun=6
ACTIVE_STATUSES = {"PLANNED", "IN_PROGRESS"}

# Operations work a fixed daily window; total effort is derived from the valve
# chain and laid out across working days (see layout_working_window).
DAILY_START_HOUR = 10        # operations start at 10:00 each working day
DAILY_WORK_HOURS = 6.0       # 10:00-16:00
MINUTES_PER_VALVE = 45.0     # effort to operate + verify one valve
SETUP_HOURS = 1.0            # fixed per-operation setup/mobilisation

DateLike = Union[str, date, datetime]


@dataclass(frozen=True)
class Holiday:
    name: str
    date: date
    observed: Optional[date]

    def observance_dates(self) -> list[date]:
        """The actual date plus the in-lieu date, if any."""
        out = [self.date]
        if self.observed:
            out.append(self.observed)
        return out


@dataclass
class ValidationResult:
    ok: bool
    violations: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def _to_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value).date()
    raise TypeError(f"Cannot coerce {value!r} to date")


def _to_datetime(value: DateLike) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"Cannot coerce {value!r} to datetime")


# --------------------------------------------------------------------------- #
# Holiday loading (cached)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=8)
def _load_raw(path: str) -> tuple[Holiday, ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    holidays: list[Holiday] = []
    for year, entries in data.items():
        if year.startswith("_"):  # skip _comment etc.
            continue
        for e in entries:
            holidays.append(
                Holiday(
                    name=e["name"],
                    date=_to_date(e["date"]),
                    observed=_to_date(e["observed"]) if e.get("observed") else None,
                )
            )
    return tuple(sorted(holidays, key=lambda h: h.date))


def load_holidays(
    years: Optional[Iterable[Union[str, int]]] = None,
    path: Optional[str] = None,
) -> list[Holiday]:
    """Return holidays, optionally filtered to specific years."""
    holidays = _load_raw(str(path or _DEFAULT_HOLIDAYS_PATH))
    if years is None:
        return list(holidays)
    wanted = {int(y) for y in years}
    return [h for h in holidays if h.date.year in wanted]


@lru_cache(maxsize=8)
def _observance_dates(path: str) -> frozenset[date]:
    """All actual + in-lieu holiday dates (used for working-day calculations)."""
    out: set[date] = set()
    for h in _load_raw(path):
        out.update(h.observance_dates())
    return frozenset(out)


@lru_cache(maxsize=8)
def _blackout_set(path: str) -> frozenset[date]:
    """Every date within +/-7 days of any holiday observance date."""
    out: set[date] = set()
    for d in _observance_dates(path):
        for delta in range(-BLACKOUT_RADIUS_DAYS, BLACKOUT_RADIUS_DAYS + 1):
            out.add(d + timedelta(days=delta))
    return frozenset(out)


def blackout_dates(
    years: Optional[Iterable[Union[str, int]]] = None,
    path: Optional[str] = None,
) -> set[date]:
    """Set of all blackout dates (+/-7d around every holiday), optionally per-year."""
    full = _blackout_set(str(path or _DEFAULT_HOLIDAYS_PATH))
    if years is None:
        return set(full)
    wanted = {int(y) for y in years}
    return {d for d in full if d.year in wanted}


# --------------------------------------------------------------------------- #
# Working-day helpers
# --------------------------------------------------------------------------- #
def is_working_day(value: DateLike, path: Optional[str] = None) -> bool:
    """Mon-Fri that is not a public holiday (actual or in-lieu)."""
    d = _to_date(value)
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return d not in _observance_dates(str(path or _DEFAULT_HOLIDAYS_PATH))


def working_days_between(
    start: DateLike, end: DateLike, path: Optional[str] = None
) -> int:
    """Count working days strictly between start and end (both exclusive)."""
    d1, d2 = _to_date(start), _to_date(end)
    if d2 <= d1:
        return 0
    count = 0
    cur = d1 + timedelta(days=1)
    while cur < d2:
        if is_working_day(cur, path):
            count += 1
        cur += timedelta(days=1)
    return count


# --------------------------------------------------------------------------- #
# Existing-operation helpers
# --------------------------------------------------------------------------- #
def _active_ops(existing_ops: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for op in existing_ops or []:
        status = (op.get("status") or "PLANNED").upper()
        if status in ACTIVE_STATUSES:
            out.append(op)
    return out


def _op_window(op: dict[str, Any]) -> tuple[datetime, datetime]:
    return _to_datetime(op["scheduled_start"]), _to_datetime(op["scheduled_end"])


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and a_end > b_start


# --------------------------------------------------------------------------- #
# Public rule API
# --------------------------------------------------------------------------- #
def validate_planned(
    start: DateLike,
    end: DateLike,
    existing_ops: Optional[Iterable[dict[str, Any]]] = None,
    path: Optional[str] = None,
) -> ValidationResult:
    """Validate a PLANNED operation window against R1, R2, R3."""
    start_dt, end_dt = _to_datetime(start), _to_datetime(end)
    violations: list[str] = []

    # R3 - no Friday start
    if start_dt.weekday() == FRIDAY:
        violations.append("R3: operation may not start on a Friday.")

    # R1 - holiday blackout (any day the op spans)
    blackout = _blackout_set(str(path or _DEFAULT_HOLIDAYS_PATH))
    span = start_dt.date()
    while span <= end_dt.date():
        if span in blackout:
            violations.append(
                f"R1: {span.isoformat()} is within 7 days of a public holiday."
            )
            break
        span += timedelta(days=1)

    # R2 - >=3 working days clear of every neighbour; no overlap
    for op in _active_ops(existing_ops or []):
        o_start, o_end = _op_window(op)
        oid = op.get("operation_id", "?")
        if _overlaps(start_dt, end_dt, o_start, o_end):
            violations.append(f"R2: overlaps existing operation {oid}.")
            continue
        if o_end <= start_dt:  # neighbour before
            gap = working_days_between(o_end.date(), start_dt.date(), path)
            if gap < MIN_WORKING_DAYS_GAP:
                violations.append(
                    f"R2: only {gap} working day(s) after operation {oid} "
                    f"(need >= {MIN_WORKING_DAYS_GAP})."
                )
        else:  # neighbour after
            gap = working_days_between(end_dt.date(), o_start.date(), path)
            if gap < MIN_WORKING_DAYS_GAP:
                violations.append(
                    f"R2: only {gap} working day(s) before operation {oid} "
                    f"(need >= {MIN_WORKING_DAYS_GAP})."
                )

    return ValidationResult(ok=not violations, violations=violations)


def validate_emergency(*_args, **_kwargs) -> ValidationResult:
    """Emergencies bypass all scheduling rules (E1)."""
    return ValidationResult(ok=True, violations=[])


def next_valid_slot(
    desired_start: DateLike,
    duration_hours: float,
    existing_ops: Optional[Iterable[dict[str, Any]]] = None,
    path: Optional[str] = None,
    max_lookahead_days: int = 730,
) -> datetime:
    """Earliest start >= desired_start that satisfies R1-R3.

    Only proposes working-day, non-Friday starts (Mon-Thu), since an operation
    should not begin on a weekend, holiday, or Friday.
    """
    start_dt = _to_datetime(desired_start)
    candidate = start_dt
    for _ in range(max_lookahead_days):
        if (
            is_working_day(candidate, path)
            and candidate.weekday() != FRIDAY
        ):
            end = candidate + timedelta(hours=duration_hours)
            if validate_planned(candidate, end, existing_ops, path).ok:
                return candidate
        # advance to next day at the same time-of-day
        next_day = (candidate + timedelta(days=1)).date()
        candidate = datetime.combine(next_day, start_dt.time())
    raise ValueError(
        f"No valid slot found within {max_lookahead_days} days of {desired_start}."
    )


def find_displaced(
    emergency_start: DateLike,
    emergency_end: DateLike,
    existing_ops: Optional[Iterable[dict[str, Any]]] = None,
    path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return active PLANNED operations that overlap an emergency window (E2)."""
    e_start, e_end = _to_datetime(emergency_start), _to_datetime(emergency_end)
    displaced = []
    for op in _active_ops(existing_ops or []):
        if (op.get("operation_class") or "PLANNED").upper() != "PLANNED":
            continue
        o_start, o_end = _op_window(op)
        if _overlaps(e_start, e_end, o_start, o_end):
            displaced.append(op)
    return displaced


def find_conflicting_emergencies(
    emergency_start: DateLike,
    emergency_end: DateLike,
    existing_ops: Optional[Iterable[dict[str, Any]]] = None,
    path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Active EMERGENCY operations that overlap the given window.

    Two emergencies cannot be auto-deconflicted by rule (both bypass R1-R3), so
    these are surfaced for the operator to choose the running order.
    """
    e_start, e_end = _to_datetime(emergency_start), _to_datetime(emergency_end)
    out = []
    for op in _active_ops(existing_ops or []):
        if (op.get("operation_class") or "PLANNED").upper() != "EMERGENCY":
            continue
        o_start, o_end = _op_window(op)
        if _overlaps(e_start, e_end, o_start, o_end):
            out.append(op)
    return out


# --------------------------------------------------------------------------- #
# Duration estimation + working-day layout
# --------------------------------------------------------------------------- #
def estimate_duration_hours(
    valve_count: int,
    minutes_per_valve: float = MINUTES_PER_VALVE,
    setup_hours: float = SETUP_HOURS,
) -> float:
    """Total effort hours for an operation, from the number of valves to operate.

    duration = setup + valve_count * minutes_per_valve. The number of valves comes
    from the deterministic shutdown chain (build_sop_chain_data -> shutdown_valves).
    """
    return setup_hours + max(valve_count, 0) * (minutes_per_valve / 60.0)


def layout_working_window(
    start: DateLike,
    duration_hours: float,
    path: Optional[str] = None,
) -> tuple[datetime, datetime, list[date]]:
    """Lay an operation's effort out across working days at a fixed daily window.

    Each working day contributes DAILY_WORK_HOURS (10:00-16:00). Effort that does
    not fit before 16:00 rolls onto the next working day; weekends and public
    holidays are skipped. The requested start rolls forward to the first working
    day on/after it, so the window always begins on a working day.

    Returns (start_dt, end_dt, working_days) where start_dt is the first working
    day at 10:00 and end_dt is the last day at 10:00 + leftover hours (<= 16:00).
    """
    d = _to_date(start)
    while not is_working_day(d, path):
        d += timedelta(days=1)

    start_dt = datetime.combine(d, time(DAILY_START_HOUR))
    remaining = max(float(duration_hours), 0.0)
    working_days: list[date] = []
    cur = d
    last_end = start_dt

    while True:
        if is_working_day(cur, path):
            working_days.append(cur)
            day_start = datetime.combine(cur, time(DAILY_START_HOUR))
            chunk = min(remaining, DAILY_WORK_HOURS)
            last_end = day_start + timedelta(hours=chunk)
            remaining -= chunk
            if remaining <= 1e-9:
                break
        cur += timedelta(days=1)

    return start_dt, last_end, working_days


def next_valid_layout_start(
    desired_start: DateLike,
    duration_hours: float,
    existing_ops: Optional[Iterable[dict[str, Any]]] = None,
    path: Optional[str] = None,
    max_lookahead_days: int = 730,
) -> date:
    """Earliest working, non-Friday start date whose laid-out window passes R1-R3.

    The layout-aware analogue of next_valid_slot: it lays the duration out from
    each candidate start and validates the resulting multi-day window.
    """
    d = _to_date(desired_start)
    for _ in range(max_lookahead_days):
        if is_working_day(d, path) and d.weekday() != FRIDAY:
            s_dt, e_dt, _days = layout_working_window(d, duration_hours, path)
            if validate_planned(s_dt, e_dt, existing_ops, path).ok:
                return d
        d += timedelta(days=1)
    raise ValueError(
        f"No valid layout start within {max_lookahead_days} days of {desired_start}."
    )


def window_working_hours(start: DateLike, end: DateLike, path: Optional[str] = None) -> float:
    """Effort hours implied by an existing window: working days it spans
    (inclusive) x DAILY_WORK_HOURS. Used to re-size a booked op when moving it."""
    d1, d2 = _to_date(start), _to_date(end)
    if d2 < d1:
        d1, d2 = d2, d1
    count = 0
    cur = d1
    while cur <= d2:
        if is_working_day(cur, path):
            count += 1
        cur += timedelta(days=1)
    return max(count, 1) * DAILY_WORK_HOURS
