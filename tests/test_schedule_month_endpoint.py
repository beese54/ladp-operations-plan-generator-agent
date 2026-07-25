"""Tests for GET /api/v1/schedule/month — the structured month view backing
the left-panel calendar (Phase 14, calendar-view feature).

Calls the route function directly (bypassing FastAPI's DI/HTTP layer,
consistent with how tests/test_schedule_agent.py tests calendar_agent nodes)
so these stay hermetic — no live server, no Neo4j/ChromaDB dependency.
`get_active_operations` is monkeypatched at the point of use in
api.routes.schedule, same pattern as calendar_agent's own tests.
"""
import asyncio

import pytest

from api.routes import schedule as schedule_route


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_ops(monkeypatch):
    monkeypatch.setattr(schedule_route, "get_active_operations", lambda: [])


def _op(operation_id, start, end, **overrides):
    base = {
        "operation_id": operation_id,
        "title": f"Op {operation_id}",
        "operation_type": "SHUTDOWN",
        "operation_class": "PLANNED",
        "pipe_id": "pipe_074",
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "PLANNED",
    }
    base.update(overrides)
    return base


def test_classifies_holiday_and_blackout_days(no_ops):
    # June 2026: Vesak in-lieu holiday on 06-01, blackout trailing to 06-08.
    resp = _run(schedule_route.get_month_schedule(year=2026, month=6))
    by_date = {d.date: d for d in resp.days}

    assert by_date["2026-06-01"].is_holiday is True
    assert by_date["2026-06-01"].holiday_name == "Vesak Day"
    assert by_date["2026-06-01"].is_blackout is False  # holiday day itself, not double-shaded

    assert by_date["2026-06-05"].is_holiday is False
    assert by_date["2026-06-05"].is_blackout is True

    assert by_date["2026-06-16"].is_holiday is False
    assert by_date["2026-06-16"].is_blackout is False
    assert by_date["2026-06-16"].is_working_day is True

    assert len(resp.days) == 30
    assert resp.holiday_data_available is True


def test_holiday_data_available_false_for_unseeded_year(no_ops):
    resp = _run(schedule_route.get_month_schedule(year=2028, month=6))
    assert resp.holiday_data_available is False
    # Navigation/classification still works — just no holiday shading.
    assert len(resp.days) == 30
    assert all(d.is_holiday is False for d in resp.days)


def test_operation_attached_to_the_days_it_touches(monkeypatch):
    ops = [_op("OPS-001", "2026-11-18T10:00:00", "2026-11-18T14:55:00")]
    monkeypatch.setattr(schedule_route, "get_active_operations", lambda: ops)

    resp = _run(schedule_route.get_month_schedule(year=2026, month=11))
    by_date = {d.date: d for d in resp.days}

    assert [o["operation_id"] for o in by_date["2026-11-18"].operations] == ["OPS-001"]
    assert by_date["2026-11-17"].operations == []
    assert by_date["2026-11-19"].operations == []


def test_multi_day_operation_spans_every_day_it_touches(monkeypatch):
    ops = [_op("OPS-002", "2026-08-24T08:00:00", "2026-08-28T16:00:00", pipe_id="pipe_051")]
    monkeypatch.setattr(schedule_route, "get_active_operations", lambda: ops)

    resp = _run(schedule_route.get_month_schedule(year=2026, month=8))
    by_date = {d.date: d for d in resp.days}

    touched = [24, 25, 26, 27, 28]
    for day in touched:
        key = f"2026-08-{day:02d}"
        assert [o["operation_id"] for o in by_date[key].operations] == ["OPS-002"], key
    assert by_date["2026-08-23"].operations == []
    assert by_date["2026-08-29"].operations == []


def test_operation_full_fields_preserved_for_chip_coloring(monkeypatch):
    ops = [_op("OPS-003", "2026-06-16T10:00:00", "2026-06-16T12:00:00",
                status="IN_PROGRESS", operation_class="EMERGENCY")]
    monkeypatch.setattr(schedule_route, "get_active_operations", lambda: ops)

    resp = _run(schedule_route.get_month_schedule(year=2026, month=6))
    by_date = {d.date: d for d in resp.days}
    op = by_date["2026-06-16"].operations[0]
    assert op["status"] == "IN_PROGRESS"
    assert op["operation_class"] == "EMERGENCY"
    assert op["operation_type"] == "SHUTDOWN"
