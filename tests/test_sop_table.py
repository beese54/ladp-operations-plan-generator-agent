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
    assert "| 1 | Downstream trace |" in out
    assert "Tail-end valve" in out
    assert "Shutdown chain | close in order:" in out
    assert "Affected valves |" in out
    # cells must not contain stray pipes that would break the table
    for line in out.splitlines():
        if line.startswith("|"):
            assert line.count("|") >= 4  # leading + 3 columns + trailing


def test_table_steps_are_sequential():
    out = format_sop_walkthrough_table(_chain())
    nums = [int(line.split("|")[1].strip())
            for line in out.splitlines()
            if line.startswith("|") and line.split("|")[1].strip().isdigit()]
    assert nums == list(range(1, len(nums) + 1))  # 1,2,3,... no gaps


def test_table_alt_feed_branch():
    out = format_sop_walkthrough_table(_chain(alt=True))
    assert "Alternate feed | ✅ available via `pipe_091`" in out
    assert "Re-feed reversal |" in out
    assert "final shutdown" in out
    # tail valve spared when an alternate feed exists
    assert "valve_037` spared" in out


def test_table_no_alt_feed_branch():
    out = format_sop_walkthrough_table(_chain(alt=False))
    assert "Alternate feed | ❌ none" in out
    assert "No alternate feed |" in out
