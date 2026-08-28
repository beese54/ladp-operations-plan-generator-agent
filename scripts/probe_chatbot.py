"""Probe the chatbot with a bank of ops-planner / field-crew / out-of-scope questions
and log every response for review.

Purpose: establish a BASELINE of answer quality before expanding the RAG corpus,
so improvements (and regressions) are measurable rather than anecdotal.

Usage:
    # Backend must be running on :8001
    PYTHONPATH=. python scripts/probe_chatbot.py
    PYTHONPATH=. python scripts/probe_chatbot.py --persona FIELD_CREW
    PYTHONPATH=. python scripts/probe_chatbot.py --limit 5
    PYTHONPATH=. python scripts/probe_chatbot.py --api http://localhost:8001

Outputs (both written to data/probe_results/):
    probe_<timestamp>.json  — machine-readable, for diffing across runs
    probe_<timestamp>.md    — human-readable review document

IMPORTANT: each question uses a FRESH session_id. The graph is checkpointed per
thread_id=session_id, so a shared session would let one question's clarification
interrupt swallow the next question as its answer.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

QUESTIONS_CSV = Path("data/eval_datasets/rag_probe_questions.csv")
RESULTS_DIR = Path("data/probe_results")
DEFAULT_API = "http://localhost:8001"

# Phrases that indicate the assistant declined / had no grounded answer. Used to
# auto-classify responses so a human doesn't have to read all 58 to find the gaps.
_DECLINE_PATTERNS = [
    r"\bi can'?t\b", r"\bi cannot\b", r"\bnot able to\b", r"\bunable to\b",
    r"\bdon'?t have\b", r"\bdo not have\b", r"\bnot available\b",
    r"\bnot addressed\b", r"\bdoes not (?:state|cover|mention|specify)\b",
    r"\bdo not (?:state|cover|mention|specify)\b",
    r"\bno (?:stored|documented|specific) \w+",
    r"\boutside (?:my|the) scope\b", r"\bonly (?:help|assist) with\b",
    r"\bfocus(?:ed)? on water network\b",
    r"\bnot something i can\b", r"\bi'?m not able\b",
    # The dominant phrasing this system actually emits — the grounded-retrieval
    # path funnels almost everything into some variant of "not in the SOP".
    r"\b(?:is|isn'?t|not) part of the documented procedure\b",
    r"\bnot part of\b",
    r"\bexcerpts? (?:do|does)(?: not|n'?t)\b",
    # "...and they don't include anything about jokes" / "they only cover ..."
    r"\bthey (?:do|does)(?: not|n'?t) (?:include|cover|address|mention)\b",
    r"\bthey only cover\b",
    r"\bi can only (?:answer|use|help)\b",
    # A leading bare "No." is the clearest possible decline.
    r"^\s*no[.,!]",
]
_DECLINE_RE = re.compile("|".join(_DECLINE_PATTERNS), re.IGNORECASE)

# The LLM writes typographic apostrophes (U+2019) and dashes, so a regex written
# with a plain ASCII "'" silently fails to match "I can't". This is the same
# false-negative class Barry hit in Phase 12's guardrail filter — normalise first.
_PUNCT_MAP = {
    "\u2019": "'", "\u2018": "'", "\u02bc": "'",   # curly / modifier apostrophes
    "\u201c": '"', "\u201d": '"',                   # curly double quotes
    "\u2014": "-", "\u2013": "-",                   # em / en dash
}


def _normalise(text: str) -> str:
    for src, dst in _PUNCT_MAP.items():
        text = text.replace(src, dst)
    return text

# A "thin" answer is short enough that it's likely a deflection rather than help.
_THIN_ANSWER_CHARS = 180


def load_questions(path: Path = QUESTIONS_CSV) -> list[dict[str, str]]:
    if not path.exists():
        sys.exit(f"Question bank not found: {path}")
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build_request_payload(question: str, session_id: str) -> dict[str, str]:
    """The ONLY place a chat request body is constructed.

    Deliberately takes the question as a plain string rather than the CSV row, so
    it is structurally impossible to leak `ground_truth`, `expected_behaviour` or
    `rag_gap_hypothesis` to the model. Evaluating against an answer the model was
    shown would make every score meaningless.

    Kept as a separate function so tests can assert the exact body — see
    tests/test_probe_isolation.py.
    """
    return {"session_id": session_id, "message": question}


def ask(api_base: str, question: str, timeout: float = 180.0,
        retries: int = 2) -> dict[str, Any]:
    """POST one question on a fresh session. Returns response dict + timing.

    Takes only the question text — never the CSV row (see
    build_request_payload). Retries transient transport failures (the dev server
    occasionally resets a connection under back-to-back LLM calls) so one blip
    doesn't leave a hole in the baseline.
    """
    last_error = ""
    for attempt in range(retries + 1):
        payload = json.dumps(
            build_request_payload(question, f"probe-{uuid4().hex[:12]}")
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{api_base.rstrip('/')}/api/v1/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.load(r)
            return {
                "ok": True,
                "answer": body.get("message", ""),
                "pipe_id": body.get("pipe_id"),
                "awaiting_clarification": bool(body.get("awaiting_clarification")),
                "has_plan": bool(body.get("has_plan")),
                "latency_ms": round((time.monotonic() - t0) * 1000),
                "attempts": attempt + 1,
                "answer_path": body.get("answer_path") or "",
                "retrieved_chunks": body.get("retrieved_chunks") or "",
            }
        except urllib.error.HTTPError as e:
            # A real HTTP status is a genuine answer from the server — don't retry.
            return {"ok": False, "answer": "",
                    "error": f"HTTP {e.code}: {e.read()[:200]!r}",
                    "latency_ms": round((time.monotonic() - t0) * 1000),
                    "attempts": attempt + 1}
        except Exception as e:
            last_error = str(e)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
    return {"ok": False, "answer": "", "error": last_error,
            "latency_ms": 0, "attempts": retries + 1}


def classify(row: dict[str, str], resp: dict[str, Any]) -> dict[str, Any]:
    """Auto-label the response and compute RAG triad scores."""
    answer = resp.get("answer") or ""
    declined = bool(_DECLINE_RE.search(_normalise(answer)))
    thin = len(answer.strip()) < _THIN_ANSWER_CHARS
    should_answer = (row.get("should_answer") or "").strip().upper() == "YES"
    clarifying = resp.get("awaiting_clarification", False)

    if not resp.get("ok"):
        verdict, note = "ERROR", "request failed"
    elif not should_answer:
        # Out-of-scope: declining is the CORRECT behaviour.
        verdict = "PASS" if declined else "FAIL"
        note = ("correctly declined" if declined
                else "answered a question it should have refused")
    elif clarifying:
        verdict, note = "CLARIFY", "asked a follow-up question instead of answering"
    elif declined:
        # In-scope but no grounded answer — this is the RAG gap signal.
        verdict, note = "GAP", "in-scope but no grounded answer available"
    elif thin:
        verdict, note = "THIN", f"answered but only {len(answer.strip())} chars"
    else:
        verdict, note = "ANSWERED", "substantive answer given"

    # ── RAG Triad scores ──────────────────────────────────────────────────────
    answer_path = resp.get("answer_path") or ""
    retrieved_chunks = resp.get("retrieved_chunks") or ""
    question = row.get("question", "")
    ground_truth = (row.get("ground_truth") or "").strip()

    triad = _compute_triad(question, answer, retrieved_chunks, ground_truth,
                           answer_path, should_answer)

    return {"verdict": verdict, "note": note, "declined": declined,
            "answer_chars": len(answer.strip()), **triad}


def _compute_triad(question: str, answer: str, chunks: str, ground_truth: str,
                   answer_path: str, should_answer: bool) -> dict[str, float]:
    """Compute RAG triad scores for one question.

    Uses the same heuristics as evaluation/scorers.py but inline so the probe
    script has no import dependency on MLflow.
    """
    def _tokens(text: str) -> set:
        t = re.sub(r"[^\w\s]", " ", (text or "").lower())
        return set(re.sub(r"\s+", " ", t).strip().split())

    def _overlap(a_text: str, b_text: str) -> float:
        a_tok = _tokens(a_text)
        b_tok = _tokens(b_text)
        if not a_tok:
            return 0.0
        return len(a_tok & b_tok) / len(a_tok)

    def _seq_similarity(a: str, b: str) -> float:
        from difflib import SequenceMatcher
        a_n = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (a or "").lower())).strip()
        b_n = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (b or "").lower())).strip()
        if not a_n or not b_n:
            return 0.0
        return SequenceMatcher(None, a_n, b_n).ratio()

    is_deterministic = answer_path in ("system_knowledge", "topology", "off_topic", "")

    # Context Relevance: are the chunks relevant to the question?
    if is_deterministic or not chunks:
        context_relevance = 1.0 if is_deterministic else 0.0
    else:
        context_relevance = _overlap(question, chunks)

    # Groundedness: is the answer supported by the chunks?
    if is_deterministic or not chunks:
        groundedness = 1.0
    else:
        groundedness = _overlap(answer, chunks)

    # Answer Relevance: does the answer address the question?
    if not should_answer:
        # Out-of-scope: a short refusal IS relevant
        answer_relevance = 1.0 if len((answer or "").strip()) < 200 else 0.0
    else:
        answer_relevance = _overlap(question, answer)

    # Answer Correctness: does the answer match the SME ground truth?
    if not ground_truth or ground_truth.upper() == "DECLINE":
        answer_correctness = None  # can't score without ground truth
    else:
        answer_correctness = _seq_similarity(answer, ground_truth)

    return {
        "answer_path": answer_path,
        "context_relevance": round(context_relevance, 3),
        "groundedness": round(groundedness, 3),
        "answer_relevance": round(answer_relevance, 3),
        "answer_correctness": round(answer_correctness, 3) if answer_correctness is not None else None,
    }


def run(api_base: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    results = []
    total = len(rows)
    for i, row in enumerate(rows, 1):
        qid = row.get("id", f"?{i}")
        question = row.get("question", "").strip()
        print(f"[{i}/{total}] {qid} ({row.get('persona')}/{row.get('difficulty')}) {question[:60]}...",
              flush=True)
        resp = ask(api_base, question)
        meta = classify(row, resp)
        print(f"        -> {meta['verdict']}  {resp.get('latency_ms')}ms  "
              f"{meta['answer_chars']} chars", flush=True)
        results.append({**row, **resp, **meta})
    return results


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_verdict: dict[str, int] = {}
    by_persona: dict[str, dict[str, int]] = {}
    for r in results:
        v = r["verdict"]
        by_verdict[v] = by_verdict.get(v, 0) + 1
        p = r.get("persona", "?")
        by_persona.setdefault(p, {})
        by_persona[p][v] = by_persona[p].get(v, 0) + 1

    latencies = [r["latency_ms"] for r in results if r.get("ok")]

    # RAG Triad averages (per path and overall)
    triad_keys = ("context_relevance", "groundedness", "answer_relevance", "answer_correctness")
    triad_overall: dict[str, list[float]] = {k: [] for k in triad_keys}
    triad_by_path: dict[str, dict[str, list[float]]] = {}

    for r in results:
        path = r.get("answer_path") or "unknown"
        triad_by_path.setdefault(path, {k: [] for k in triad_keys})
        for k in triad_keys:
            val = r.get(k)
            if val is not None:
                triad_overall[k].append(val)
                triad_by_path[path][k].append(val)

    def _avg(vals: list[float]) -> float | None:
        return round(sum(vals) / len(vals), 3) if vals else None

    triad_summary = {k: _avg(v) for k, v in triad_overall.items()}
    triad_path_summary = {
        path: {k: _avg(v) for k, v in scores.items()}
        for path, scores in triad_by_path.items()
    }

    return {
        "total": len(results),
        "by_verdict": by_verdict,
        "by_persona": by_persona,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "max_latency_ms": max(latencies) if latencies else 0,
        "triad": triad_summary,
        "triad_by_path": triad_path_summary,
    }


def write_json(results: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "results": results,
    }, indent=2), encoding="utf-8")


def write_markdown(results: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    icon = {"ANSWERED": "✅", "PASS": "✅", "GAP": "🔴", "THIN": "🟡",
            "CLARIFY": "🔵", "FAIL": "❌", "ERROR": "💥"}
    L: list[str] = []
    L.append("# Chatbot Probe — Baseline Response Log")
    L.append("")
    L.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ")
    L.append(f"Questions: **{summary['total']}**  ")
    L.append(f"Avg latency: **{summary['avg_latency_ms']} ms** "
             f"(max {summary['max_latency_ms']} ms)")
    L.append("")
    L.append("## Verdict key")
    L.append("")
    L.append("| Verdict | Meaning |")
    L.append("|---------|---------|")
    L.append("| ✅ ANSWERED | In-scope question got a substantive answer |")
    L.append("| ✅ PASS | Out-of-scope question was correctly declined |")
    L.append("| 🔴 GAP | In-scope but no grounded answer — **RAG gap** |")
    L.append("| 🟡 THIN | Answered but suspiciously short |")
    L.append("| 🔵 CLARIFY | Asked a follow-up instead of answering |")
    L.append("| ❌ FAIL | Out-of-scope question was answered (guardrail miss) |")
    L.append("| 💥 ERROR | Request failed |")
    L.append("")

    L.append("## Summary")
    L.append("")
    L.append("| Verdict | Count |")
    L.append("|---------|-------|")
    for v, n in sorted(summary["by_verdict"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {icon.get(v, '')} {v} | {n} |")
    L.append("")

    L.append("### By persona")
    L.append("")
    verdict_cols = sorted({v for p in summary["by_persona"].values() for v in p})
    L.append("| Persona | " + " | ".join(verdict_cols) + " |")
    L.append("|" + "---|" * (len(verdict_cols) + 1))
    for persona, counts in summary["by_persona"].items():
        cells = [str(counts.get(v, 0)) for v in verdict_cols]
        L.append(f"| {persona} | " + " | ".join(cells) + " |")
    L.append("")

    # The actionable section. Two very different failure classes live in here and
    # they need opposite fixes, so they're reported separately:
    #   - hypothesis starts with "none" => the system ALREADY has this knowledge
    #     (rules engine / Neo4j / an implemented feature) but the chat path can't
    #     reach it. That's a routing problem, not a missing-document problem.
    #   - anything else => a genuine corpus gap that a document would close.
    gaps = [r for r in results if r["verdict"] in ("GAP", "THIN")]
    if gaps:
        routing = [r for r in gaps
                   if (r.get("rag_gap_hypothesis") or "").strip().lower().startswith("none")]
        corpus = [r for r in gaps if r not in routing]

        if routing:
            L.append("## ⚙️ Routing gaps — answer already exists in the system")
            L.append("")
            L.append("These are **not** missing documents. The knowledge is already "
                     "implemented in the rules engine, Neo4j, or a shipped feature, "
                     "but the chat path returns *\"not in the documented procedure\"*. "
                     "Adding PDFs will **not** fix these — the general-response path "
                     "needs to consult these sources.")
            L.append("")
            L.append("| ID | Question | Where the answer actually lives |")
            L.append("|----|----------|--------------------------------|")
            for r in routing:
                src = (r.get("rag_gap_hypothesis") or "").replace("none - ", "").replace("none", "—")
                L.append(f"| `{r['id']}` | {r['question']} | {src} |")
            L.append("")

        if corpus:
            L.append("## 🔴 Corpus gaps — candidate documents to add")
            L.append("")
            by_doc: dict[str, list[dict]] = {}
            for r in corpus:
                doc = (r.get("rag_gap_hypothesis") or "unspecified").strip()
                by_doc.setdefault(doc, []).append(r)
            L.append("| Candidate document | Qs | Questions it would answer |")
            L.append("|--------------------|----|---------------------------|")
            for doc, rs in sorted(by_doc.items(), key=lambda kv: -len(kv[1])):
                ids = ", ".join(f"`{r['id']}`" for r in rs)
                L.append(f"| **{doc}** | {len(rs)} | {ids} |")
            L.append("")

    guardrail_misses = [r for r in results if r["verdict"] == "FAIL"]
    if guardrail_misses:
        L.append("## ❌ Guardrail misses — answered something it should have declined")
        L.append("")
        for r in guardrail_misses:
            L.append(f"- **{r['id']}** — {r['question']}")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Full transcript")
    L.append("")
    current_persona = None
    for r in results:
        if r.get("persona") != current_persona:
            current_persona = r.get("persona")
            L.append(f"### {current_persona}")
            L.append("")
        L.append(f"#### {icon.get(r['verdict'], '')} `{r['id']}` — {r['question']}")
        L.append("")
        L.append(f"- **Verdict:** {r['verdict']} — {r['note']}")
        L.append(f"- **Difficulty:** {r.get('difficulty')} · "
                 f"**Category:** {r.get('category')}")
        L.append(f"- **Expected:** {r.get('expected_behaviour')}")
        if (r.get("rag_gap_hypothesis") or "").strip() not in ("", "none"):
            L.append(f"- **Gap hypothesis:** {r.get('rag_gap_hypothesis')}")
        L.append(f"- **Latency:** {r.get('latency_ms')} ms · "
                 f"**Length:** {r.get('answer_chars')} chars")
        L.append("")
        if r.get("ok"):
            L.append("> " + (r["answer"].strip() or "_(empty response)_").replace("\n", "\n> "))
        else:
            L.append(f"**ERROR:** {r.get('error')}")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", default=DEFAULT_API, help="Backend base URL")
    ap.add_argument("--persona", help="Filter: OPS_PLANNER | FIELD_CREW | GENERAL | OUT_OF_SCOPE")
    ap.add_argument("--difficulty", help="Filter: EASY | MEDIUM | HARD")
    ap.add_argument("--limit", type=int, help="Only run the first N questions")
    args = ap.parse_args()

    rows = load_questions()
    if args.persona:
        rows = [r for r in rows if r.get("persona", "").upper() == args.persona.upper()]
    if args.difficulty:
        rows = [r for r in rows if r.get("difficulty", "").upper() == args.difficulty.upper()]
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        sys.exit("No questions matched the given filters.")

    # Fail fast with a clear message rather than 58 connection errors.
    try:
        with urllib.request.urlopen(f"{args.api.rstrip('/')}/api/v1/health", timeout=15) as r:
            health = json.load(r)
        print(f"Backend health: {health.get('status')}  "
              f"(neo4j={health.get('neo4j')} chromadb={health.get('chromadb')})")
    except Exception as e:
        sys.exit(f"Backend not reachable at {args.api} — start it first.\n  {e}")

    print(f"Probing {len(rows)} questions...\n")
    results = run(args.api, rows)
    summary = summarise(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULTS_DIR / f"probe_{stamp}.json"
    md_path = RESULTS_DIR / f"probe_{stamp}.md"
    write_json(results, summary, json_path)
    write_markdown(results, summary, md_path)

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for v, n in sorted(summary["by_verdict"].items(), key=lambda kv: -kv[1]):
        print(f"  {v:<10} {n}")
    print(f"\n  avg latency  {summary['avg_latency_ms']} ms")
    print(f"  max latency  {summary['max_latency_ms']} ms")

    print(f"\n  RAG TRIAD (overall averages):")
    for k, v in summary.get("triad", {}).items():
        print(f"    {k:<22} {v:.3f}" if v is not None else f"    {k:<22} n/a")

    print(f"\n  RAG TRIAD by answer path:")
    for path, scores in summary.get("triad_by_path", {}).items():
        parts = [f"{k}={v:.2f}" if v is not None else f"{k}=n/a"
                 for k, v in scores.items()]
        print(f"    {path:<20} {' | '.join(parts)}")

    print(f"\nWrote:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
