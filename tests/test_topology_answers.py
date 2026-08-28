"""Tests for prompts/topology_answers.py

Neo4j is mocked throughout — these are unit tests of the routing/formatting logic,
not of the graph. Two properties matter most:
  1. A question naming a pipe/valve gets a real answer instead of
     "not part of the documented procedure" (the baseline failure).
  2. Matching stays narrow: no asset ID, or nothing the graph can answer,
     returns None so the SOP corpus path is preserved.
"""
import pytest

from prompts import topology_answers as ta
from prompts.topology_answers import (
    _canonical_pipe,
    _canonical_valve,
    _extract_ids,
    answer_topology_question,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

PIPE_DATA = {
    "from_valve": {"id": "valve_001", "road_name": "bukit batok west avenue 5"},
    "to_valve": {"id": "valve_002", "road_name": "bukit batok west avenue 2"},
    "pipe_props": {
        "pipe_id": "pipe_003",
        "road_name": "Bukit Batok Link",
        "material": "Steel",
        "diameter_mm": 900,
        "length_m": 85.0,
        "pressure_mRL": 30.0,
        "status": "open",
        "year_installed": 2026,
    },
}

CHAIN_WITH_ALT = {
    "pipe_id": "pipe_084",
    "pipe_road_name": "Bukit Batok Street 22",
    "shutdown_valves": ["valve_034", "valve_035", "valve_036"],
    "shutdown_pipes": ["pipe_084", "pipe_086"],
    "tail_valve_id": "valve_036",
    "alternate_feed": {"pipe_id": "pipe_090", "from_valve_id": "valve_040", "status": "open"},
    "downstream_valves_with_roads": [],
}

CHAIN_NO_ALT = {
    **CHAIN_WITH_ALT,
    "alternate_feed": None,
    "downstream_valves_with_roads": [
        {"valve_id": "valve_050", "road_name": "Test Road"},
        {"valve_id": "valve_051", "road_name": "Another Road"},
    ],
}

NEIGHBOURHOOD_900 = [
    {"pipe_id": "pipe_003", "diameter_mm": 900, "road_name": "Bukit Batok Link"},
    {"pipe_id": "pipe_005", "diameter_mm": 700, "road_name": "Ave 7"},
]

NEIGHBOURHOOD_300 = [
    {"pipe_id": "pipe_055", "diameter_mm": 300, "road_name": "St 34"},
]


@pytest.fixture
def mock_pipe(monkeypatch):
    import tools.neo4j_tools as nt
    monkeypatch.setattr(nt, "get_pipe_and_valves", lambda pid: PIPE_DATA)


@pytest.fixture
def mock_pipe_missing(monkeypatch):
    import tools.neo4j_tools as nt
    monkeypatch.setattr(nt, "get_pipe_and_valves", lambda pid: {})


@pytest.fixture
def mock_chain_alt(monkeypatch):
    import prompts.sop_walkthrough_prompt as sw
    monkeypatch.setattr(sw, "build_sop_chain_data", lambda pid: CHAIN_WITH_ALT)


@pytest.fixture
def mock_chain_no_alt(monkeypatch):
    import prompts.sop_walkthrough_prompt as sw
    monkeypatch.setattr(sw, "build_sop_chain_data", lambda pid: CHAIN_NO_ALT)


@pytest.fixture
def mock_valve_900(monkeypatch):
    import tools.neo4j_tools as nt
    monkeypatch.setattr(nt, "get_neighborhood_pipes", lambda vid: NEIGHBOURHOOD_900)


@pytest.fixture
def mock_valve_300(monkeypatch):
    import tools.neo4j_tools as nt
    monkeypatch.setattr(nt, "get_neighborhood_pipes", lambda vid: NEIGHBOURHOOD_300)


# ── ID extraction ─────────────────────────────────────────────────────────────

class TestIdExtraction:
    @pytest.mark.parametrize("raw,expected", [
        ("pipe_084", "pipe_084"),
        ("pipe 84", "pipe_084"),
        ("PIPE_84", "pipe_084"),
        ("pipe-84", "pipe_084"),
        ("pipe_3", "pipe_003"),
    ])
    def test_pipe_forms_normalise(self, raw, expected):
        pipe, _ = _extract_ids(f"tell me about {raw}")
        assert pipe == expected

    @pytest.mark.parametrize("raw,expected", [
        ("valve_021", "valve_021"),
        ("valve 21", "valve_021"),
        ("VALVE_21", "valve_021"),
    ])
    def test_valve_forms_normalise(self, raw, expected):
        _, valve = _extract_ids(f"how many turns for {raw}")
        assert valve == expected

    def test_no_id_returns_none_pair(self):
        assert _extract_ids("what is a gate valve?") == (None, None)

    def test_canonical_padding(self):
        assert _canonical_pipe("3") == "pipe_003"
        assert _canonical_valve("7") == "valve_007"


# ── Isolation chain (probe P01) ───────────────────────────────────────────────

class TestIsolationChain:
    def test_which_valves_isolate_gets_answer(self, mock_chain_alt):
        answer = answer_topology_question("Which valves isolate pipe_084?")
        assert answer is not None
        for v in CHAIN_WITH_ALT["shutdown_valves"]:
            assert v in answer

    def test_reports_tail_valve(self, mock_chain_alt):
        answer = answer_topology_question("Which valves isolate pipe_084?")
        assert CHAIN_WITH_ALT["tail_valve_id"] in answer

    def test_reports_alternate_feed(self, mock_chain_alt):
        answer = answer_topology_question("what valves do I close to shut down pipe_084?")
        assert "pipe_090" in answer
        assert "lternate feed" in answer

    def test_no_alternate_feed_names_affected_roads(self, mock_chain_no_alt):
        answer = answer_topology_question("Which valves isolate pipe_084?")
        assert "No alternate feed" in answer
        assert "Test Road" in answer

    def test_unknown_pipe_falls_through(self, monkeypatch):
        import prompts.sop_walkthrough_prompt as sw

        def raise_missing(pid):
            raise ValueError("not found")

        monkeypatch.setattr(sw, "build_sop_chain_data", raise_missing)
        assert answer_topology_question("Which valves isolate pipe_999?") is None

    def test_graph_error_falls_through(self, monkeypatch):
        import prompts.sop_walkthrough_prompt as sw

        def boom(pid):
            raise RuntimeError("neo4j down")

        monkeypatch.setattr(sw, "build_sop_chain_data", boom)
        assert answer_topology_question("Which valves isolate pipe_084?") is None


# ── Pipe properties (probe P02) ───────────────────────────────────────────────

class TestPipeProperties:
    def test_what_road_gets_answer(self, mock_pipe):
        answer = answer_topology_question("What road is pipe_033 on?")
        assert answer is not None
        assert "Bukit Batok Link" in answer

    def test_material_question_gets_answer(self, mock_pipe):
        answer = answer_topology_question("What is pipe_084 made of?")
        assert answer is not None
        assert "Steel" in answer

    def test_includes_diameter_and_status(self, mock_pipe):
        answer = answer_topology_question("tell me about pipe_003")
        assert "900" in answer
        assert "open" in answer

    def test_missing_pipe_falls_through(self, mock_pipe_missing):
        assert answer_topology_question("What road is pipe_999 on?") is None

    def test_unrecorded_field_says_not_recorded(self, monkeypatch):
        import tools.neo4j_tools as nt
        sparse = {
            "from_valve": {"id": "valve_001"},
            "to_valve": {"id": "valve_002"},
            "pipe_props": {"pipe_id": "pipe_003", "road_name": "Some Road"},
        }
        monkeypatch.setattr(nt, "get_pipe_and_valves", lambda pid: sparse)
        answer = answer_topology_question("What is pipe_003 made of?")
        assert "not recorded" in answer


# ── Valve turns (probe C02) ───────────────────────────────────────────────────

class TestValveTurns:
    def test_how_many_turns_gets_answer(self, mock_valve_900):
        answer = answer_topology_question("How many turns to fully close valve_021?")
        assert answer is not None
        assert "turns" in answer.lower()

    def test_turn_count_matches_engine(self, mock_valve_900):
        from tools import valve_operation_rules as vr
        expected = vr.valve_turns(900)
        answer = answer_topology_question("How many turns for valve_021?")
        assert str(expected) in answer

    def test_large_valve_notes_slow_close(self, mock_valve_900):
        answer = answer_topology_question("How many turns to close valve_001?")
        assert "surge" in answer.lower()

    def test_small_valve_omits_large_note(self, mock_valve_300):
        answer = answer_topology_question("How many turns to close valve_055?")
        assert "surge" not in answer.lower()

    def test_states_diameter_is_inferred(self, mock_valve_900):
        """The valve's own diameter isn't reliably stored, so the answer must not
        present the inferred figure as a specification."""
        answer = answer_topology_question("How many turns for valve_021?")
        assert "inferred" in answer.lower()

    def test_no_diameter_data_falls_through(self, monkeypatch):
        import tools.neo4j_tools as nt
        monkeypatch.setattr(nt, "get_neighborhood_pipes",
                            lambda vid: [{"pipe_id": "p", "diameter_mm": None}])
        assert answer_topology_question("How many turns for valve_021?") is None

    def test_unknown_valve_falls_through(self, monkeypatch):
        import tools.neo4j_tools as nt
        monkeypatch.setattr(nt, "get_neighborhood_pipes", lambda vid: [])
        assert answer_topology_question("How many turns for valve_999?") is None


# ── Conservative matching ─────────────────────────────────────────────────────

class TestConservativeMatching:
    @pytest.mark.parametrize("question", [
        # No asset named — belongs to the SOP corpus or a reference document
        "What is a gate valve?",
        "What does mRL mean?",
        "What causes water hammer?",
        "Which direction do I turn to close the valve?",
        "What is the procedure when an alternate feed is available?",
        # Off topic
        "What is the capital of France?",
        "Tell me a joke",
    ])
    def test_no_asset_id_returns_none(self, question):
        assert answer_topology_question(question) is None

    def test_empty_input_returns_none(self):
        assert answer_topology_question("") is None

    def test_asset_named_but_nothing_answerable_returns_none(self, mock_pipe):
        """Naming a pipe isn't sufficient — the question must ask something the
        graph can answer, otherwise the SOP path should handle it."""
        assert answer_topology_question(
            "should I notify residents before working on pipe_003?") is None

    def test_isolation_takes_precedence_over_properties(self, mock_chain_alt, mock_pipe):
        """'Which valves isolate X' contains both isolation and property signals;
        the isolation chain is the more specific, more useful answer."""
        answer = answer_topology_question("Which valves isolate pipe_084?")
        assert "shutdown chain" in answer.lower()


class TestLiveDataNeverAnswered:
    """Regression guard. The first version of this module answered
    "show me the live pressure reading at valve_014" with the valve's STORED
    reference figures — a confidently wrong answer to a question about sensor
    data that this system has no integration for. The graph holds design values,
    not readings, so live-data questions must fall through and be declined.
    """

    @pytest.mark.parametrize("question", [
        "Can you show me the live pressure reading at valve_014?",
        "What is the current pressure at valve_014?",
        "What's the real-time status of pipe_003?",
        "Is valve_021 currently open?",
        "What is the latest reading at valve_001?",
        "Show me the sensor data for pipe_084",
        "What is the actual pressure in pipe_033 right now?",
    ])
    def test_live_data_requests_fall_through(self, question, mock_valve_900, mock_pipe):
        assert answer_topology_question(question) is None, (
            f"live-data question was answered from static graph: {question!r}"
        )

    def test_static_property_question_still_answered(self, mock_pipe):
        """The exclusion must not swallow legitimate reference-data questions."""
        assert answer_topology_question("What is the design pressure of pipe_033?") is not None
