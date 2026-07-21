"""Tests for reporting/network_diagram.py (render_chain_diagram)."""
from reporting.network_diagram import render_chain_diagram

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_CHAIN_WITH_ALT = {
    "pipe_id": "pipe_084",
    "shutdown_valves": ["v1", "v2", "v3", "v4"],
    "shutdown_pipes": ["p1", "p2", "p3"],
    "tail_valve_id": "v4",
    "alternate_feed": {"from_valve_id": "va", "pipe_id": "p-alt"},
    "reverse_checks": [
        {"from_valve": "v4", "to_valve": "v3", "pipe_id": "p-r1"},
        {"from_valve": "v3", "to_valve": "v2", "pipe_id": "p-r2"},
        {"from_valve": "v2", "to_valve": "v1", "pipe_id": "p-r3"},
    ],
}

_CHAIN_NO_ALT = {
    "pipe_id": "pipe_099",
    "shutdown_valves": ["v1", "v2"],
    "shutdown_pipes": ["p1"],
    "tail_valve_id": "v2",
    "alternate_feed": None,
    "reverse_checks": [],
}

_CHAIN_MINIMAL = {
    "pipe_id": "pipe_x",
    "shutdown_valves": ["v1", "v2"],
    "shutdown_pipes": ["p1"],
    "tail_valve_id": "v2",
    "alternate_feed": None,
    "reverse_checks": [],
}


def test_render_chain_diagram_returns_png_bytes():
    png = render_chain_diagram(_CHAIN_WITH_ALT)
    assert png[:8] == _PNG_SIGNATURE
    assert len(png) > 1000


def test_render_chain_diagram_no_alt_feed_renders():
    png = render_chain_diagram(_CHAIN_NO_ALT)
    assert png[:8] == _PNG_SIGNATURE


def test_render_chain_diagram_minimal_chain_renders():
    png = render_chain_diagram(_CHAIN_MINIMAL)
    assert png[:8] == _PNG_SIGNATURE
