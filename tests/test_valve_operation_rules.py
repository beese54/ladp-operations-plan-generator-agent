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


# ── chain -> per-step identity (chain_valve_steps) ──
def test_chain_valve_steps_matches_chain_valve_actions_no_alt():
    chain = {"shutdown_valves": ["v1", "v2"], "valve_diameters": {"v1": 300, "v2": 700}}
    steps = vor.chain_valve_steps(chain)
    assert [(s.diameter_mm, s.action) for s in steps] == vor.chain_valve_actions(chain)


def test_chain_valve_steps_matches_chain_valve_actions_with_alt():
    chain = {
        "shutdown_valves": ["v1", "v2"],
        "alternate_feed": {"from_valve_id": "va", "pipe_id": "p-alt"},
        "reverse_checks": [{"from_valve": "r1", "to_valve": "x", "pipe_id": "p-r1"},
                           {"from_valve": "r2", "to_valve": "y", "pipe_id": "p-r2"}],
        "valve_diameters": {k: 300 for k in ["v1", "v2", "va", "r1", "r2"]},
    }
    steps = vor.chain_valve_steps(chain)
    assert [(s.diameter_mm, s.action) for s in steps] == vor.chain_valve_actions(chain)
    assert [s.valve_id for s in steps] == ["v1", "v2", "va", "r1", "r2"]
    assert [s.seq for s in steps] == [1, 2, 3, 4, 5]


def test_chain_valve_steps_pipe_id_mapping():
    chain = {
        "shutdown_valves": ["v1", "v2", "v3"],
        "shutdown_pipes": ["p1", "p2"],
        "alternate_feed": {"from_valve_id": "va", "pipe_id": "p-alt"},
        "reverse_checks": [{"from_valve": "v3", "to_valve": "v2", "pipe_id": "p-r1"}],
        "valve_diameters": {k: 300 for k in ["v1", "v2", "v3", "va"]},
    }
    steps = vor.chain_valve_steps(chain)
    by_seq = {s.seq: s for s in steps}
    assert by_seq[1].pipe_id == "p1"      # v1 -> p1
    assert by_seq[2].pipe_id == "p2"      # v2 -> p2
    assert by_seq[3].pipe_id is None      # tail valve v3, no following pipe
    assert by_seq[4].pipe_id == "p-alt"   # alt-feed OPEN
    assert by_seq[5].pipe_id == "p-r1"    # reverse-check OPEN


def test_chain_valve_steps_travel_minutes_zero_for_first_only():
    chain = {"shutdown_valves": ["v1", "v2", "v3"], "valve_diameters": {"v1": 300, "v2": 300, "v3": 300}}
    steps = vor.chain_valve_steps(chain)
    assert steps[0].travel_minutes == 0.0
    assert steps[1].travel_minutes == vor.DAILY_TRAVEL_MINUTES
    assert steps[2].travel_minutes == vor.DAILY_TRAVEL_MINUTES
    assert steps[0].total_minutes == steps[0].action_minutes
