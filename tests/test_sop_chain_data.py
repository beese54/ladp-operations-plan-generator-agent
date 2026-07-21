"""Regression test for the forward-trace cycle guard in build_sop_chain_data
(prompts/sop_walkthrough_prompt.py). Discovered live against pipe_051, whose
network has a same-road ring (pipe_049/pipe_050 both open between valve_020
and valve_021) that made the old unguarded `while True` trace loop forever.
"""
from prompts import sop_walkthrough_prompt as swp


def test_build_sop_chain_data_stops_at_a_same_road_cycle(monkeypatch):
    # Origin pipe P0: valve_A -> valve_B, road "Test Road".
    monkeypatch.setattr(swp, "get_pipe_and_valves", lambda pipe_id: {
        "from_valve": {"id": "valve_A"},
        "to_valve": {"id": "valve_B"},
        "pipe_props": {"road_name": "Test Road", "status": "open"},
    })

    # Forward trace: valve_B -> valve_C (P1), then valve_C -> valve_B (P2) —
    # a 2-node ring with no exit, mirroring pipe_051's real topology.
    def fake_execute_read(cypher, params):
        if "next_valve" in cypher and "road" in params:
            if params["vid"] == "valve_B":
                return [{"pipe_id": "P1", "next_valve": "valve_C", "pstatus": "open"}]
            if params["vid"] == "valve_C":
                return [{"pipe_id": "P2", "next_valve": "valve_B", "pstatus": "open"}]
        return []  # alt-feed / road-name / diameter lookups: nothing further

    monkeypatch.setattr(swp, "execute_read", fake_execute_read)

    chain = swp.build_sop_chain_data("P0")

    assert chain["shutdown_valves"] == ["valve_A", "valve_B", "valve_C"]
    assert chain["shutdown_pipes"] == ["P0", "P1"]
    assert chain["tail_valve_id"] == "valve_C"
    assert chain["alternate_feed"] is None


def test_build_sop_chain_data_no_cycle_is_unaffected(monkeypatch):
    # Sanity check: a normal linear chain (no ring) still traces to completion.
    monkeypatch.setattr(swp, "get_pipe_and_valves", lambda pipe_id: {
        "from_valve": {"id": "valve_A"},
        "to_valve": {"id": "valve_B"},
        "pipe_props": {"road_name": "Test Road", "status": "open"},
    })

    def fake_execute_read(cypher, params):
        if "next_valve" in cypher and "road" in params:
            if params["vid"] == "valve_B":
                return [{"pipe_id": "P1", "next_valve": "valve_C", "pstatus": "open"}]
        return []

    monkeypatch.setattr(swp, "execute_read", fake_execute_read)

    chain = swp.build_sop_chain_data("P0")

    assert chain["shutdown_valves"] == ["valve_A", "valve_B", "valve_C"]
    assert chain["shutdown_pipes"] == ["P0", "P1"]
    assert chain["tail_valve_id"] == "valve_C"
