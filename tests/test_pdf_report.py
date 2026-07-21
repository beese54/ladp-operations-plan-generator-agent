"""Tests for reporting/pdf_report.py (build_operation_report_pdf).

Patches at the point of use (reporting.pdf_report's own namespace), matching
the monkeypatch pattern already used in tests/test_booking.py.
"""
import pytest

from reporting import pdf_report

_CHAIN = {
    "pipe_id": "pipe_084",
    "pipe_road_name": "Bukit Batok Street 22",
    "pipe_status": "open",
    "from_valve_id": "v1",
    "to_valve_id": "v2",
    "shutdown_valves": ["v1", "v2", "v3", "v4"],
    "shutdown_pipes": ["p1", "p2", "p3"],
    "tail_valve_id": "v4",
    "alternate_feed": {"from_valve_id": "va", "pipe_id": "p-alt"},
    "reverse_checks": [
        {"from_valve": "v4", "to_valve": "v3", "pipe_id": "p-r1"},
        {"from_valve": "v3", "to_valve": "v2", "pipe_id": "p-r2"},
        {"from_valve": "v2", "to_valve": "v1", "pipe_id": "p-r3"},
    ],
    "downstream_valves_with_roads": [
        {"valve_id": "v2", "road_name": "Road A"},
        {"valve_id": "v3", "road_name": "Road B"},
        {"valve_id": "v4", "road_name": "Road C"},
    ],
    "valve_diameters": {k: 300 for k in ["v1", "v2", "v3", "v4", "va"]},
}

_OP = {
    "operation_id": "OPS-TEST01",
    "pipe_id": "pipe_084",
    "operation_class": "PLANNED",
    "scheduled_start": "2026-06-17T10:00:00",
    "scheduled_end": "2026-06-17T14:00:00",
    "status": "PLANNED",
}


def test_build_operation_report_pdf_returns_pdf_bytes(monkeypatch):
    monkeypatch.setattr(pdf_report, "get_operation", lambda op_id: dict(_OP))
    monkeypatch.setattr(pdf_report, "build_sop_chain_data", lambda pipe_id: _CHAIN)
    pdf_bytes = pdf_report.build_operation_report_pdf("OPS-TEST01")
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 500


def test_build_operation_report_pdf_missing_operation_raises_not_found(monkeypatch):
    monkeypatch.setattr(pdf_report, "get_operation", lambda op_id: None)
    with pytest.raises(pdf_report.ReportNotFoundError):
        pdf_report.build_operation_report_pdf("OPS-NOPE")


def test_build_operation_report_pdf_missing_pipe_raises_not_found(monkeypatch):
    monkeypatch.setattr(pdf_report, "get_operation", lambda op_id: dict(_OP))

    def _raise(pipe_id):
        raise ValueError(f"Pipe '{pipe_id}' not found in Neo4j.")

    monkeypatch.setattr(pdf_report, "build_sop_chain_data", _raise)
    with pytest.raises(pdf_report.ReportNotFoundError):
        pdf_report.build_operation_report_pdf("OPS-TEST01")


def test_build_operation_report_pdf_unexpected_error_wraps_as_generation_error(monkeypatch):
    monkeypatch.setattr(pdf_report, "get_operation", lambda op_id: dict(_OP))

    def _raise(pipe_id):
        raise RuntimeError("neo4j exploded")

    monkeypatch.setattr(pdf_report, "build_sop_chain_data", _raise)
    with pytest.raises(pdf_report.ReportGenerationError):
        pdf_report.build_operation_report_pdf("OPS-TEST01")


def test_build_operation_report_pdf_no_alt_feed_chain(monkeypatch):
    chain = dict(_CHAIN)
    chain["alternate_feed"] = None
    chain["reverse_checks"] = []
    monkeypatch.setattr(pdf_report, "get_operation", lambda op_id: dict(_OP))
    monkeypatch.setattr(pdf_report, "build_sop_chain_data", lambda pipe_id: chain)
    pdf_bytes = pdf_report.build_operation_report_pdf("OPS-TEST01")
    assert pdf_bytes[:5] == b"%PDF-"
