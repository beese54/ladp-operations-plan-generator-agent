"""Load the fictitious 2026 planned-shutdown seed into SQLite (idempotent upsert).

Run scripts/generate_seed_schedule.py first to produce the review JSON.

Usage: PYTHONPATH=. python scripts/load_seed_schedule.py
"""
import json
from pathlib import Path

from db.sqlite_client import bootstrap_sqlite_schema, get_sqlite_connection

SEED = Path("data/seed/scheduled_operations_seed.json")

UPSERT = """
INSERT INTO scheduled_operations
  (operation_id, title, operation_type, operation_class, pipe_id,
   scheduled_start, scheduled_end, status, description, created_by)
VALUES (:operation_id, :title, :operation_type, :operation_class, :pipe_id,
        :scheduled_start, :scheduled_end, :status, :description, :created_by)
ON CONFLICT(operation_id) DO UPDATE SET
  title           = excluded.title,
  operation_type  = excluded.operation_type,
  operation_class = excluded.operation_class,
  pipe_id         = excluded.pipe_id,
  scheduled_start = excluded.scheduled_start,
  scheduled_end   = excluded.scheduled_end,
  status          = excluded.status,
  description     = excluded.description,
  updated_at      = datetime('now')
"""


def main():
    ops = json.loads(SEED.read_text(encoding="utf-8"))
    bootstrap_sqlite_schema()  # ensures operation_class column exists (migration)
    with get_sqlite_connection() as conn:
        for op in ops:
            conn.execute(UPSERT, {
                "operation_id": op["operation_id"],
                "title": op["title"],
                "operation_type": op["operation_type"],
                "operation_class": op["operation_class"],
                "pipe_id": op["pipe_id"],
                "scheduled_start": op["scheduled_start"],
                "scheduled_end": op["scheduled_end"],
                "status": op["status"],
                "description": op["description"],
                "created_by": op["created_by"],
            })
        conn.commit()
        rows = conn.execute(
            "SELECT operation_id, pipe_id, operation_class, "
            "substr(scheduled_start,1,10) AS s, substr(scheduled_end,1,10) AS e "
            "FROM scheduled_operations WHERE created_by='seed' "
            "ORDER BY scheduled_start"
        ).fetchall()
    print(f"Loaded/updated {len(ops)} seed operations. Now in DB (created_by='seed'):")
    for r in rows:
        print(f"  {r['operation_id']:12} {r['pipe_id']:9} {r['operation_class']:8} {r['s']} -> {r['e']}")


if __name__ == "__main__":
    main()
