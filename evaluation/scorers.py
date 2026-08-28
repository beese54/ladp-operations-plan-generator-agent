"""
MLflow scorers for the Ops Plan Generator.

Phase A: Fixed for MLflow 3.14+ (eval_fn= keyword required).
Phase B: Added RAG Triad scorers (context_relevance, groundedness, answer_relevance,
         answer_correctness).

IMPORTANT: The blanket `except Exception` that previously silently swallowed EVERY
import error has been removed. If a scorer fails to initialize, it raises LOUDLY so
you find out immediately, not weeks later when someone wonders why all metrics are empty.

Scorer categories:
  Rule-based (deterministic, zero LLM cost):
    feasibility_match       — exact verdict match vs expected
    valve_count_adequate    — actual valve steps >= expected minimum
    intent_extraction       — pipe_id and date extracted correctly
    scope_fidelity          — never claims an unimplemented capability
    answer_correctness      — semantic overlap with SME ground truth (RAG Triad)
    groundedness            — answer vocabulary traces to retrieved chunks (RAG Triad)
    answer_relevance        — response addresses the question asked (RAG Triad)
    context_relevance       — retrieved chunks are relevant to the query (RAG Triad)
    refusal_accuracy        — out-of-scope questions correctly declined
"""
from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from typing import Any

import pandas as pd
from mlflow.metrics import MetricValue, make_metric

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# RULE-BASED SCORERS (deterministic, zero LLM cost)
# ═══════════════════════════════════════════════════════════════════════════════

# ── Feasibility Match ─────────────────────────────────────────────────────────

def _feasibility_match_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """1.0 if actual_verdict == expected_verdict, else 0.0."""
    if "actual_verdict" not in eval_df.columns or "targets" not in eval_df.columns:
        return MetricValue(scores=[0.0] * len(eval_df))
    scores = (eval_df["actual_verdict"] == eval_df["targets"]).astype(float)
    return MetricValue(scores=scores.tolist())


feasibility_match_scorer = make_metric(
    eval_fn=_feasibility_match_fn,
    name="feasibility_match",
    greater_is_better=True,
)


# ── Valve Count Adequate ──────────────────────────────────────────────────────

def _valve_count_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """1.0 if actual valve count meets the expected minimum, else 0.0."""
    if "actual_valve_count" not in eval_df.columns:
        return MetricValue(scores=[0.0] * len(eval_df))
    scores = (
        eval_df["actual_valve_count"].fillna(0).astype(int)
        >= eval_df["expected_min_valve_steps"].fillna(0).astype(int)
    ).astype(float)
    return MetricValue(scores=scores.tolist())


valve_count_scorer = make_metric(
    eval_fn=_valve_count_fn,
    name="valve_count_adequate",
    greater_is_better=True,
)


# ── Intent Extraction Accuracy ────────────────────────────────────────────────

def _intent_accuracy_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """0.0 / 0.5 / 1.0 based on correct extraction of pipe_id and target_date."""
    if "actual_pipe_id" not in eval_df.columns:
        return MetricValue(scores=[0.0] * len(eval_df))
    pipe_match = (
        eval_df["actual_pipe_id"].fillna("") == eval_df["pipe_id"].fillna("")
    ).astype(float)
    date_match = (
        eval_df["actual_date"].fillna("") == eval_df["target_date"].fillna("")
    ).astype(float)
    scores = ((pipe_match + date_match) / 2).tolist()
    return MetricValue(scores=scores)


intent_accuracy_scorer = make_metric(
    eval_fn=_intent_accuracy_fn,
    name="intent_extraction_accuracy",
    greater_is_better=True,
)


# ── Scope Fidelity ───────────────────────────────────────────────────────────

def _scope_fidelity_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """1.0 unless actual_response contains a banned_phrases term."""
    def _row_score(response: str, banned: str) -> float:
        if not isinstance(banned, str) or not banned.strip():
            return 1.0
        response_lower = (response or "").lower()
        phrases = [p.strip().lower() for p in banned.split("|") if p.strip()]
        return 0.0 if any(p in response_lower for p in phrases) else 1.0

    banned_col = (eval_df["banned_phrases"]
                  if "banned_phrases" in eval_df.columns
                  else pd.Series([""] * len(eval_df)))
    response_col = eval_df.get("actual_response", pd.Series([""] * len(eval_df)))
    scores = [_row_score(r, b) for r, b in zip(response_col, banned_col)]
    return MetricValue(scores=scores)


scope_fidelity_scorer = make_metric(
    eval_fn=_scope_fidelity_fn,
    name="scope_fidelity",
    greater_is_better=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# RAG TRIAD SCORERS (deterministic heuristics — no LLM cost)
# ═══════════════════════════════════════════════════════════════════════════════
#
# The standard RAG Triad evaluates three axes:
#   1. Context Relevance — are retrieved chunks relevant to the question?
#   2. Groundedness (Faithfulness) — is the answer supported by the chunks?
#   3. Answer Relevance — does the answer address the question?
#
# Plus a fourth (from RAGAS):
#   4. Answer Correctness — does the answer match the SME ground truth?
#
# These implementations use heuristics (token overlap, SequenceMatcher) rather
# than LLM-as-judge. This keeps them FREE to run (no API calls), FAST (milliseconds
# per row), and DETERMINISTIC (same input always produces the same score). A
# threshold of 0.0 means "completely wrong" and 1.0 means "perfect".
#
# For the triad to work, the probe harness must log two additional columns:
#   - "retrieved_chunks": the concatenated text of chunks that were retrieved
#   - "answer_path": which tier answered (system_knowledge | topology | sop_rag | ...)

def _normalise_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for scoring."""
    t = (text or "").lower()
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _token_overlap(text_a: str, text_b: str) -> float:
    """Proportion of tokens in text_a that also appear in text_b (0.0–1.0).

    Directional: measures how much of A is covered by B. Used for groundedness
    (how much of the answer's vocabulary appears in the context) and context
    relevance (how much of the question's vocabulary appears in the chunks).
    """
    tokens_a = set(_normalise_text(text_a).split())
    tokens_b = set(_normalise_text(text_b).split())
    if not tokens_a:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a)


def _semantic_similarity(text_a: str, text_b: str) -> float:
    """SequenceMatcher ratio between normalised texts (0.0–1.0).

    Not true semantic similarity (that would require embeddings), but a
    reasonable proxy for answer correctness scoring where we're comparing
    an SME answer to the model's answer — both describe the same procedure
    in similar words. Good enough for a deterministic scorer; upgrade to
    embedding cosine similarity later if needed.
    """
    a = _normalise_text(text_a)
    b = _normalise_text(text_b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ── Answer Correctness (vs SME Ground Truth) ─────────────────────────────────

def _answer_correctness_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """Semantic similarity between the model's answer and the SME ground truth.

    Only scored on rows where ground_truth is non-empty and not 'DECLINE'.
    Rows without a ground truth score 1.0 (neutral — they don't drag down the
    average for lack of an answer to compare against).
    """
    scores = []
    response_col = eval_df.get("actual_response", pd.Series([""] * len(eval_df)))
    gt_col = eval_df.get("ground_truth", pd.Series([""] * len(eval_df)))

    for response, gt in zip(response_col, gt_col):
        gt_str = str(gt or "").strip()
        if not gt_str or gt_str.upper() == "DECLINE":
            scores.append(1.0)  # no ground truth to compare → neutral
            continue
        scores.append(_semantic_similarity(str(response), gt_str))
    return MetricValue(scores=scores)


answer_correctness_scorer = make_metric(
    eval_fn=_answer_correctness_fn,
    name="answer_correctness",
    greater_is_better=True,
)


# ── Groundedness (Faithfulness to Retrieved Context) ──────────────────────────

def _groundedness_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """How much of the answer's vocabulary appears in the retrieved chunks.

    High score = the answer draws its words from the source material.
    Low score = the answer introduces terms/claims not found in context.

    Only meaningful for the sop_rag path. For deterministic paths
    (system_knowledge, topology), groundedness is 1.0 by construction.
    Rows without retrieved_chunks score 1.0 (can't measure, assume grounded).
    """
    scores = []
    response_col = eval_df.get("actual_response", pd.Series([""] * len(eval_df)))
    chunks_col = eval_df.get("retrieved_chunks", pd.Series([""] * len(eval_df)))
    path_col = eval_df.get("answer_path", pd.Series([""] * len(eval_df)))

    for response, chunks, path in zip(response_col, chunks_col, path_col):
        path_str = str(path or "").strip().lower()
        # Deterministic paths are grounded by construction
        if path_str in ("system_knowledge", "topology", "off_topic", ""):
            scores.append(1.0)
            continue
        chunks_str = str(chunks or "").strip()
        if not chunks_str:
            scores.append(1.0)  # no chunks logged → can't score
            continue
        scores.append(_token_overlap(str(response), chunks_str))
    return MetricValue(scores=scores)


groundedness_scorer = make_metric(
    eval_fn=_groundedness_fn,
    name="groundedness",
    greater_is_better=True,
)


# ── Answer Relevance ──────────────────────────────────────────────────────────

def _answer_relevance_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """Does the answer address the question asked?

    Measured by token overlap between the question and the answer. A relevant
    answer should echo key terms from the question (pipe IDs, valve IDs,
    technical terms). A completely off-topic answer will share few tokens.

    Known limitation: a correct refusal ("I can't help with that") will score
    low because it doesn't echo question terms. For should_answer=NO rows,
    we score 1.0 if the answer is short (a refusal) and 0.0 if long (the
    model answered something it shouldn't have).
    """
    scores = []
    response_col = eval_df.get("actual_response", pd.Series([""] * len(eval_df)))
    question_col = eval_df.get("question", pd.Series([""] * len(eval_df)))
    should_col = eval_df.get("should_answer", pd.Series(["YES"] * len(eval_df)))

    for response, question, should in zip(response_col, question_col, should_col):
        response_str = str(response or "").strip()
        should_str = str(should or "").strip().upper()

        # Out-of-scope: relevance = did it refuse?
        if should_str == "NO":
            scores.append(1.0 if len(response_str) < 200 else 0.0)
            continue

        # In-scope: does the answer echo the question's key terms?
        scores.append(_token_overlap(str(question), response_str))
    return MetricValue(scores=scores)


answer_relevance_scorer = make_metric(
    eval_fn=_answer_relevance_fn,
    name="answer_relevance",
    greater_is_better=True,
)


# ── Context Relevance ─────────────────────────────────────────────────────────

def _context_relevance_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """Are the retrieved chunks relevant to the question?

    Measured by token overlap between the question and the retrieved chunks.
    High score = the retrieval found chunks that share vocabulary with the query.
    Low score = irrelevant chunks were pulled (bad embeddings or chunking).

    Only meaningful for sop_rag path. Deterministic paths score 1.0.
    """
    scores = []
    question_col = eval_df.get("question", pd.Series([""] * len(eval_df)))
    chunks_col = eval_df.get("retrieved_chunks", pd.Series([""] * len(eval_df)))
    path_col = eval_df.get("answer_path", pd.Series([""] * len(eval_df)))

    for question, chunks, path in zip(question_col, chunks_col, path_col):
        path_str = str(path or "").strip().lower()
        if path_str in ("system_knowledge", "topology", "off_topic", ""):
            scores.append(1.0)
            continue
        chunks_str = str(chunks or "").strip()
        if not chunks_str:
            scores.append(0.0)  # no chunks retrieved = relevance unknown/zero
            continue
        scores.append(_token_overlap(str(question), chunks_str))
    return MetricValue(scores=scores)


context_relevance_scorer = make_metric(
    eval_fn=_context_relevance_fn,
    name="context_relevance",
    greater_is_better=True,
)


# ── Refusal Accuracy ──────────────────────────────────────────────────────────

def _refusal_accuracy_fn(eval_df: pd.DataFrame, _builtin) -> MetricValue:
    """Did the system refuse out-of-scope questions and answer in-scope ones?

    1.0 if:
      - should_answer=NO and the response is short (< 200 chars, a refusal)
      - should_answer=YES and the response is substantive (>= 200 chars)
    0.0 otherwise.
    """
    scores = []
    response_col = eval_df.get("actual_response", pd.Series([""] * len(eval_df)))
    should_col = eval_df.get("should_answer", pd.Series(["YES"] * len(eval_df)))

    for response, should in zip(response_col, should_col):
        response_str = str(response or "").strip()
        should_str = str(should or "").strip().upper()
        is_short = len(response_str) < 200

        if should_str == "NO":
            scores.append(1.0 if is_short else 0.0)
        else:
            scores.append(1.0 if not is_short else 0.5)  # 0.5 for thin but present
    return MetricValue(scores=scores)


refusal_accuracy_scorer = make_metric(
    eval_fn=_refusal_accuracy_fn,
    name="refusal_accuracy",
    greater_is_better=True,
)


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

# All scorers that exist and should always work. No try/except silencing —
# if any of these fail at import time, it's a real bug that must be fixed.
_ALL_SCORERS = [
    feasibility_match_scorer,
    valve_count_scorer,
    intent_accuracy_scorer,
    scope_fidelity_scorer,
    answer_correctness_scorer,
    groundedness_scorer,
    answer_relevance_scorer,
    context_relevance_scorer,
    refusal_accuracy_scorer,
]


def get_available_scorers() -> list:
    """Return all scorers. Raises if any are None (which would mean the module
    loaded incorrectly — previously this silently returned an empty list and
    the eval harness produced no scores for weeks without anyone noticing)."""
    for s in _ALL_SCORERS:
        if s is None:
            raise RuntimeError(
                f"A scorer in _ALL_SCORERS is None — this means make_metric() "
                f"failed during module load. Check the traceback above."
            )
    return list(_ALL_SCORERS)


def get_triad_scorers() -> list:
    """Return only the RAG Triad + correctness scorers."""
    return [
        context_relevance_scorer,
        groundedness_scorer,
        answer_relevance_scorer,
        answer_correctness_scorer,
    ]
