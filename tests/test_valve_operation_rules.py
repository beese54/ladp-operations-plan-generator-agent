"""Tests for the valve-operation timing SOP (data/seed/sop_documents/valve_operation_sop.md)."""
import pytest

from tools import valve_operation_rules as vor


# ── turns (ceiling) ──
def test_valve_turns_ceiling():
    assert vor.valve_turns(300) == 25   # 11.81*2+1 = 24.62 -> 25
    assert vor.valve_turns(700) == 57   # 27.56*2+1 = 56.12 -> 57
    assert vor.valve_turns(900) == 72   # 35.43*2+1 = 71.87 -> 72


# ── per-valve action times ──
def test_small_valve_open_and_close_equal():
    assert vor.valve_action_minutes(300, "OPEN") == pytest.approx(32.5)
    assert vor.valve_action_minutes(300, "CLOSE") == pytest.approx(32.5)


def test_large_valve_close_is_slower_than_open():
    # 700mm T=57: open 1.3*57=74.1, close 1.9*57=108.3
    assert vor.valve_action_minutes(700, "OPEN") == pytest.approx(74.1)
    assert vor.valve_action_minutes(700, "CLOSE") == pytest.approx(108.3)


def test_boundary_500mm_uses_small_rule():
    t = vor.valve_turns(500)
    assert vor.valve_action_minutes(500, "CLOSE") == pytest.approx(1.3 * t)


# ── sequence + travel ──
def test_operation_minutes_includes_travel():
    # two 300mm closes: 2*32.5 + 1*20 travel
    assert vor.operation_minutes([(300, "CLOSE"), (300, "CLOSE")]) == pytest.approx(85.0)


def test_operation_minutes_empty():
    assert vor.operation_minutes([]) == 0.0


# ── chain -> actions ──
def test_chain_actions_no_alt_feed_is_closes_only():
    chain = {"shutdown_valves": ["v1", "v2"], "valve_diameters": {"v1": 300, "v2": 700}}
    assert vor.chain_valve_actions(chain) == [(300, "CLOSE"), (700, "CLOSE")]


def test_chain_actions_with_alt_feed_adds_opens():
    chain = {
        "shutdown_valves": ["v1", "v2"],
        "alternate_feed": {"from_valve_id": "va"},
        "reverse_checks": [{"from_valve": "r1", "to_valve": "x"},
                           {"from_valve": "r2", "to_valve": "y"}],
        "valve_diameters": {k: 300 for k in ["v1", "v2", "va", "r1", "r2"]},
    }
    assert [a for _, a in vor.chain_valve_actions(chain)] == \
        ["CLOSE", "CLOSE", "OPEN", "OPEN", "OPEN"]


def test_unknown_diameter_defaults_small():
    assert vor.chain_valve_actions({"shutdown_valves": ["vx"]}) == [(300, "CLOSE")]


def test_operation_duration_hours_pipe084_shape():
    # 4 closes + 1 alt-feed open + 3 reverse opens = 8 actions, all 300mm
    chain = {
        "shutdown_valves": ["v1", "v2", "v3", "v4"],
        "alternate_feed": {"from_valve_id": "va"},
        "reverse_checks": [{"from_valve": "r1", "to_valve": "x"},
                           {"from_valve": "r2", "to_valve": "y"},
                           {"from_valve": "r3", "to_valve": "z"}],
        "valve_diameters": {k: 300 for k in
                            ["v1", "v2", "v3", "v4", "va", "r1", "r2", "r3"]},
    }
    # 8*32.5 + 7*20 = 400 min
    assert vor.operation_duration_hours(chain) == pytest.approx(400 / 60)
