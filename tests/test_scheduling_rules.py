"""Unit tests for the deterministic scheduling rules engine (Phase 1, S1.3).

Anchor dates (all 2026):
  - 2026-02-17/18  Chinese New Year  -> blackout 02-10 .. 02-25
  - 2026-06-01     Vesak in-lieu Mon -> blackout 05-25 .. 06-08
  - 2026-06-16     Tuesday (today)   -> clear of any blackout
  - 2026-06-19     Friday            -> clear of any blackout
"""
from datetime import date, datetime

import pytest

from tools import scheduling_rules as sr


# --------------------------------------------------------------------------- #
# Holiday loading + blackout boundaries (R1)
# --------------------------------------------------------------------------- #
def test_holidays_loaded():
    h2026 = sr.load_holidays([2026])
    h2027 = sr.load_holidays([2027])
    assert len(h2026) == 11
    assert len(h2027) == 11


def test_inlieu_dates_present():
    obs = {h.observed for h in sr.load_holidays([2026]) if h.observed}
    assert date(2026, 6, 1) in obs    # Vesak Sun -> Mon
    assert date(2026, 8, 10) in obs   # National Day Sun -> Mon
    assert date(2026, 11, 9) in obs   # Deepavali Sun -> Mon


def test_blackout_boundaries_cny():
    bl = sr.blackout_dates([2026])
    # CNY day 1 = 02-17; 7 days before = 02-10 blocked, 02-09 allowed
    assert date(2026, 2, 10) in bl
    assert date(2026, 2, 9) not in bl
    # CNY day 2 = 02-18; 7 days after = 02-25 blocked, 02-26 allowed
    assert date(2026, 2, 25) in bl
    assert date(2026, 2, 26) not in bl


def test_blackout_includes_inlieu_window():
    bl = sr.blackout_dates([2026])
    # Vesak in-lieu 06-01 -> 06-08 blocked, 06-09 allowed
    assert date(2026, 6, 8) in bl
    assert date(2026, 6, 9) not in bl


# --------------------------------------------------------------------------- #
# Working-day helpers
# --------------------------------------------------------------------------- #
def test_is_working_day():
    assert sr.is_working_day(date(2026, 6, 17)) is True     # Wed
    assert sr.is_working_day(date(2026, 6, 20)) is False     # Sat
    assert sr.is_working_day(date(2026, 6, 21)) is False     # Sun
    assert sr.is_working_day(date(2026, 1, 1)) is False       # New Year holiday
    assert sr.is_working_day(date(2026, 6, 1)) is False       # Vesak in-lieu


def test_working_days_between_excludes_weekend():
    # Wed 06-17 .. Mon 06-22 (exclusive): Thu 18, Fri 19 = 2 working days
    assert sr.working_days_between(date(2026, 6, 17), date(2026, 6, 22)) == 2
    # Wed 06-17 .. Tue 06-23 (exclusive): Thu 18, Fri 19, Mon 22 = 3
    assert sr.working_days_between(date(2026, 6, 17), date(2026, 6, 23)) == 3


# --------------------------------------------------------------------------- #
# validate_planned: R3 (Friday), R1 (blackout), happy path
# --------------------------------------------------------------------------- #
def test_friday_start_rejected():
    res = sr.validate_planned("2026-06-19T08:00:00", "2026-06-19T16:00:00")
    assert res.ok is False
    assert any("R3" in v for v in res.violations)


def test_blackout_date_rejected():
    res = sr.validate_planned("2026-02-17T08:00:00", "2026-02-17T16:00:00")
    assert res.ok is False
    assert any("R1" in v for v in res.violations)


def test_clean_weekday_accepted():
    res = sr.validate_planned("2026-06-17T08:00:00", "2026-06-17T16:00:00")
    assert res.ok is True
    assert res.violations == []


# --------------------------------------------------------------------------- #
# validate_planned: R2 working-day gap
# --------------------------------------------------------------------------- #
def _existing(start, end, **kw):
    base = {"operation_id": "OPS-EXIST", "scheduled_start": start,
            "scheduled_end": end, "status": "PLANNED", "operation_class": "PLANNED"}
    base.update(kw)
    return [base]


def test_gap_too_small_rejected():
    existing = _existing("2026-06-16T08:00:00", "2026-06-17T16:00:00")
    # New op Mon 06-22: only Thu 18 + Fri 19 = 2 working days after existing -> reject
    res = sr.validate_planned("2026-06-22T08:00:00", "2026-06-22T16:00:00", existing)
    assert res.ok is False
    assert any("R2" in v for v in res.violations)


def test_gap_sufficient_accepted():
    existing = _existing("2026-06-16T08:00:00", "2026-06-17T16:00:00")
    # New op Tue 06-23: Thu 18, Fri 19, Mon 22 = 3 working days -> ok
    res = sr.validate_planned("2026-06-23T08:00:00", "2026-06-23T16:00:00", existing)
    assert res.ok is True


def test_overlap_rejected():
    existing = _existing("2026-06-17T08:00:00", "2026-06-17T16:00:00")
    res = sr.validate_planned("2026-06-17T10:00:00", "2026-06-17T14:00:00", existing)
    assert res.ok is False
    assert any("overlaps" in v for v in res.violations)


# --------------------------------------------------------------------------- #
# Emergencies bypass everything (E1)
# --------------------------------------------------------------------------- #
def test_emergency_bypasses_rules():
    # Friday + inside CNY blackout would fail validate_planned, but emergency is ok
    res = sr.validate_emergency("2026-02-20T08:00:00", "2026-02-20T16:00:00")
    assert res.ok is True
    assert res.violations == []


# --------------------------------------------------------------------------- #
# next_valid_slot
# --------------------------------------------------------------------------- #
def test_next_valid_slot_skips_friday_and_weekend():
    # Desired Friday 06-19 -> should roll to Monday 06-22 (Mon-Thu working day)
    slot = sr.next_valid_slot("2026-06-19T09:00:00", duration_hours=4)
    assert slot.weekday() not in (4, 5, 6)   # not Fri/Sat/Sun
    assert slot.date() == date(2026, 6, 22)
    assert slot.time() == datetime(2026, 6, 22, 9, 0).time()


def test_next_valid_slot_skips_blackout():
    # Desired inside CNY blackout (02-17) -> first valid weekday is after 02-25
    slot = sr.next_valid_slot("2026-02-17T09:00:00", duration_hours=4)
    assert slot.date() > date(2026, 2, 25)
    assert sr.validate_planned(slot, slot.replace(hour=13)).ok


# --------------------------------------------------------------------------- #
# find_displaced (E2)
# --------------------------------------------------------------------------- #
def test_find_displaced_returns_overlapping_planned():
    existing = _existing("2026-07-06T08:00:00", "2026-07-06T16:00:00",
                         operation_id="OPS-PLANNED-1")
    displaced = sr.find_displaced("2026-07-06T10:00:00", "2026-07-06T12:00:00", existing)
    assert len(displaced) == 1
    assert displaced[0]["operation_id"] == "OPS-PLANNED-1"


def test_find_displaced_ignores_non_overlapping():
    existing = _existing("2026-07-06T08:00:00", "2026-07-06T16:00:00")
    displaced = sr.find_displaced("2026-07-20T10:00:00", "2026-07-20T12:00:00", existing)
    assert displaced == []


def test_find_displaced_ignores_other_emergency():
    existing = _existing("2026-07-06T08:00:00", "2026-07-06T16:00:00",
                         operation_class="EMERGENCY")
    displaced = sr.find_displaced("2026-07-06T10:00:00", "2026-07-06T12:00:00", existing)
    assert displaced == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
