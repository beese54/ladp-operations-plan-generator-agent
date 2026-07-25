# Tasks

## Phase 1 Deliverables
- [x] specification.json
- [x] definition_of_done.md
- [x] progress_tracking.json
- [x] init.sh

## Phase 0 — Scaffold
- [x] 0.1 Directory structure
- [x] 0.2 requirements.txt
- [x] 0.3 .env.example
- [x] 0.4 config/settings.py

## Phase 1 — DB Clients
- [x] 1.1 db/sqlite_client.py
- [x] 1.2 db/chroma_client.py
- [x] 1.3 db/neo4j_client.py

## Phase 2 — Schemas
- [x] 2.1 schemas/graph_state.py
- [x] 2.2 schemas/neo4j_models.py
- [x] 2.3 schemas/calendar_models.py
- [x] 2.4 schemas/api_models.py

## Phase 3 — Tools
- [x] 3.1 tools/neo4j_tools.py
- [x] 3.2 tools/chroma_tools.py
- [x] 3.3 tools/calendar_tools.py

## Phase 4 — Seed Data + Ingestion
- [x] 4.1 ingestion/ingest_sop.py
- [x] 4.2 ingestion/ingest_historical.py
- [x] 4.3 data/seed/neo4j_seed.cypher
- [x] 4.4 scripts/bootstrap_db.py

## Phase 5 — Agents
- [x] 5.1 agents/calendar_agent.py
- [x] 5.2 agents/neo4j_agent.py
- [x] 5.3 agents/sop_agent.py
- [x] 5.4 agents/historical_agent.py
- [x] 5.5 agents/ops_plan_generator.py
- [x] 5.6 agents/orchestrator.py

## Phase 6 — API
- [x] 6.1 api/routes/health.py
- [x] 6.2 api/routes/chat.py
- [x] 6.3 api/routes/schedule.py
- [x] 6.4 api/middleware.py
- [x] 6.5 api/main.py

## Phase 7 — UI
- [x] 7.1 ui/streamlit_app.py

## Phase 8 — Tests
- [ ] 8.1 Unit: neo4j_tools
- [ ] 8.2 Unit: chroma_tools
- [ ] 8.3 Unit: calendar_tools
- [ ] 8.4 Unit: graph_state
- [ ] 8.5 Integration: neo4j_agent
- [ ] 8.6 Integration: calendar_agent
- [ ] 8.7 E2E: full_workflow

## Phase 9 — Verification
- [x] 9.1 scripts/verify_connections.py

## Phase 10 — pipe_084 SOP: deterministic chain wiring (2026-06-15)
- [x] 10.1 Fix ingest_sop.py re-sync bug (skip-if-exists → delete+insert per doc)
- [x] 10.2 Re-ingest SOP docs; verify ChromaDB matches docx (0 mismatches)
- [x] 10.3 Diagnose: main chat path emits CONDITIONAL, no affected valves / re-feed
- [x] 10.4 Wire build_sop_chain_data into ops_plan_generator (ground-truth chain block)
- [x] 10.5 Update _SYSTEM_PROMPT to consume deterministic chain
- [x] 10.6 Verify invoke_graph(pipe_084) emits affected valves (035,036) + re-feed pairs

### Review (2026-06-15)
- ingest_sop.py: skip-if-exists → per-doc delete+upsert (true re-sync); ChromaDB now
  matches docx exactly (0 mismatches, 16 chunks).
- ops_plan_generator.py: builds deterministic SOP chain via build_sop_chain_data,
  renders a GROUND TRUTH block (tail valve, alt feed, affected valves, re-feed
  open/close pairs); _SYSTEM_PROMPT instructs the model to consume it. Graceful
  fallback to topology-only if the chain can't be built.
- Result: pipe_084 plan now FEASIBLE with affected valves (035,036) and the full
  reverse re-feed sequence — even when SOP RAG retrieval fails.
- Pre-existing, out-of-scope: historical_agent RustBindingsAPI bug; SOP RAG
  relative-path error outside server context.

## Phase 11 — Lead chat output with SOP logic + auto-trace graph (2026-06-15)
Decisions (approved): output = SOP logic first, keep all sections; graph = auto-trace.
- [x] 11.1 schemas/graph_state.py — add `sop_chain: Optional[dict[str, Any]]` to OrchestratorState
- [x] 11.2 prompts/sop_walkthrough_prompt.py — deterministic `format_sop_walkthrough(chain)` (SOP-doc numbering: 1-8 trace, 9 alt feed, 10 chain, 11 affected valves, 12 re-feed)
- [x] 11.3 agents/ops_plan_generator.py — return `"sop_chain": chain` in success path
- [x] 11.4 agents/orchestrator.py — orchestrator_response_node prepends walkthrough, keeps all sections
- [x] 11.5 frontend/src/App.jsx — runTrace accepts explicit id; pass onPipeResolved to ChatPanel
- [x] 11.6 frontend/src/components/ChatPanel.jsx — call onPipeResolved(data.pipe_id) after reply

### Verification
- [x] Backend: POST /chat pipe_084 (full window) → SOP walkthrough leads (Steps 1-12), all sections follow; FEASIBLE
- [x] Trace endpoint /api/v1/trace/pipe_084 → 200, chain {pipe_084,086,088 / valves 034-037 / tail 037}
- [x] Vite HMR recompiled App.jsx + ChatPanel.jsx cleanly (no errors); proxy /api → 8001
- [~] UI visual screenshot — not captured (no browser automation installed); both wiring ends + endpoint verified by data path

### Review
- Deterministic renderer format_sop_walkthrough() (no LLM) guarantees the SOP logic always
  matches the docx exactly; carried generator→response via new state field sop_chain.
- Chat now leads with the full SOP sequential walkthrough, then keeps all plan sections below.
- Chat→graph: ChatPanel.onPipeResolved(data.pipe_id) → App.runTrace(id) → same path as the
  manual Trace button; graph auto-highlights the shutdown chain on any pipe-resolving query.

## Phase 12 — Scope guardrails for general_response (stop capability hallucination) (2026-07-25)
User testing found the chat assistant inventing capabilities that don't exist anywhere in
the codebase (photo/screenshot SOP upload, pump/tank coordination, work orders, troubleshooting)
when asked general/off-topic questions ("how do i start?", "understand an SOP"). Root cause:
general_response_node used one open-ended "answer helpfully using your knowledge" LLM prompt
for both UNKNOWN and GENERAL_QUERY intents, with no code-level constraint on claimed capabilities.
- [x] 12.1 agents/orchestrator.py — off_topic_node: deterministic decline for UNKNOWN, no LLM call
- [x] 12.2 agents/orchestrator.py — route_after_intent split (UNKNOWN → off_topic, GENERAL_QUERY → general_response)
- [x] 12.3 agents/orchestrator.py — _GENERAL_SYSTEM rewritten as closed 3-capability list + explicit ban list
- [x] 12.4 agents/orchestrator.py — _BANNED_CAPABILITY_RE + negation-aware _claims_banned_capability() output filter in general_response_node (harness backstop)
- [x] 12.5 data/eval_datasets/general_query_cases.csv — banned_phrases column + 3 regression rows
- [x] 12.6 evaluation/scorers.py — scope_fidelity_scorer, wired into get_available_scorers()
- [x] 12.7 tasks/guardrails_design.md — misuse model (Pattern AS Phase 0)

### Verification
- [x] Syntax-checked agents/orchestrator.py and evaluation/scorers.py (ast.parse)
- [x] scope_fidelity_scorer row-scoring logic unit-tested in isolation — correct 0.0/1.0 per banned_phrases
- [x] _claims_banned_capability() unit-tested against 8 realistic phrasings incl. curly-apostrophe
  contractions ("I can't/can't read uploaded documents") — caught a real false-positive bug where
  the LLM's typographic apostrophe (’, U+2019) wasn't recognized by the negation regex, fixed
- [x] Live re-test via invoke_graph() of all 4 original transcript turns against the fixed graph —
  capital-of-france: correct verbatim decline; how-do-i-start / understand-an-SOP: only mention
  the 3 real capabilities, no photo/upload/pump/tank/work-order/troubleshoot leakage; plan-a-valve-
  shutdown: unaffected, still triggers the pipe-ID clarification interrupt as before
  - Also confirmed the SOP answer ("I can't read uploaded documents...") is preserved verbatim now
    instead of being wrongly overwritten by the negation-unaware filter's first version
- [~] `PYTHONPATH=. python -m evaluation.run_eval --dataset general_query` — blocked by a
  PRE-EXISTING, unrelated bug: mlflow.metrics.make_metric() in the installed mlflow version
  requires eval_fn as a kwarg, so ALL rule-based scorers (including the 3 that predate this
  change) silently resolve to None via the file's blanket `except Exception`. Confirmed via
  `git stash` that get_available_scorers() returns [] on unmodified main too — not a regression
  introduced here, but a standing gap in the eval harness worth fixing separately.
- [x] `PYTHONPATH=. pytest tests/ -v` — 146 passed, 0 failed, 1 pre-existing unrelated warning

### Review
- Containment lives in the harness, not just the prompt: UNKNOWN now short-circuits to a fixed
  string with zero LLM involvement (cheaper and non-driftable); GENERAL_QUERY still calls the
  LLM but under a closed capability list; the LLM's own output is additionally regex-checked
  before it reaches the user, so a prompt-compliance failure alone can't leak a hallucinated
  capability claim.
- Deliberately out of scope (per user decision): wiring genuine "explain this SOP" questions to
  live ChromaDB retrieval for a grounded answer — a legitimate follow-up feature, not a guardrail.

## Phase 13 — Ground general SOP answers in the real corpus (2026-07-25)
The Phase 12 gap above turned out to be a real, confirmed bug within the same session: asked
"what is the SOP guidance", the assistant returned a generic industry checklist (lockout/tagout,
permits, confined space, traffic control) that appears in NONE of the 4 real files ingested into
ChromaDB (data/seed/sop_documents/ — verified by reading the actual .docx/.md content). Root
cause: _GENERAL_SYSTEM capability #3 said "using established domain knowledge," which let the
model free-generate SOP content instead of retrieving it. A second, separate bug compounded the
confusion: invoke_graph's early _is_steps_request short-circuit (line ~1031) intercepted "show me
the SOP guidance" (verb "show" matches _STEPS_REQUEST_VERBS) but NOT "what is the SOP guidance"
(no "what is" in the verb list), so two near-identical questions hit two different code paths.
- [x] 13.1 agents/orchestrator.py — _is_steps_request guard now only short-circuits when a
  sop_chain is actually stored; no chain → falls through to the real graph instead of guessing
  "ask me about a pipe shutdown first"
- [x] 13.2 agents/orchestrator.py — _sop_grounded_answer(): retrieves via search_sop_documents
  (same tool sop_agent uses), synthesizes strictly from retrieved excerpts via new
  _SOP_GROUNDED_SYSTEM prompt, deterministic fallback when nothing is retrieved
- [x] 13.3 agents/orchestrator.py — _answer_is_grounded() post-check: flags generic safety
  boilerplate (lockout/tagout/permit/confined space/ppe/traffic control) present in the answer
  but absent from the retrieved chunk text, swaps in the honest fallback (harness backstop,
  same pattern as Phase 12's _claims_banned_capability — a similarity-score threshold alone
  doesn't work here, see Design note below)
- [x] 13.4 agents/orchestrator.py — general_response_node now DEFAULTS to grounded retrieval;
  only a small _META_HELP_PATTERNS deny-list ("how do i start", "what can you do", ...) still
  uses the _GENERAL_SYSTEM capability-list LLM path
- [x] 13.5 data/eval_datasets/general_query_cases.csv — 2 new rows: in-corpus positive case
  (alternate feed) + lockout/tagout regression case (banned_phrases)
- [x] 13.6 tasks/guardrails_design.md — addendum: content-grounding hallucination as a second
  misuse-model category

### Design note — allow-list tried first, replaced with default-to-grounded
The original plan used an _SOP_CONTENT_KEYWORDS allow-list ("sop", "procedure", "isolation", ...)
to decide when to ground vs. use the capability-list prompt. Live verification caught this missing
a real in-corpus question — "what happens if there's no alternate feed available?" contains none
of those keywords, so it fell through to the ungrounded capability-list path instead of being
answered from the real corpus. Fixed by inverting the design: general_response_node now grounds
by default, and only a small, explicit meta-help deny-list opts OUT into the capability-list
prompt. This also incidentally fixes questions like "how many customers does pipe_033 affect?"
(existing golden eval row) — previously capability #3's "using your knowledge" could have
fabricated a customer count; now it honestly says the documented excerpts don't cover that.

### Verification
- [x] Syntax-checked agents/orchestrator.py after each edit (ast.parse)
- [x] invoke_graph() re-test: "show me the SOP guidance" / "what is the SOP guidance" / "show me
  the general water network operations SOP" — all three now converge on real, grounded content
  (previously two different code paths gave two different answers)
- [x] "what happens if there's no alternate feed available?" — grounded in
  no_alternate_feed_available_SOP.docx content (residents/valves/road-names), not the earlier
  ungrounded capability-menu deflection
- [x] "what is the lockout tagout procedure for a pipe shutdown?" — honest fallback ("I don't have
  general SOP guidance stored beyond the pipe-isolation procedure..."), no fabricated checklist;
  _answer_is_grounded() post-check fired and replaced the model's first (fabricated) attempt
- [x] "How many customers does pipe_033 affect?" (existing eval row) — now honestly says the
  documented excerpts don't cover customer counts, instead of a risk of a fabricated number
- [x] Phase 12 regression set re-confirmed: capital-of-france (off_topic_node, direct decline),
  "understand an SOP" (no photo/upload claim), "Tell me a joke", "plan a valve shutdown"
  (clarification interrupt unaffected) — all safe; noted a pre-existing, unrelated classifier
  nondeterminism (capital-of-france sometimes lands as GENERAL_QUERY not UNKNOWN) now surfaces
  the grounded "not addressed by the documented procedure" wording instead of the off-topic
  decline in that case — still safe/honest, just a minor wording inconsistency, not fixed here
  (out of scope: it's an intent-classifier consistency issue, not a hallucination)
- [x] `PYTHONPATH=. pytest tests/ -v` — 146 passed, 0 failed
- [x] Live backend (`curl localhost:8001/api/v1/chat`) re-tested with "what is the SOP guidance"
  — confirmed real ingested content, matches invoke_graph() test

### Review
- Two misuse-model categories now distinguished (see tasks/guardrails_design.md): Phase 12 =
  capability-existence hallucination (claiming features that don't exist), Phase 13 =
  content-grounding hallucination (true-sounding but unsourced claims). Different failure modes
  need different controls — a deny-list catches the former, retrieval-grounding + vocabulary
  cross-check catches the latter.
- Known minor gap (not a hallucination risk, just UX): intent-classifier nondeterminism between
  UNKNOWN/GENERAL_QUERY for clearly off-topic messages means the wording of the safe decline
  varies by run. Both wordings are honest and non-fabricating. Worth a separate look if it
  becomes user-visible confusion, not urgent.
