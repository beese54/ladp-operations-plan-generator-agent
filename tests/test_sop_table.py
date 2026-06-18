"""Tests for the markdown-table SOP walkthrough renderer (chat UI)."""
from prompts.sop_walkthrough_prompt import format_sop_walkthrough_table


def _chain(alt=True):
    return {
        "pipe_id": "pipe_084",
        "from_valve_id": "valve_034",
        "to_valve_id": "valve_035",
        "pipe_road_name": "Bukit Batok Street 22",
        "pipe_status": "open",
        "steps": [
            {"from_valve": "valve_035", "pipe_id": "pipe_086", "to_valve": "valve_036", "status": "open"},
            {"from_valve": "valve_036", "pipe_id": "pipe_088", "to_valve": "valve_037", "status": "open"},
        ],
        "tail_valve_id": "valve_037",
        "alternate_feed": {"pipe_id": "pipe_091", "from_valve_id": "valve_038", "status": "open"} if alt else None,
        "shutdown_pipes": ["pipe_084", "pipe_086", "pipe_088"],
        "shutdown_valves": ["valve_034", "valve_035", "valve_036", "valve_037"],
        "reverse_checks": [
            {"from_valve": "valve_037", "to_valve": "valve_036", "pipe_id": "pipe_089", "status": "closed", "ok": True},
            {"from_valve": "valve_036", "to_valve": "valve_035", "pipe_id": "pipe_087", "status": "closed", "ok": True},
        ],
        "downstream_valves_with_roads": [
            {"valve_id": "valve_036", "road_name": "Bukit Batok Street 22"},
            {"valve_id": "valve_037", "road_name": "Bukit Batok Street 22"},
        ],
    }


def test_table_has_markdown_header_and_core_rows():
    out = format_sop_walkthrough_table(_chain())
    assert out.startswith("### Isolation procedure — `pipe_084`")
    assert "| Step | Stage | Detail |" in out
    assert "|------|-------|--------|" in out
    # trace rows are numbered, tail + canonical 9-12 present
    assert "| 1 | Downstream trace |" in out
    assert "Tail-end valve" in out
    assert "| 10 | Shutdown chain | close in order:" in out
    assert "| 11 | Affected valves |" in out
    # cells must not contain stray pipes that would break the table
    for line in out.splitlines():
        if line.startswith("|"):
            assert line.count("|") >= 4  # leading + 3 columns + trailing


def test_table_alt_feed_branch():
    out = format_sop_walkthrough_table(_chain(alt=True))
    assert "| 9 | Alternate feed | ✅ available via `pipe_091`" in out
    assert "| 12 | Re-feed reversal |" in out
    assert "final shutdown" in out
    # tail valve spared when an alternate feed exists
    assert "valve_037` spared" in out


def test_table_no_alt_feed_branch():
    out = format_sop_walkthrough_table(_chain(alt=False))
    assert "| 9 | Alternate feed | ❌ none" in out
    assert "| 12 | No alternate feed |" in out
