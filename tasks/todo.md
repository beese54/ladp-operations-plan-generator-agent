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
