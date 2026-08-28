"""Unit tests for tools/crew_tools.py

All tests use an in-memory SQLite database — no file created, no external deps.
"""
import pytest
from db.sqlite_client import bootstrap_sqlite_schema
from tools.crew_tools import (
    _chain_to_steps,
    save_checklist_snapshot,
    get_checklist_snapshot,
    get_checklist_progress,
    update_step_status,
    get_completion_rate,
    add_crew_note,
    get_crew_notes,
    get_full_checklist,
    get_flagged_steps,
    get_crew_summaries,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

DB = ":memory:"

MINIMAL_CHAIN = {
    "pipe_id": "pipe_084",
    "from_valve_id": "valve_034",
    "to_valve_id": "valve_035",
    "pipe_road_name": "Bukit Batok Street 22",
    "pipe_status": "open",
    "steps": [
        {"from_valve": "valve_035", "pipe_id": "pipe_086", "to_valve": "valve_036", "status": "open"},
    ],
    "tail_valve_id": "valve_036",
    "alternate_feed": {
        "pipe_id": "pipe_090",
        "from_valve_id": "valve_040",
        "status": "open",
    },
    "shutdown_pipes": ["pipe_084", "pipe_086"],
    "shutdown_valves": ["valve_034", "valve_035", "valve_036"],
    "reverse_checks": [
        {"from_valve": "valve_036", "to_valve": "valve_035", "pipe_id": "pipe_087", "status": "closed", "ok": True},
    ],
    "downstream_valves_with_roads": [],
    "valve_diameters": {},
}

NO_ALT_FEED_CHAIN = {
    **MINIMAL_CHAIN,
    "alternate_feed": None,
    "reverse_checks": [],
    "downstream_valves_with_roads": [
        {"valve_id": "valve_050", "road_name": "Test Road"},
        {"valve_id": "valve_051", "road_name": "Another Road"},
    ],
}

OP_ID = "OPS-TEST0001"


@pytest.fixture
def db(tmp_path):
    """Temporary SQLite DB with schema bootstrapped."""
    path = str(tmp_path / "test.db")
    bootstrap_sqlite_schema(path)
    # Insert a minimal scheduled_operations row so FK constraints pass
    from db.sqlite_client import get_sqlite_connection
    with get_sqlite_connection(path) as conn:
        conn.execute("""
            INSERT INTO scheduled_operations
              (operation_id, title, operation_type, scheduled_start, scheduled_end)
            VALUES (?, 'Test op', 'SHUTDOWN', '2026-08-01T10:00:00', '2026-08-01T16:00:00')
        """, (OP_ID,))
        conn.commit()
    return path


# ── _chain_to_steps ───────────────────────────────────────────────────────────

class TestChainToSteps:
    def test_with_alternate_feed_has_isolation_and_re_feed_steps(self):
        steps = _chain_to_steps(MINIMAL_CHAIN)
        phases = [s["phase"] for s in steps]
        assert "isolation" in phases
        assert "alternate_feed" in phases
        assert "re_feed" in phases
        assert "verify" in phases

    def test_isolation_steps_match_shutdown_valves(self):
        steps = _chain_to_steps(MINIMAL_CHAIN)
        isolation = [s for s in steps if s["phase"] == "isolation"]
        assert len(isolation) == len(MINIMAL_CHAIN["shutdown_valves"])
        for step, valve in zip(isolation, MINIMAL_CHAIN["shutdown_valves"]):
            assert valve in step["description"]
            assert step["valve_id"] == valve

    def test_no_alt_feed_produces_notify_steps(self):
        steps = _chain_to_steps(NO_ALT_FEED_CHAIN)
        phases = [s["phase"] for s in steps]
        assert "notify" in phases
        assert "alternate_feed" not in phases
        assert "re_feed" not in phases

    def test_no_alt_feed_notify_count_matches_downstream(self):
        steps = _chain_to_steps(NO_ALT_FEED_CHAIN)
        notify = [s for s in steps if s["phase"] == "notify"]
        assert len(notify) == len(NO_ALT_FEED_CHAIN["downstream_valves_with_roads"])

    def test_step_numbers_are_sequential_from_one(self):
        steps = _chain_to_steps(MINIMAL_CHAIN)
        for i, step in enumerate(steps, start=1):
            assert step["step_number"] == i

    def test_always_ends_with_verify_step(self):
        steps = _chain_to_steps(MINIMAL_CHAIN)
        assert steps[-1]["phase"] == "verify"

    def test_empty_chain_returns_single_verify_step(self):
        empty = {**MINIMAL_CHAIN, "shutdown_valves": [], "reverse_checks": [], "alternate_feed": None, "downstream_valves_with_roads": []}
        steps = _chain_to_steps(empty)
        assert len(steps) == 1
        assert steps[0]["phase"] == "verify"


# ── save / get snapshot ───────────────────────────────────────────────────────

class TestChecklistSnapshot:
    def test_save_returns_steps(self, db):
        steps = save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        assert len(steps) > 0

    def test_get_returns_same_count(self, db):
        saved = save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        fetched = get_checklist_snapshot(OP_ID, db_path=db)
        assert len(fetched) == len(saved)

    def test_idempotent_double_save(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)  # should not raise
        fetched = get_checklist_snapshot(OP_ID, db_path=db)
        assert len(fetched) == len(_chain_to_steps(MINIMAL_CHAIN))

    def test_get_nonexistent_returns_empty(self, db):
        result = get_checklist_snapshot("NO-SUCH-OP", db_path=db)
        assert result == []

    def test_step_fields_present(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        for s in steps:
            assert "step_number" in s
            assert "phase" in s
            assert "description" in s


# ── update_step_status ────────────────────────────────────────────────────────

class TestUpdateStepStatus:
    def test_mark_done(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        progress = get_checklist_progress(OP_ID, db_path=db)
        assert progress[1]["status"] == "DONE"

    def test_mark_flagged_with_note(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "FLAGGED", flag_note="Valve stuck", db_path=db)
        progress = get_checklist_progress(OP_ID, db_path=db)
        assert progress[1]["status"] == "FLAGGED"
        assert progress[1]["flag_note"] == "Valve stuck"

    def test_flagged_without_note_raises(self, db):
        with pytest.raises(ValueError, match="flag_note is required"):
            update_step_status(OP_ID, 1, "FLAGGED", db_path=db)

    def test_invalid_status_raises(self, db):
        with pytest.raises(ValueError, match="Invalid step status"):
            update_step_status(OP_ID, 1, "BROKEN", db_path=db)

    def test_update_is_idempotent(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        update_step_status(OP_ID, 1, "PENDING", db_path=db)
        progress = get_checklist_progress(OP_ID, db_path=db)
        assert progress[1]["status"] == "PENDING"


# ── get_completion_rate ───────────────────────────────────────────────────────

class TestCompletionRate:
    def test_zero_percent_when_all_pending(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        stats = get_completion_rate(OP_ID, db_path=db)
        assert stats["percent_complete"] == 0.0
        assert stats["pending"] == stats["total"]

    def test_100_percent_when_all_done(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        for s in steps:
            update_step_status(OP_ID, s["step_number"], "DONE", db_path=db)
        stats = get_completion_rate(OP_ID, db_path=db)
        assert stats["percent_complete"] == 100.0
        assert stats["done"] == stats["total"]

    def test_partial_completion(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        # Mark first step done
        update_step_status(OP_ID, steps[0]["step_number"], "DONE", db_path=db)
        stats = get_completion_rate(OP_ID, db_path=db)
        assert stats["done"] == 1
        assert stats["pending"] == stats["total"] - 1

    def test_flagged_counted_separately(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        update_step_status(OP_ID, steps[0]["step_number"], "FLAGGED", flag_note="Issue", db_path=db)
        stats = get_completion_rate(OP_ID, db_path=db)
        assert stats["flagged"] == 1
        assert stats["done"] == 0

    def test_no_snapshot_returns_zeros(self, db):
        stats = get_completion_rate(OP_ID, db_path=db)
        assert stats["total"] == 0
        assert stats["percent_complete"] == 0.0


# ── crew notes ────────────────────────────────────────────────────────────────

class TestCrewNotes:
    def test_add_and_retrieve_note(self, db):
        note_id = add_crew_note(OP_ID, "Valve was stiff but opened", db_path=db)
        notes = get_crew_notes(OP_ID, db_path=db)
        assert len(notes) == 1
        assert notes[0]["id"] == note_id
        assert notes[0]["message"] == "Valve was stiff but opened"
        assert notes[0]["step_number"] is None

    def test_note_with_step_number(self, db):
        add_crew_note(OP_ID, "Step 3 had a complication", step_number=3, db_path=db)
        notes = get_crew_notes(OP_ID, db_path=db)
        assert notes[0]["step_number"] == 3

    def test_multiple_notes_ordered_newest_first(self, db):
        add_crew_note(OP_ID, "First note", db_path=db)
        add_crew_note(OP_ID, "Second note", db_path=db)
        notes = get_crew_notes(OP_ID, db_path=db)
        assert len(notes) == 2
        assert notes[0]["message"] == "Second note"

    def test_no_notes_returns_empty(self, db):
        notes = get_crew_notes(OP_ID, db_path=db)
        assert notes == []


# ── get_full_checklist ────────────────────────────────────────────────────────

class TestFullChecklist:
    def test_merges_progress_into_steps(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        update_step_status(OP_ID, steps[0]["step_number"], "DONE", db_path=db)

        full = get_full_checklist(OP_ID, db_path=db)
        assert full[0]["status"] == "DONE"
        # Remaining steps should be PENDING
        for s in full[1:]:
            assert s["status"] == "PENDING"

    def test_all_required_fields_present(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        full = get_full_checklist(OP_ID, db_path=db)
        for step in full:
            assert "step_number" in step
            assert "phase" in step
            assert "description" in step
            assert "status" in step
            assert "flag_note" in step


# ── get_flagged_steps (ops-planner visibility) ────────────────────────────────

class TestFlaggedSteps:
    def test_empty_when_nothing_flagged(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        assert get_flagged_steps(OP_ID, db_path=db) == []

    def test_returns_flagged_step_with_note(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 2, "FLAGGED", flag_note="Valve seized", db_path=db)
        flagged = get_flagged_steps(OP_ID, db_path=db)
        assert len(flagged) == 1
        assert flagged[0]["step_number"] == 2
        assert flagged[0]["flag_note"] == "Valve seized"

    def test_joins_step_description(self, db):
        """The planner needs the step text, not just a bare number."""
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "FLAGGED", flag_note="Stuck", db_path=db)
        flagged = get_flagged_steps(OP_ID, db_path=db)
        assert flagged[0]["description"]
        assert "valve_034" in flagged[0]["description"]

    def test_excludes_done_and_pending(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        update_step_status(OP_ID, 2, "FLAGGED", flag_note="Issue", db_path=db)
        flagged = get_flagged_steps(OP_ID, db_path=db)
        assert [f["step_number"] for f in flagged] == [2]

    def test_unflagging_removes_from_list(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "FLAGGED", flag_note="Issue", db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        assert get_flagged_steps(OP_ID, db_path=db) == []


# ── get_crew_summaries (batched, drives the ops calendar) ─────────────────────

OP_ID_2 = "OPS-TEST0002"


@pytest.fixture
def db_two_ops(db):
    """Second operation so batching across operations is actually exercised."""
    from db.sqlite_client import get_sqlite_connection
    with get_sqlite_connection(db) as conn:
        conn.execute("""
            INSERT INTO scheduled_operations
              (operation_id, title, operation_type, scheduled_start, scheduled_end)
            VALUES (?, 'Second op', 'SHUTDOWN', '2026-08-05T10:00:00', '2026-08-05T16:00:00')
        """, (OP_ID_2,))
        conn.commit()
    return db


class TestCrewSummaries:
    def test_empty_input_returns_empty(self, db):
        assert get_crew_summaries([], db_path=db) == {}

    def test_operation_without_snapshot_omitted(self, db):
        """No checklist means nothing to report — the UI shows a 'not opened' hint."""
        assert get_crew_summaries([OP_ID], db_path=db) == {}

    def test_reports_totals_for_fresh_checklist(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["total"] == len(_chain_to_steps(MINIMAL_CHAIN))
        assert summary["done"] == 0
        assert summary["flagged"] == 0
        assert summary["percent_complete"] == 0.0

    def test_percent_matches_get_completion_rate(self, db):
        """Batched path must agree with the single-operation path."""
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        batched = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        single = get_completion_rate(OP_ID, db_path=db)
        assert batched["percent_complete"] == single["percent_complete"]
        assert batched["done"] == single["done"]
        assert batched["pending"] == single["pending"]

    def test_includes_flagged_steps_inline(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 2, "FLAGGED", flag_note="Leaking", db_path=db)
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["flagged"] == 1
        assert len(summary["flagged_steps"]) == 1
        assert summary["flagged_steps"][0]["flag_note"] == "Leaking"

    def test_flagged_steps_empty_when_none_flagged(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["flagged_steps"] == []

    def test_counts_notes(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        add_crew_note(OP_ID, "First", db_path=db)
        add_crew_note(OP_ID, "Second", db_path=db)
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["note_count"] == 2

    def test_does_not_leak_between_operations(self, db_two_ops):
        db = db_two_ops
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        save_checklist_snapshot(OP_ID_2, MINIMAL_CHAIN, db_path=db)
        update_step_status(OP_ID, 1, "DONE", db_path=db)
        update_step_status(OP_ID_2, 1, "FLAGGED", flag_note="Op2 issue", db_path=db)
        add_crew_note(OP_ID_2, "Op2 note", db_path=db)

        summaries = get_crew_summaries([OP_ID, OP_ID_2], db_path=db)

        assert summaries[OP_ID]["done"] == 1
        assert summaries[OP_ID]["flagged"] == 0
        assert summaries[OP_ID]["note_count"] == 0

        assert summaries[OP_ID_2]["done"] == 0
        assert summaries[OP_ID_2]["flagged"] == 1
        assert summaries[OP_ID_2]["note_count"] == 1
        assert summaries[OP_ID_2]["flagged_steps"][0]["flag_note"] == "Op2 issue"

    def test_pending_never_negative(self, db):
        """Guards the max(0, ...) clamp if progress rows outnumber snapshot rows."""
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        steps = get_checklist_snapshot(OP_ID, db_path=db)
        for s in steps:
            update_step_status(OP_ID, s["step_number"], "DONE", db_path=db)
        update_step_status(OP_ID, 999, "DONE", db_path=db)  # step not in snapshot
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["pending"] >= 0

    def test_all_done_is_100_percent(self, db):
        save_checklist_snapshot(OP_ID, MINIMAL_CHAIN, db_path=db)
        for s in get_checklist_snapshot(OP_ID, db_path=db):
            update_step_status(OP_ID, s["step_number"], "DONE", db_path=db)
        summary = get_crew_summaries([OP_ID], db_path=db)[OP_ID]
        assert summary["percent_complete"] == 100.0
        assert summary["pending"] == 0
