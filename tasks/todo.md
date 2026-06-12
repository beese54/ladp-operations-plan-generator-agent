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
