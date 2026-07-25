"""Tests for the chat route's schedule_view signal (Phase 14, calendar-view
feature) — the field that tells the frontend when/where the left panel
should auto-switch to the ops calendar.
"""
from api.routes import chat as chat_route


def test_schedule_query_turn_uses_target_date():
    result = {"operation_type": "SCHEDULE_QUERY", "target_date": "2026-11-01"}
    assert chat_route._schedule_view_for(result) == {"year": 2026, "month": 11}


def test_booking_turn_uses_actual_booked_date_not_target_date(monkeypatch):
    # Operator asked for 2026-11-20 but the engine auto-shifted the booking
    # to 2026-11-23 (e.g. off a blackout/conflict date) — schedule_view must
    # reflect where it actually landed, not the original ask.
    monkeypatch.setattr(
        chat_route, "get_operation",
        lambda op_id: {"scheduled_start": "2026-11-23T10:00:00"} if op_id == "OPS-1" else None,
    )
    result = {
        "operation_type": "SHUTDOWN",
        "target_date": "2026-11-20",
        "booked_operation_id": "OPS-1",
    }
    assert chat_route._schedule_view_for(result) == {"year": 2026, "month": 11}


def test_booking_spanning_month_boundary_uses_scheduled_start_month(monkeypatch):
    monkeypatch.setattr(
        chat_route, "get_operation",
        lambda op_id: {"scheduled_start": "2026-08-24T08:00:00"},
    )
    result = {"operation_type": "SHUTDOWN", "booked_operation_id": "OPS-2"}
    assert chat_route._schedule_view_for(result) == {"year": 2026, "month": 8}


def test_ordinary_shutdown_plan_turn_does_not_trigger_switch():
    # A plan was generated/shown but nothing was booked yet — must not flip
    # the left panel to the calendar mid-conversation.
    result = {"operation_type": "SHUTDOWN", "target_date": "2026-11-20"}
    assert chat_route._schedule_view_for(result) is None


def test_general_query_turn_does_not_trigger_switch():
    result = {"operation_type": "GENERAL_QUERY", "target_date": "2026-11-20"}
    assert chat_route._schedule_view_for(result) is None


def test_booked_operation_id_missing_from_db_is_handled(monkeypatch):
    monkeypatch.setattr(chat_route, "get_operation", lambda op_id: None)
    result = {"operation_type": "SHUTDOWN", "booked_operation_id": "OPS-GONE"}
    assert chat_route._schedule_view_for(result) is None
