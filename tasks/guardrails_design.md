# Guardrails Design — `general_response_node` scope containment

Pattern AS (AI Guardrails & Safety Layer) misuse model for the fix landed
2026-07-25. Scope: contain the chat assistant's off-topic/general-query path
to the system's real, implemented capabilities. See `tasks/todo.md` Phase 12
for the task checklist and `agents/orchestrator.py` for the implementation.

## Phase 0 — Misuse Model

**Bad outputs that must never reach a user:**
- Claims of capabilities that don't exist anywhere in this codebase —
  observed cases: accepting a photo/screenshot/scanned document of an SOP
  (the system has no image/vision path — both LLM clients are called with
  text-only `chat.completions.create`), "coordinating a pump or tank
  operation" as a distinct service, "preparing a work order or switching
  plan," "troubleshooting" as a standalone diagnostic service. None of
  these correspond to a real agent, tool, or graph node.
- An off-topic decline that isn't guaranteed verbatim — before this fix,
  the exact refusal sentence was only ever produced if the LLM chose to
  follow the prompt; nothing in the harness enforced it.
- Fabricated real-time data (live pressure/valve status) presented as fact
  instead of a "query the network directly" deflection — the general-chat
  path has no live data access.

**Bad inputs that must be contained:**
- Off-topic requests unrelated to water network operations (e.g. "what is
  the capital of France").
- Ambiguous/meta requests that don't map to a specific operation (e.g. "how
  do I start?") — these previously got the most latitude, because the LLM
  treated them as an invitation to be maximally helpful and improvised a
  menu of invented options.
- In-scope-sounding requests for functionality the system doesn't have
  (e.g. "understand an SOP" via document upload) — the classifier correctly
  routes these to the general/help path, but the path itself had no
  boundary on what it could offer to do.

**Adversary:** Not a malicious actor. This is a trusted, authenticated
water-utility operator using the tool in good faith. The risk is **misplaced
trust in a false capability claim** in a safety-adjacent infrastructure
domain — an operator who believes the system will "prepare a work order" or
"coordinate a pump operation" and acts on that belief is a worse outcome
than the system simply saying "I can't do that."

**Assets at risk:** User trust in the system's stated capabilities, and by
extension in this being a domain-appropriate tool for safety-relevant
decisions (pipe isolation planning). A chatbot that improvises features
erodes confidence in the parts that actually are grounded (Neo4j topology,
SOP retrieval, calendar checks feeding the real ops-plan pipeline).

## Controls implemented (harness, not just prompt)

| Layer | Control | Where |
|---|---|---|
| Routing | `UNKNOWN` intent short-circuits to a fixed decline string — zero LLM calls, zero drift | `route_after_intent`, `off_topic_node` |
| Input/prompt | `GENERAL_QUERY` LLM call constrained to a closed, enumerated 3-capability list with an explicit ban list | `_GENERAL_SYSTEM` |
| Output | Regex deny-list checked against the LLM's answer before it's returned; swapped for a safe redirect on a hit | `_BANNED_CAPABILITY_RE` in `general_response_node` |
| Verification | Red-team regression rows (the exact 3 failing turns from this session) + `scope_fidelity_scorer` in the golden eval set | `data/eval_datasets/general_query_cases.csv`, `evaluation/scorers.py` |

## Explicitly out of scope (by user decision)

Wiring genuine "explain/understand this SOP" questions to real ChromaDB
retrieval (`tools/chroma_tools.search_sop_documents`) so the assistant gives
a grounded answer instead of a redirect. This is a legitimate feature —
directly analogous to why `schedule_query_node` was pulled out of
`general_response` — but it's a capability expansion, not a guardrail, and
was intentionally deferred.

## Addendum (2026-07-25) — Phase 13: content-grounding hallucination

The "deliberately out of scope" item above turned out to be load-bearing
within the same session: the general-knowledge fallback that Phase 12 left
in place for SOP/safety questions (capability #3, "using established
domain knowledge") produced a **second, distinct misuse category**.

**Capability-existence hallucination (Phase 12):** the model claims a
*feature* that doesn't exist — "I can accept a photo," "I can prepare a
work order." Contained by an enumerated capability list, a deny-list output
filter, and (for fully off-topic messages) a deterministic no-LLM path.

**Content-grounding hallucination (Phase 13):** the model answers a
legitimate, in-scope question with **true-sounding but unsourced content**
— asked "what is the SOP guidance," it produced a generic
lockout/tagout/permit/confined-space checklist. Every one of those terms
is plausible for a water utility in general, which is exactly what makes
this failure mode more dangerous than Phase 12's: nothing about the answer
looks wrong on its face. Verified by reading the actual 4 files ingested
into ChromaDB (`data/seed/sop_documents/`) — none of them mention any of
it. This is the same misuse-model risk already named in Phase 0 above
("misplaced trust in a false capability claim... in a safety-adjacent
infrastructure domain"), just manifesting as false *content* instead of a
false *capability*.

**Why a deny-list doesn't generalize here:** Phase 12's fix works because
the set of fabricatable features is small and enumerable in advance. The
set of fabricatable *content* is not — any plausible-sounding safety fact
could be invented. The control instead has to be architectural: answer
only from retrieved source text (RAG), and verify after the fact that the
answer's vocabulary traces back to what was actually retrieved
(`_answer_is_grounded` in `agents/orchestrator.py`) rather than trying to
enumerate every possible fabrication in advance.

**Why a similarity-score threshold doesn't work for this corpus:**
empirically tested before implementing — a genuinely off-corpus query
("lockout tagout procedure") scored 0.64-0.65 against the real SOP
documents, barely below genuinely relevant queries at 0.70-0.78. The
4-document corpus is too narrow and topically homogeneous (everything is
"SOP-flavored") for retrieval distance alone to signal semantic
answerability. The grounding check instead compares the *synthesized
answer's* vocabulary against the *retrieved chunk text* — a term appearing
in the answer but nowhere in the source is evidence of fabrication
regardless of how confident the retrieval scored.

**Design correction during implementation:** the first version gated
grounded retrieval behind an `_SOP_CONTENT_KEYWORDS` allow-list ("sop",
"procedure", "isolation", ...). Live testing caught this missing a real
in-corpus question — "what happens if there's no alternate feed
available?" uses none of those words. Fixed by inverting the default:
`general_response_node` now grounds every question by default, and only a
small, explicit `_META_HELP_PATTERNS` deny-list ("how do I start", "what
can you do") opts OUT to the capability-list prompt. Lesson: an allow-list
for when to apply a safety control is itself a source of gaps — default to
the safe behavior and allow-list the exceptions, not the other way round.

## Known gap surfaced during this work (pre-existing, unrelated)

`evaluation/scorers.py`'s rule-based scorers (including the two that predate
this change) currently fail to initialize: the installed mlflow version's
`mlflow.metrics.make_metric()` requires `eval_fn` as an explicit keyword
argument, which the file's decorator-style usage doesn't provide, so the
blanket `except Exception` silently sets all four rule-based scorers
(`feasibility_match_scorer`, `valve_count_scorer`, `intent_accuracy_scorer`,
`scope_fidelity_scorer`) to `None`. Confirmed via `git stash` that this
reproduces on unmodified `main` — not a regression from this change. The
`scope_fidelity_scorer` row-scoring logic itself was verified correct via a
standalone unit test (see Phase 12 verification notes in `tasks/todo.md`).
Fixing the mlflow compatibility issue is a separate task.
