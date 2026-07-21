"""Tests for the calendar write helpers (Phase 4, S4.0)."""
import pytest

from db.sqlite_client import bootstrap_sqlite_schema
from tools import calendar_tools as ct


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "cal.db")
    bootstrap_sqlite_schema(p)
    return p


def test_create_persists_operation_class(db):
    op_id = ct.create_scheduled_operation(
        title="Emergency shutdown — pipe_084", operation_type="SHUTDOWN",
        pipe_id="pipe_084", scheduled_start="2026-07-06T10:00:00",
        scheduled_end="2026-07-06T14:00:00", operation_class="EMERGENCY",
        valve_ids=["v1", "v2"], created_by="chat", db_path=db,
    )
    assert op_id.startswith("OPS-")
    ops = ct.get_active_operations(db_path=db)
    assert len(ops) == 1
    assert ops[0]["operation_id"] == op_id
    assert ops[0]["operation_class"] == "EMERGENCY"


def test_create_defaults_to_planned(db):
    ct.create_scheduled_operation(
        title="x", operation_type="SHUTDOWN", pipe_id="pipe_001",
        scheduled_start="2026-07-06T10:00:00", scheduled_end="2026-07-06T14:00:00",
        db_path=db,
    )
    assert ct.get_active_operations(db_path=db)[0]["operation_class"] == "PLANNED"


def test_reschedule_operation_updates_window(db):
    op_id = ct.create_scheduled_operation(
        title="x", operation_type="SHUTDOWN", pipe_id="pipe_001",
        scheduled_start="2026-07-06T10:00:00", scheduled_end="2026-07-06T14:00:00",
        db_path=db,
    )
    assert ct.reschedule_operation(op_id, "2026-07-20T10:00:00", "2026-07-20T14:00:00", db_path=db) is True
    op = ct.get_active_operations(db_path=db)[0]
    assert op["scheduled_start"] == "2026-07-20T10:00:00"
    assert op["scheduled_end"] == "2026-07-20T14:00:00"


def test_reschedule_missing_returns_false(db):
    assert ct.reschedule_operation(
        "OPS-NOPE", "2026-07-20T10:00:00", "2026-07-20T14:00:00", db_path=db
    ) is False


def test_get_operation_returns_row_with_decoded_json(db):
    op_id = ct.create_scheduled_operation(
        title="x", operation_type="SHUTDOWN", pipe_id="pipe_084",
        scheduled_start="2026-07-06T10:00:00", scheduled_end="2026-07-06T14:00:00",
        valve_ids=["v1", "v2"], assigned_crew=["crew-1"], db_path=db,
    )
    op = ct.get_operation(op_id, db_path=db)
    assert op is not None
    assert op["operation_id"] == op_id
    assert op["pipe_id"] == "pipe_084"
    assert op["valve_ids"] == ["v1", "v2"]
    assert op["assigned_crew"] == ["crew-1"]


def test_get_operation_missing_returns_none(db):
    assert ct.get_operation("OPS-NOPE", db_path=db) is None
