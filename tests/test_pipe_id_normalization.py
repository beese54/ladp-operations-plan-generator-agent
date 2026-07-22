"""Tests for casual pipe-reference normalization in the intent parser."""
from agents.orchestrator import _normalize_pipe_id


def test_normalizes_word_and_number_with_space():
    assert _normalize_pipe_id("pipe 67") == "pipe_067"


def test_normalizes_word_and_number_no_separator():
    assert _normalize_pipe_id("Pipe67") == "pipe_067"


def test_normalizes_word_and_number_with_dash():
    assert _normalize_pipe_id("PIPE-67") == "pipe_067"


def test_normalizes_bare_number():
    assert _normalize_pipe_id("67") == "pipe_067"


def test_canonical_id_is_idempotent():
    assert _normalize_pipe_id("pipe_067") == "pipe_067"
    assert _normalize_pipe_id("pipe_151") == "pipe_151"


def test_leading_zeros_in_input_are_reduced_correctly():
    assert _normalize_pipe_id("067") == "pipe_067"


def test_ids_with_four_or_more_digits_are_not_truncated():
    assert _normalize_pipe_id("pipe 1000") == "pipe_1000"


def test_unrecognized_format_passes_through_unchanged():
    assert _normalize_pipe_id("P-001") == "P-001"


def test_none_and_empty_pass_through():
    assert _normalize_pipe_id(None) is None
    assert _normalize_pipe_id("") == ""
