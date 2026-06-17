import json
import logging
import sqlite3
from typing import Any, Optional
from uuid import uuid4
from db.sqlite_client import get_sqlite_connection
from schemas.graph_state import SchedulingConflict

logger = logging.getLogger(__name__)


def check_pipe_schedule_conflicts(
    pipe_id: str,
    requested_start: str,
    requested_end: str,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all PLANNED/IN_PROGRESS operations on this pipe that overlap the requested window."""
    query = """
    SELECT operation_id, title, scheduled_start, scheduled_end, status, priority
    FROM scheduled_operations
    WHERE status IN ('PLANNED', 'IN_PROGRESS')
      AND pipe_id = ?
      AND scheduled_start < ?
      AND scheduled_end   > ?
    """
    conflicts = []
    with get_sqlite_connection(db_path) as conn:
        for row in conn.execute(query, (pipe_id, requested_end, requested_start)):
            r = dict(row)
            conflicts.append({
                "conflicting_op_id": r["operation_id"],
                "conflict_type": "TIME_OVERLAP",
                "severity": "BLOCKING" if r["priority"] in ("CRITICAL", "HIGH") else "WARNING",
                "title": r["title"],
                "scheduled_start": r["scheduled_start"],
                "scheduled_end": r["scheduled_end"],
                "detail": f"Operation '{r['title']}' is scheduled on this pipe during the requested window.",
            })
    return conflicts


def get_upcoming_operations(
    pipe_id: Optional[str] = None,
    days_ahead: int = 30,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return operations scheduled within the next N days, optionally filtered by pipe."""
    base_query = """
    SELECT operation_id, title, operation_type, pipe_id,
           scheduled_start, scheduled_end, status, priority
    FROM scheduled_operations
    WHERE status IN ('PLANNED', 'IN_PROGRESS')
      AND scheduled_start >= datetime('now')
      AND scheduled_start <= datetime('now', ? || ' days')
    """
    params: list[Any] = [str(days_ahead)]
    if pipe_id:
        base_query += " AND pipe_id = ?"
        params.append(pipe_id)
    base_query += " ORDER BY scheduled_start ASC"

    with get_sqlite_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(base_query, params)]


def get_active_operations(
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Return all PLANNED/IN_PROGRESS operations (any pipe) for rule evaluation.

    The working-day-gap rule (R2) and emergency displacement span all operations,
    not just the same pipe, so this returns the whole active set.
    """
    query = """
    SELECT operation_id, title, operation_type, operation_class, pipe_id,
           scheduled_start, scheduled_end, status
    FROM scheduled_operations
    WHERE status IN ('PLANNED', 'IN_PROGRESS')
    ORDER BY scheduled_start ASC
    """
    with get_sqlite_connection(db_path) as conn:
        return [dict(r) for r in conn.execute(query)]


def create_scheduled_operation(
    title: str,
    operation_type: str,
    pipe_id: str,
    scheduled_start: str,
    scheduled_end: str,
    priority: str = "NORMAL",
    description: Optional[str] = None,
    valve_ids: Optional[list[str]] = None,
    zone_id: Optional[str] = None,
    assigned_crew: Optional[list[str]] = None,
    created_by: str = "system",
    db_path: Optional[str] = None,
) -> str:
    """Insert a new scheduled operation. Returns the generated operation_id."""
    operation_id = f"OPS-{uuid4().hex[:8].upper()}"
    query = """
    INSERT INTO scheduled_operations
      (operation_id, title, operation_type, pipe_id, valve_ids, zone_id,
       scheduled_start, scheduled_end, priority, description, assigned_crew, created_by)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_sqlite_connection(db_path) as conn:
        conn.execute(query, (
            operation_id, title, operation_type, pipe_id,
            json.dumps(valve_ids or []),
            zone_id,
            scheduled_start, scheduled_end,
            priority, description,
            json.dumps(assigned_crew or []),
            created_by,
        ))
        conn.commit()
    logger.info("Created scheduled operation %s", operation_id)
    return operation_id


def cancel_operation(operation_id: str, db_path: Optional[str] = None) -> bool:
    """Mark an operation as CANCELLED. Returns True if a row was updated."""
    query = """
    UPDATE scheduled_operations
    SET status = 'CANCELLED', updated_at = datetime('now')
    WHERE operation_id = ? AND status NOT IN ('COMPLETED', 'CANCELLED')
    """
    with get_sqlite_connection(db_path) as conn:
        cur = conn.execute(query, (operation_id,))
        conn.commit()
        return cur.rowcount > 0


def log_chat_session(
    session_id: str,
    user_query: str,
    pipe_id: Optional[str] = None,
    target_date: Optional[str] = None,
    feasibility: Optional[str] = None,
    plan_generated: bool = False,
    response_summary: Optional[str] = None,
    db_path: Optional[str] = None,
) -> None:
    """Upsert a chat session record for audit trail."""
    query = """
    INSERT INTO chat_sessions
      (session_id, user_query, pipe_id, target_date, feasibility, plan_generated, response_summary)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(session_id) DO UPDATE SET
      user_query       = excluded.user_query,
      pipe_id          = excluded.pipe_id,
      target_date      = excluded.target_date,
      feasibility      = excluded.feasibility,
      plan_generated   = excluded.plan_generated,
      response_summary = excluded.response_summary
    """
    with get_sqlite_connection(db_path) as conn:
        conn.execute(query, (
            session_id, user_query, pipe_id, target_date,
            feasibility, int(plan_generated), response_summary,
        ))
        conn.commit()
