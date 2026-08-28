"""Field Crew Interface tools.

All functions that read/write the crew checklist tables:
  - crew_checklist_steps    (snapshot of SOP steps, written at booking time)
  - crew_checklist_progress (per-step status: PENDING | DONE | FLAGGED)
  - crew_notes              (free-text notes and complication reports from crew)

The checklist steps are built from build_sop_chain_data() (live Neo4j) with a
fallback to the snapshot stored at booking time.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from db.sqlite_client import get_sqlite_connection

logger = logging.getLogger(__name__)


# ── Step snapshot (written once at booking time) ──────────────────────────────

def _chain_to_steps(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a build_sop_chain_data() result into an ordered list of step dicts.

    Steps are ordered to match the on-site sequence:
      1. Close isolation valves (shutdown_valves, in order)
      2. Verify alternate feed (if present)
      3. Re-feed checks (reverse_checks)
      4. If no alternate feed: notify affected areas (downstream_valves_with_roads)
    """
    steps: list[dict[str, Any]] = []
    seq = 1

    # ── Phase 1: close isolation valves (shutdown chain, in order) ───────────
    for valve_id in chain.get("shutdown_valves") or []:
        steps.append({
            "step_number": seq,
            "phase": "isolation",
            "description": f"Close valve {valve_id}",
            "valve_id": valve_id,
            "pipe_id": None,
        })
        seq += 1

    # ── Phase 2: verify alternate feed ────────────────────────────────────────
    alt = chain.get("alternate_feed")
    if alt:
        steps.append({
            "step_number": seq,
            "phase": "alternate_feed",
            "description": (
                f"Verify alternate feed via {alt['pipe_id']} "
                f"(from valve {alt['from_valve_id']}) is open and supplying water"
            ),
            "valve_id": alt["from_valve_id"],
            "pipe_id": alt["pipe_id"],
        })
        seq += 1

        # ── Phase 3: re-feed isolation checks ────────────────────────────────
        for rc in chain.get("reverse_checks") or []:
            steps.append({
                "step_number": seq,
                "phase": "re_feed",
                "description": (
                    f"Verify reverse pipe {rc['pipe_id']} "
                    f"({rc['from_valve']} → {rc['to_valve']}) is isolated — "
                    f"expected status: closed"
                ),
                "valve_id": rc["to_valve"],
                "pipe_id": rc["pipe_id"],
            })
            seq += 1
    else:
        # ── Phase 2B: no alternate feed — notify affected areas ──────────────
        for dv in chain.get("downstream_valves_with_roads") or []:
            steps.append({
                "step_number": seq,
                "phase": "notify",
                "description": (
                    f"No alternate feed — notify customers on "
                    f"{dv.get('road_name', 'affected road')} "
                    f"(valve {dv['valve_id']})"
                ),
                "valve_id": dv["valve_id"],
                "pipe_id": None,
            })
            seq += 1

    # ── Final step: confirm isolation complete ────────────────────────────────
    steps.append({
        "step_number": seq,
        "phase": "verify",
        "description": "Confirm pressure drop and isolation complete — notify ops planning team",
        "valve_id": None,
        "pipe_id": None,
    })

    return steps


def save_checklist_snapshot(
    operation_id: str,
    chain: dict[str, Any],
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Persist the SOP chain as a step snapshot for this operation.

    Idempotent — safe to call multiple times (INSERT OR IGNORE). Returns the
    full list of steps that were saved.
    """
    steps = _chain_to_steps(chain)
    query = """
    INSERT OR IGNORE INTO crew_checklist_steps
      (operation_id, step_number, phase, description, valve_id, pipe_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    with get_sqlite_connection(db_path) as conn:
        for s in steps:
            conn.execute(query, (
                operation_id, s["step_number"], s["phase"],
                s["description"], s["valve_id"], s["pipe_id"],
            ))
        conn.commit()
    logger.info("Saved %d checklist steps for %s", len(steps), operation_id)
    return steps


def get_checklist_snapshot(
    operation_id: str,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return the stored step snapshot for an operation, or [] if none exists."""
    query = """
    SELECT step_number, phase, description, valve_id, pipe_id
    FROM crew_checklist_steps
    WHERE operation_id = ?
    ORDER BY step_number ASC
    """
    with get_sqlite_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, (operation_id,))]


# ── Progress (status per step) ────────────────────────────────────────────────

def get_checklist_progress(
    operation_id: str,
    db_path: Optional[str] = None,
) -> dict[int, dict[str, Any]]:
    """Return a mapping of step_number → {status, flag_note, updated_at}."""
    query = """
    SELECT step_number, status, flag_note, updated_at
    FROM crew_checklist_progress
    WHERE operation_id = ?
    """
    with get_sqlite_connection(db_path) as conn:
        return {
            r["step_number"]: dict(r)
            for r in conn.execute(query, (operation_id,))
        }


def update_step_status(
    operation_id: str,
    step_number: int,
    status: str,
    flag_note: Optional[str] = None,
    db_path: Optional[str] = None,
) -> bool:
    """Upsert the status of a single checklist step.

    status must be one of: PENDING | DONE | FLAGGED
    flag_note is required (and stored) when status == FLAGGED.
    Returns True if the row was written.
    """
    status = status.upper()
    if status not in ("PENDING", "DONE", "FLAGGED"):
        raise ValueError(f"Invalid step status: {status!r}")
    if status == "FLAGGED" and not flag_note:
        raise ValueError("flag_note is required when status is FLAGGED")

    query = """
    INSERT INTO crew_checklist_progress
      (operation_id, step_number, status, flag_note, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(operation_id, step_number) DO UPDATE SET
      status     = excluded.status,
      flag_note  = excluded.flag_note,
      updated_at = excluded.updated_at
    """
    now = datetime.now(timezone.utc).isoformat()
    with get_sqlite_connection(db_path) as conn:
        conn.execute(query, (operation_id, step_number, status, flag_note, now))
        conn.commit()
    return True


def get_completion_rate(
    operation_id: str,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Return completion statistics for an operation's checklist.

    Returns: {total, done, flagged, pending, percent_complete}
    """
    steps = get_checklist_snapshot(operation_id, db_path)
    if not steps:
        return {"total": 0, "done": 0, "flagged": 0, "pending": 0, "percent_complete": 0.0}

    progress = get_checklist_progress(operation_id, db_path)
    total = len(steps)
    done = sum(1 for s in steps if progress.get(s["step_number"], {}).get("status") == "DONE")
    flagged = sum(1 for s in steps if progress.get(s["step_number"], {}).get("status") == "FLAGGED")
    pending = total - done - flagged
    percent = round((done / total) * 100, 1) if total else 0.0
    return {
        "total": total,
        "done": done,
        "flagged": flagged,
        "pending": pending,
        "percent_complete": percent,
    }


# ── Notes / complication reports ─────────────────────────────────────────────

def add_crew_note(
    operation_id: str,
    message: str,
    step_number: Optional[int] = None,
    db_path: Optional[str] = None,
) -> int:
    """Insert a crew note. Returns the new row id."""
    query = """
    INSERT INTO crew_notes (operation_id, step_number, message)
    VALUES (?, ?, ?)
    """
    with get_sqlite_connection(db_path) as conn:
        cur = conn.execute(query, (operation_id, step_number, message))
        conn.commit()
        return cur.lastrowid


def get_crew_notes(
    operation_id: str,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all notes for an operation, newest first."""
    query = """
    SELECT id, step_number, message, created_at
    FROM crew_notes
    WHERE operation_id = ?
    ORDER BY created_at DESC, id DESC
    """
    with get_sqlite_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, (operation_id,))]


# ── Full checklist (steps + progress merged) ──────────────────────────────────

def get_full_checklist(
    operation_id: str,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return steps with their current progress merged in.

    Each item: {step_number, phase, description, valve_id, pipe_id,
                status, flag_note, updated_at}
    """
    steps = get_checklist_snapshot(operation_id, db_path)
    progress = get_checklist_progress(operation_id, db_path)
    result = []
    for s in steps:
        p = progress.get(s["step_number"], {})
        result.append({
            **s,
            "status": p.get("status", "PENDING"),
            "flag_note": p.get("flag_note"),
            "updated_at": p.get("updated_at"),
        })
    return result


# ── Ops-planner-facing summaries ──────────────────────────────────────────────

def get_flagged_steps(
    operation_id: str,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return only the steps the crew has flagged, with their notes.

    Used by the ops planner calendar to surface on-site complications.
    Joins against the step snapshot so the planner sees the step description,
    not just a bare step number.
    """
    query = """
    SELECT p.step_number, p.flag_note, p.updated_at,
           s.description, s.valve_id, s.pipe_id, s.phase
    FROM crew_checklist_progress p
    LEFT JOIN crew_checklist_steps s
           ON s.operation_id = p.operation_id
          AND s.step_number  = p.step_number
    WHERE p.operation_id = ? AND p.status = 'FLAGGED'
    ORDER BY p.step_number ASC
    """
    with get_sqlite_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query, (operation_id,))]


def get_crew_summaries(
    operation_ids: list[str],
    db_path: Optional[str] = None,
) -> dict[str, dict[str, Any]]:
    """Batch crew progress for many operations in one pass.

    Returns operation_id -> {total, done, flagged, pending, percent_complete,
                             flagged_steps[], note_count}
    Operations with no checklist snapshot are omitted (nothing to report).
    Batched deliberately: the month calendar renders up to ~30 days of
    operations, and per-operation round trips would be N+1 queries.
    """
    if not operation_ids:
        return {}

    placeholders = ",".join("?" for _ in operation_ids)
    out: dict[str, dict[str, Any]] = {}

    with get_sqlite_connection(db_path) as conn:
        # Step totals per operation
        totals = {
            r["operation_id"]: r["total"]
            for r in conn.execute(
                f"""SELECT operation_id, COUNT(*) AS total
                    FROM crew_checklist_steps
                    WHERE operation_id IN ({placeholders})
                    GROUP BY operation_id""",
                operation_ids,
            )
        }
        # Status counts per operation
        status_counts: dict[str, dict[str, int]] = {}
        for r in conn.execute(
            f"""SELECT operation_id, status, COUNT(*) AS n
                FROM crew_checklist_progress
                WHERE operation_id IN ({placeholders})
                GROUP BY operation_id, status""",
            operation_ids,
        ):
            status_counts.setdefault(r["operation_id"], {})[r["status"]] = r["n"]
        # Note counts per operation
        note_counts = {
            r["operation_id"]: r["n"]
            for r in conn.execute(
                f"""SELECT operation_id, COUNT(*) AS n
                    FROM crew_notes
                    WHERE operation_id IN ({placeholders})
                    GROUP BY operation_id""",
                operation_ids,
            )
        }

    for op_id, total in totals.items():
        counts = status_counts.get(op_id, {})
        done = counts.get("DONE", 0)
        flagged = counts.get("FLAGGED", 0)
        out[op_id] = {
            "total": total,
            "done": done,
            "flagged": flagged,
            "pending": max(0, total - done - flagged),
            "percent_complete": round((done / total) * 100, 1) if total else 0.0,
            "flagged_steps": get_flagged_steps(op_id, db_path) if flagged else [],
            "note_count": note_counts.get(op_id, 0),
        }
    return out
