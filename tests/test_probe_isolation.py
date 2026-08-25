"""Guard: the probe harness must never show the model the ground-truth answer.

If a request body ever carried `ground_truth` (or `expected_behaviour`, or the
`rag_gap_hypothesis`), every score the harness produces would be worthless —
the model would be grading itself against an answer it was handed. These tests
exist so that failure mode can't be introduced silently later.

The question bank is loaded from the real CSV, so this also acts as a schema
check on the dataset itself.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

# scripts/ isn't a package, so load the module by path.
_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "probe_chatbot.py"
_spec = importlib.util.spec_from_file_location("probe_chatbot", _SCRIPT)
probe = importlib.util.module_from_spec(_spec)
sys.modules["probe_chatbot"] = probe
_spec.loader.exec_module(probe)


ALLOWED_PAYLOAD_KEYS = {"session_id", "message"}

# Columns that must never reach the model.
LEAKY_COLUMNS = ("ground_truth", "expected_behaviour", "rag_gap_hypothesis",
                 "sme_verified", "difficulty", "category")


@pytest.fixture(scope="module")
def rows():
    loaded = probe.load_questions()
    assert loaded, "question bank is empty"
    return loaded


# ── Payload construction ──────────────────────────────────────────────────────

class TestRequestPayload:
    def test_payload_has_only_session_and_message(self):
        payload = probe.build_request_payload("Which valves isolate pipe_084?", "s1")
        assert set(payload) == ALLOWED_PAYLOAD_KEYS

    def test_message_is_the_question_verbatim(self):
        q = "How many turns to fully close valve_021?"
        payload = probe.build_request_payload(q, "s1")
        assert payload["message"] == q

    def test_payload_signature_takes_a_string_not_a_row(self):
        """A dict row would let ground truth in through the front door."""
        import inspect
        sig = inspect.signature(probe.build_request_payload)
        assert list(sig.parameters) == ["question", "session_id"]

    def test_ask_does_not_accept_a_row(self):
        import inspect
        sig = inspect.signature(probe.ask)
        assert "row" not in sig.parameters
        assert "ground_truth" not in sig.parameters


# ── Against the real dataset ──────────────────────────────────────────────────

class TestNoLeakForRealRows:
    def test_no_row_leaks_any_extra_column(self, rows):
        for row in rows:
            payload = probe.build_request_payload(row["question"], "s1")
            assert set(payload) == ALLOWED_PAYLOAD_KEYS, row["id"]

    def test_ground_truth_text_never_appears_in_payload(self, rows):
        """The strongest form of the check: for every row that HAS an SME answer,
        assert that answer's text is absent from the serialised request body."""
        checked = 0
        for row in rows:
            gt = (row.get("ground_truth") or "").strip()
            if not gt:
                continue
            checked += 1
            body = json.dumps(probe.build_request_payload(row["question"], "s1"))
            assert gt not in body, f"{row['id']}: ground truth leaked into payload"
            # Also check a distinctive fragment, in case of partial inclusion.
            fragment = gt[:40]
            assert fragment not in body, f"{row['id']}: ground-truth fragment leaked"
        assert checked >= 15, (
            f"expected the bank to contain SME answers to test against, found {checked}"
        )

    def test_expected_behaviour_never_appears_in_payload(self, rows):
        for row in rows:
            eb = (row.get("expected_behaviour") or "").strip()
            if not eb:
                continue
            body = json.dumps(probe.build_request_payload(row["question"], "s1"))
            assert eb not in body, f"{row['id']}: expected_behaviour leaked"


# ── Classification must not consult the answer key ────────────────────────────

class TestClassificationIndependence:
    def test_verdict_ignores_ground_truth(self):
        """classify() reads should_answer (the grading contract) but must not be
        swayed by whether a ground_truth string happens to be present."""
        resp = {"ok": True, "answer": "A" * 400, "latency_ms": 100,
                "awaiting_clarification": False}
        with_gt = probe.classify(
            {"should_answer": "YES", "ground_truth": "some expert answer"}, resp)
        without_gt = probe.classify(
            {"should_answer": "YES", "ground_truth": ""}, resp)
        assert with_gt["verdict"] == without_gt["verdict"]

    def test_out_of_scope_grading_is_on_refusal_only(self):
        declined = {"ok": True, "answer": "I can't help with that.",
                    "latency_ms": 10, "awaiting_clarification": False}
        answered = {"ok": True, "answer": "The capital of France is Paris." * 20,
                    "latency_ms": 10, "awaiting_clarification": False}
        row = {"should_answer": "NO", "ground_truth": ""}
        assert probe.classify(row, declined)["verdict"] == "PASS"
        assert probe.classify(row, answered)["verdict"] == "FAIL"


# ── Dataset schema ────────────────────────────────────────────────────────────

class TestDatasetIntegrity:
    def test_required_columns_present(self, rows):
        required = {"id", "persona", "difficulty", "category", "question",
                    "should_answer", "expected_behaviour", "rag_gap_hypothesis",
                    "sme_verified", "ground_truth"}
        assert required.issubset(rows[0].keys())

    def test_ids_unique(self, rows):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))

    def test_every_row_has_a_question(self, rows):
        for r in rows:
            assert r["question"].strip(), r["id"]

    def test_sme_verified_implies_ground_truth(self, rows):
        for r in rows:
            if r["sme_verified"].strip().upper() == "YES":
                assert r["ground_truth"].strip(), f"{r['id']} verified but no answer"

    def test_ground_truth_implies_sme_verified(self, rows):
        """Prevents an answer being added without flagging it, which would make
        the correctness scorer silently skip it."""
        for r in rows:
            if r["ground_truth"].strip():
                assert r["sme_verified"].strip().upper() == "YES", \
                    f"{r['id']} has an answer but sme_verified is not YES"

    def test_out_of_scope_rows_have_no_ground_truth(self, rows):
        """Out-of-scope rows are graded on refusal; their ground_truth should be
        either empty or the special marker DECLINE."""
        for r in rows:
            if r["should_answer"].strip().upper() == "NO":
                gt = r["ground_truth"].strip()
                assert gt == "" or gt.upper() == "DECLINE", \
                    f"{r['id']} should_answer=NO but has ground_truth other than DECLINE: {gt!r}"

    def test_c01_pub_convention_is_preserved(self, rows):
        """C01 is a permanent regression test: PUB closes valves ANTICLOCKWISE,
        opposite to the usual industry convention. If an ingested third-party
        valve manual ever flips this, C01 is how we find out — so the row itself
        must not drift. See data/eval_datasets/GROUND_TRUTH_NOTES.md.
        """
        c01 = next((r for r in rows if r["id"] == "C01"), None)
        assert c01 is not None, "C01 must remain in the bank"
        gt = c01["ground_truth"].lower()
        assert "anticlockwise to close" in gt
        assert "clockwise to open" in gt
