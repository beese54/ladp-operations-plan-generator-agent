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


# --------------------------------------------------------------------------- #
# Duration estimation + working-day layout (Phase 3)
# --------------------------------------------------------------------------- #
def test_estimate_duration_hours():
    # setup 1h + 4 valves * 45min
    assert sr.estimate_duration_hours(4) == pytest.approx(1.0 + 4 * 0.75)
    assert sr.estimate_duration_hours(0) == pytest.approx(sr.SETUP_HOURS)


def test_layout_single_day_fits_in_window():
    # 2.5h on a Monday -> 10:00..12:30, one working day
    start_dt, end_dt, days = sr.layout_working_window("2026-06-15", 2.5)
    assert start_dt == datetime(2026, 6, 15, 10, 0)
    assert end_dt == datetime(2026, 6, 15, 12, 30)
    assert days == [date(2026, 6, 15)]


def test_layout_multi_day_spill():
    # 14h from Monday -> 6h Mon, 6h Tue, 2h Wed -> ends Wed 12:00
    start_dt, end_dt, days = sr.layout_working_window("2026-06-15", 14.0)
    assert days == [date(2026, 6, 15), date(2026, 6, 16), date(2026, 6, 17)]
    assert end_dt == datetime(2026, 6, 17, 12, 0)


def test_layout_skips_weekend():
    # 14h from Thursday -> Thu, Fri, then Monday (Sat/Sun skipped)
    start_dt, end_dt, days = sr.layout_working_window("2026-06-18", 14.0)
    assert days == [date(2026, 6, 18), date(2026, 6, 19), date(2026, 6, 22)]
    assert end_dt == datetime(2026, 6, 22, 12, 0)


def test_layout_skips_public_holiday():
    # National Day observed Mon 2026-08-10 is skipped.
    # 10h from Fri 2026-08-07 -> Fri(6h), skip Sat/Sun + Mon holiday, Tue(4h)
    start_dt, end_dt, days = sr.layout_working_window("2026-08-07", 10.0)
    assert days == [date(2026, 8, 7), date(2026, 8, 11)]
    assert end_dt == datetime(2026, 8, 11, 14, 0)


def test_layout_rolls_start_to_working_day():
    # Saturday start -> rolls to Monday
    start_dt, _end, days = sr.layout_working_window("2026-06-20", 2.0)
    assert start_dt == datetime(2026, 6, 22, 10, 0)
    assert days[0] == date(2026, 6, 22)


def test_next_valid_layout_start_skips_friday():
    # Friday 2026-06-19 start -> next valid working non-Friday start = Mon 06-22
    d = sr.next_valid_layout_start("2026-06-19", 2.5, [])
    assert d == date(2026, 6, 22)


# --------------------------------------------------------------------------- #
# Emergency-vs-emergency detection + window effort
# --------------------------------------------------------------------------- #
def _emerg(start, end, op_id="E1"):
    return [{"operation_id": op_id, "operation_class": "EMERGENCY", "status": "PLANNED",
             "scheduled_start": start, "scheduled_end": end}]


def test_find_conflicting_emergencies_overlap():
    existing = _emerg("2026-08-19T10:00:00", "2026-08-20T16:00:00")
    res = sr.find_conflicting_emergencies("2026-08-19T12:00:00", "2026-08-19T18:00:00", existing)
    assert [o["operation_id"] for o in res] == ["E1"]


def test_find_conflicting_emergencies_ignores_planned_and_non_overlap():
    planned = [{"operation_id": "P1", "operation_class": "PLANNED", "status": "PLANNED",
                "scheduled_start": "2026-08-19T10:00:00", "scheduled_end": "2026-08-19T16:00:00"}]
    assert sr.find_conflicting_emergencies("2026-08-19T11:00:00", "2026-08-19T12:00:00", planned) == []
    far = _emerg("2026-09-01T10:00:00", "2026-09-01T16:00:00")
    assert sr.find_conflicting_emergencies("2026-08-19T11:00:00", "2026-08-19T12:00:00", far) == []


def test_window_working_hours():
    # one working day
    assert sr.window_working_hours("2026-06-17T10:00:00", "2026-06-17T16:00:00") == sr.DAILY_WORK_HOURS
    # Thu -> Mon spans 3 working days (Thu, Fri, Mon); weekend skipped
    assert sr.window_working_hours("2026-06-18", "2026-06-22") == 3 * sr.DAILY_WORK_HOURS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
