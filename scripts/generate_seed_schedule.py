"""Generate fictitious 2026 planned-shutdown seed data (one op per month).

Each op is tied to a real pipe/road from the network, runs 3-5 working days,
starts on a Monday (never Friday), and is validated against the Phase-1 rules
engine so the seed data is rule-consistent. Writes a review JSON only — does
NOT touch the database.

Usage: PYTHONPATH=. python scripts/generate_seed_schedule.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from tools import scheduling_rules as sr

OUT = Path("data/seed/scheduled_operations_seed.json")

# (month_start_monday, working_days, pipe_id, road, reason_template)
# operation_class is PLANNED for all of these. Emergency ops are created at
# runtime (they preempt planned ops); none are seeded here.
PLAN = [
    ("2026-01-12", 3, "pipe_003", "Bukit Batok Link",            "LTA road diversion works at {road}"),
    ("2026-02-02", 5, "pipe_007", "Bukit Batok Street 32",       "Drainage upgrading works at {road}"),
    ("2026-03-09", 5, "pipe_013", "Bukit Batok Road",            "LTA MRT construction works at {road}"),
    ("2026-04-13", 3, "pipe_021", "Bukit Batok West Avenue 8",   "LTA road diversion works at {road}"),
    ("2026-05-11", 5, "pipe_030", "Bukit Batok Central",         "Drainage upgrading works at {road}"),
    ("2026-06-22", 4, "pipe_038", "Bukit Batok East Avenue 3",   "LTA MRT construction works at {road}"),
    ("2026-07-13", 3, "pipe_043", "Bukit Batok East Avenue 6",   "LTA road diversion works at {road}"),
    ("2026-08-24", 5, "pipe_051", "Bukit Batok East Avenue 5",   "Drainage upgrading works at {road}"),
    ("2026-09-14", 4, "pipe_055", "Bukit Batok Street 34",       "LTA MRT construction works at {road}"),
    ("2026-10-19", 5, "pipe_068", "Bukit Batok Street 23",       "LTA road diversion works at {road}"),
    ("2026-11-23", 3, "pipe_082", "Bukit Batok Street 22",       "Drainage upgrading works at {road}"),
    ("2026-12-07", 5, "pipe_093", "Bukit Batok Street 52",       "LTA MRT construction works at {road}"),
]


def add_working_days(start, n):
    """Return the date n working days after start (inclusive of start as day 1)."""
    d = start
    counted = 1
    while counted < n:
        d += timedelta(days=1)
        if sr.is_working_day(d):
            counted += 1
    return d


def build():
    ops = []
    for i, (mon, wd, pipe, road, reason_t) in enumerate(PLAN, start=1):
        start_d = datetime.fromisoformat(mon).date()
        end_d = add_working_days(start_d, wd)
        start = datetime(start_d.year, start_d.month, start_d.day, 8, 0)
        end = datetime(end_d.year, end_d.month, end_d.day, 16, 0)
        reason = reason_t.format(road=road.title())
        ops.append({
            "operation_id": f"OPS-2026-{i:02d}",
            "title": reason,
            "operation_type": "SHUTDOWN",
            "operation_class": "PLANNED",
            "pipe_id": pipe,
            "road_name": road.title(),
            "scheduled_start": start.isoformat(),
            "scheduled_end": end.isoformat(),
            "working_days": wd,
            "status": "PLANNED",
            "description": reason,
            "created_by": "seed",
        })
    return ops


def main():
    ops = build()
    # Validate each against the rules engine (each op sees the others as existing).
    print(f"{'ID':12} {'Pipe':9} {'Start':12} {'End':12} {'WD':>2} {'Class':9} Reason")
    print("-" * 100)
    all_ok = True
    for op in ops:
        others = [o for o in ops if o is not op]
        res = sr.validate_planned(op["scheduled_start"], op["scheduled_end"], others)
        flag = "OK " if res.ok else "BAD"
        if not res.ok:
            all_ok = False
        print(f"{op['operation_id']:12} {op['pipe_id']:9} "
              f"{op['scheduled_start'][:10]:12} {op['scheduled_end'][:10]:12} "
              f"{op['working_days']:>2} {op['operation_class']:9} {flag} {op['title']}")
        if not res.ok:
            for v in res.violations:
                print(f"             ! {v}")
    print("-" * 100)
    print("ALL RULE-COMPLIANT" if all_ok else "SOME OPS VIOLATE RULES — review above")
    OUT.write_text(json.dumps(ops, indent=2), encoding="utf-8")
    print(f"\nReview file written: {OUT}  ({len(ops)} operations)  [NOT inserted into DB]")


if __name__ == "__main__":
    main()
