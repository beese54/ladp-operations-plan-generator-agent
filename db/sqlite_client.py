import sqlite3
from contextlib import contextmanager
from pathlib import Path
from config.settings import get_settings

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS scheduled_operations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id    TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    operation_type  TEXT NOT NULL,
    pipe_id         TEXT,
    valve_ids       TEXT,
    zone_id         TEXT,
    scheduled_start TEXT NOT NULL,
    scheduled_end   TEXT NOT NULL,
    actual_start    TEXT,
    actual_end      TEXT,
    status          TEXT NOT NULL DEFAULT 'PLANNED',
    priority        TEXT NOT NULL DEFAULT 'NORMAL',
    operation_class TEXT NOT NULL DEFAULT 'PLANNED',  -- PLANNED | EMERGENCY
    description     TEXT,
    assigned_crew   TEXT,
    created_by      TEXT NOT NULL DEFAULT 'system',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS operation_affected_consumers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id    TEXT NOT NULL REFERENCES scheduled_operations(operation_id),
    consumer_id     TEXT NOT NULL,
    consumer_name   TEXT,
    criticality     TEXT,
    notified_at     TEXT,
    notified_via    TEXT
);

CREATE TABLE IF NOT EXISTS scheduling_conflicts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    new_operation_id    TEXT NOT NULL,
    conflicting_op_id   TEXT NOT NULL REFERENCES scheduled_operations(operation_id),
    conflict_type       TEXT NOT NULL,
    conflict_detail     TEXT,
    severity            TEXT NOT NULL,
    detected_at         TEXT NOT NULL DEFAULT (datetime('now')),
    resolved            INTEGER NOT NULL DEFAULT 0,
    resolution_note     TEXT
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL UNIQUE,
    user_query      TEXT NOT NULL,
    pipe_id         TEXT,
    target_date     TEXT,
    feasibility     TEXT,
    plan_generated  INTEGER NOT NULL DEFAULT 0,
    response_summary TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sched_ops_pipe_id ON scheduled_operations(pipe_id);
CREATE INDEX IF NOT EXISTS idx_sched_ops_dates   ON scheduled_operations(scheduled_start, scheduled_end);
CREATE INDEX IF NOT EXISTS idx_sched_ops_status  ON scheduled_operations(status);
CREATE INDEX IF NOT EXISTS idx_conflicts_op_id   ON scheduling_conflicts(new_operation_id);
"""


def get_db_path() -> str:
    return get_settings().sqlite_db_path


@contextmanager
def get_sqlite_connection(db_path: str | None = None):
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
    finally:
        conn.close()


# Idempotent column additions for databases created before a column existed.
# (SQLite has no "ADD COLUMN IF NOT EXISTS", so we check PRAGMA table_info.)
_MIGRATIONS = {
    "scheduled_operations": {
        "operation_class": "ALTER TABLE scheduled_operations "
                           "ADD COLUMN operation_class TEXT NOT NULL DEFAULT 'PLANNED'",
    },
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for table, columns in _MIGRATIONS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in columns.items():
            if col not in existing:
                conn.execute(ddl)


def bootstrap_sqlite_schema(db_path: str | None = None) -> None:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(_DDL)
        _apply_migrations(conn)
        conn.commit()
    finally:
        conn.close()
