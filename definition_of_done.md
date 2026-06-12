# Definition of Done

Each task is only marked **Completed** when ALL criteria for that task pass.

---

## Phase 0 — Scaffold

### Task 0.1 — Directory Structure
- [ ] All directories in the approved file structure exist on disk
- [ ] `tasks/todo.md` and `tasks/lessons.md` are present

### Task 0.2 — requirements.txt
- [ ] File exists at project root
- [ ] All packages pinned to specific versions
- [ ] `pip install -r requirements.txt` completes without error on a clean venv

### Task 0.3 — .env.example
- [ ] All required env vars documented with placeholder values
- [ ] Includes: `ANTHROPIC_API_KEY`, `TOGETHER_API_KEY`, `TOGETHER_MODEL`, `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `CHROMA_PERSIST_DIR`, `SQLITE_DB_PATH`, `FASTAPI_HOST`, `FASTAPI_PORT`, `LOG_LEVEL`

### Task 0.4 — config/settings.py
- [ ] Loads all env vars from `.env` via pydantic-settings `BaseSettings`
- [ ] Implements `get_settings()` singleton (cached with `@lru_cache`)
- [ ] `get_llm_client(agent_name)` factory returns correct client (Anthropic or OpenAI-compat Together.ai) based on `AGENT_PROVIDERS` mapping
- [ ] `python -c "from config.settings import get_settings; get_settings()"` runs without error given a valid `.env`

---

## Phase 1 — DB Clients

### Task 1.1 — db/sqlite_client.py
- [ ] `get_sqlite_connection()` returns `sqlite3.Connection` with WAL mode and FK enforcement enabled
- [ ] `bootstrap_sqlite_schema()` creates all 4 tables idempotently (`IF NOT EXISTS`)
- [ ] Context manager usage (`with get_sqlite_connection() as conn`) works
- [ ] Unit test: bootstrap twice on in-memory DB does not raise

### Task 1.2 — db/chroma_client.py
- [ ] `get_chroma_client()` returns `chromadb.PersistentClient` pointed at `CHROMA_PERSIST_DIR`
- [ ] `get_or_create_collection(name)` returns collection with `SentenceTransformerEmbeddingFunction(all-MiniLM-L6-v2)`
- [ ] Calling `get_or_create_collection` twice returns the same collection (idempotent)
- [ ] Unit test: collection created, 1 document added, query returns 1 result

### Task 1.3 — db/neo4j_client.py
- [ ] `get_neo4j_driver()` returns singleton `GraphDatabase.driver` using `neo4j+s://` URI
- [ ] `verify_connectivity()` executes `RETURN 1` and returns `True`
- [ ] `execute_read(query, params)` and `execute_write(query, params)` handle session lifecycle
- [ ] `close_driver()` closes the driver cleanly
- [ ] Integration test (live Aura): `verify_connectivity()` returns `True` with valid credentials

---

## Phase 2 — Schemas

### Task 2.1 — schemas/graph_state.py
- [ ] `OrchestratorState` TypedDict defines all fields listed in the plan
- [ ] All nested TypedDicts defined: `CalendarContext`, `TopologyContext`, `SOPContext`, `HistoricalContext`, `OperationsPlan`, `OpsValveAction`
- [ ] `python -c "from schemas.graph_state import OrchestratorState"` imports cleanly
- [ ] `OperationsPlan` includes `valve_sequence: List[OpsValveAction]`

### Task 2.2 — schemas/neo4j_models.py
- [ ] Dataclasses: `ValveNode`, `PipeRelationship`, `JunctionNode`, `TankNode`
- [ ] Each has `from_neo4j_record(record)` classmethod that builds the dataclass from a Neo4j result record
- [ ] `PipeRelationship` has `has_customer: bool` and `Number_of_customers: int`

### Task 2.3 — schemas/calendar_models.py
- [ ] Pydantic v2 models: `ScheduledOperation`, `SchedulingConflict`, `AffectedConsumer`
- [ ] `ScheduledOperation` has `scheduled_start: datetime`, `scheduled_end: datetime`, `status` with literal type

### Task 2.4 — schemas/api_models.py
- [ ] `ChatRequest` with `session_id`, `message`, `stream: bool = False`
- [ ] `ChatResponse` with `session_id`, `message`, `feasibility`, `pipe_id`, `target_date`, `has_plan`, `operations_plan`, `processing_time_ms`
- [ ] `CreateScheduleRequest`, `CreateScheduleResponse`, `HealthResponse` defined

---

## Phase 3 — Tools

### Task 3.1 — tools/neo4j_tools.py
- [ ] 8 functions implemented (including partner pipe fetch and status update)
- [ ] Each function catches `ServiceUnavailable` and returns empty result + logs error
- [ ] All queries use parameterised Cypher (no string interpolation)
- [ ] Unit tests: each function tested with mocked `Session.run()` return values

### Task 3.2 — tools/chroma_tools.py
- [ ] `search_sop_documents(query, n_results, filter_tags)` queries `sop_documents` collection
- [ ] `search_historical_plans(query, n_results, filter_metadata)` queries `historical_plans` collection
- [ ] Both return `List[dict]` with `text`, `metadata`, `similarity_score` (0.0–1.0)
- [ ] Distance-to-similarity conversion verified: lower ChromaDB distance → higher similarity score
- [ ] Unit tests with mocked ChromaDB collections

### Task 3.3 — tools/calendar_tools.py
- [ ] `check_pipe_schedule_conflicts(pipe_id, start, end)` returns list of conflicts
- [ ] `check_zone_saturation(zone_id, start, end)` returns integer count (unused field left for future)
- [ ] `get_upcoming_operations(pipe_id, zone_id, days_ahead)` returns sorted list
- [ ] `create_scheduled_operation(...)` inserts and returns `operation_id`
- [ ] `cancel_operation(operation_id)` sets status to CANCELLED
- [ ] Unit tests with sqlite3 in-memory DB; overlapping record detected as conflict

---

## Phase 4 — Ingestion + Seed

### Task 4.1 — ingestion/ingest_sop.py
- [ ] Reads all `.txt` and `.pdf` files from `data/seed/sop_documents/`
- [ ] Chunks with `RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)`
- [ ] Upserts to `sop_documents` ChromaDB collection (idempotent — duplicate IDs skipped)
- [ ] Prints summary: files processed, chunks inserted
- [ ] Running twice does not create duplicates

### Task 4.2 — ingestion/ingest_historical.py
- [ ] Same as 4.1 but targets `historical_plans` collection and `data/seed/historical_plans/`
- [ ] Parses `plan_id`, `pipe_id`, `execution_date`, `outcome` from document filename or header

### Task 4.3 — data/seed/neo4j_seed.cypher
- [ ] Begins with `CALL db.schema.visualization()` commented reference note
- [ ] Uses `MERGE` not `CREATE` to avoid duplicates on re-run
- [ ] Augments existing Aura data only — does not delete any existing nodes or relationships
- [ ] Includes at least 2 Tank nodes, 5 Valve nodes, 6 PIPE relationships (3 bidirectional pairs)

### Task 4.4 — scripts/bootstrap_db.py
- [ ] CLI flags: `--skip-neo4j`, `--skip-sop`, `--skip-history`, `--skip-sqlite`
- [ ] Each step reports success/failure
- [ ] Exits with code 1 if any non-skipped step fails

---

## Phase 5 — Agents

### Task 5.1 — agents/calendar_agent.py
- [ ] `calendar_agent_node(state)` reads `pipe_id`, `scheduled_start`, `scheduled_end` from state
- [ ] Calls `check_pipe_schedule_conflicts` and returns `CalendarContext`
- [ ] `blocking_conflict: True` when any conflict has `severity == "BLOCKING"`
- [ ] Integration test: pre-inserted conflict detected correctly

### Task 5.2 — agents/neo4j_agent.py
- [ ] `neo4j_agent_node(state)` fetches pipe, both endpoint valves, and partner pipe
- [ ] Computes `downstream_customer_count` by summing `Number_of_customers` on reachable pipes
- [ ] If pipe not found in Aura: appends to `error_messages`, returns empty `TopologyContext`
- [ ] Integration test against live Aura with seeded data

### Task 5.3 — agents/sop_agent.py
- [ ] `sop_agent_node(state)` builds query from `topology_context` fields (diameter, material, valve types)
- [ ] Calls `search_sop_documents` with `n_results=5`
- [ ] Summarises retrieved chunks into `relevant_principles` list via Together.ai call
- [ ] System prompt cached (`cache_control: ephemeral`)
- [ ] Returns `SOPContext` with both raw chunks and summarised principles

### Task 5.4 — agents/historical_agent.py
- [ ] `historical_agent_node(state)` queries `historical_plans` ChromaDB with `n_results=3`
- [ ] Returns `HistoricalContext` with retrieved chunks formatted as `similar_plans`
- [ ] Integration test: seeded plan retrieved when matching pipe type queried

### Task 5.5 — agents/ops_plan_generator.py
- [ ] `ops_plan_generator_node(state)` assembles all 4 contexts into prompt
- [ ] Claude system prompt + SOP block both have `cache_control: ephemeral`
- [ ] Returns structured `OperationsPlan` JSON parsed into TypedDict
- [ ] Retry logic: if JSON parse fails, retries once with explicit format reminder
- [ ] `feasibility_verdict` in `["FEASIBLE", "NOT_FEASIBLE", "CONDITIONAL"]`
- [ ] `valve_sequence` is non-empty list of `OpsValveAction` for shutdown requests

### Task 5.6 — agents/orchestrator.py
- [ ] LangGraph `StateGraph` compiles without error
- [ ] `intent_parser_node`: correctly classifies GENERAL_QUERY vs OPS_QUERY; extracts pipe_id and target_date
- [ ] `general_response_node`: answers general water network questions; refuses off-topic requests
- [ ] `clarification_node`: uses `interrupt()` to ask for missing pipe_id or date; resumes on next message
- [ ] `time_clarification_node`: uses `interrupt()` to ask for start/end time when only date provided
- [ ] `orchestrator_response_node`: formats `OperationsPlan` into Markdown with feasibility badge
- [ ] `error_handler_node`: returns user-friendly message with what information to re-provide
- [ ] E2E test (MOCK_MODE): `agents_completed` contains `["calendar", "neo4j", "sop", "historical", "ops_plan_generator"]`

---

## Phase 6 — API

### Task 6.1 — api/routes/health.py
- [ ] `GET /api/v1/health` returns 200 with status for each service
- [ ] Returns 503 if any critical service (Neo4j, Anthropic) is unreachable
- [ ] Integration test with `httpx.AsyncClient`

### Task 6.2 — api/routes/chat.py
- [ ] `POST /api/v1/chat` accepts `ChatRequest`, returns `ChatResponse`
- [ ] `session_id` persists across calls for multi-turn conversation
- [ ] `processing_time_ms` accurately reflects end-to-end latency
- [ ] Returns `has_plan: true` and populated `operations_plan` for completed shutdown queries

### Task 6.3 — api/routes/schedule.py
- [ ] GET lists operations filtered by `pipe_id` and/or `days_ahead`
- [ ] POST creates operation and returns `conflicts` list before committing
- [ ] DELETE sets status CANCELLED (does not hard-delete)

### Task 6.4 — api/middleware.py
- [ ] CORS allows all origins (dev mode; lockdown for production)
- [ ] Every request gets a unique `X-Request-ID` header in response
- [ ] Unhandled exceptions return `{"error": "...", "request_id": "..."}` JSON, not HTML stack traces

### Task 6.5 — api/main.py
- [ ] `create_app()` factory with `lifespan` context manager
- [ ] On startup: verifies Neo4j connectivity; if down, logs error but does not crash (degraded mode)
- [ ] On startup: pre-warms ChromaDB collections
- [ ] `uvicorn api.main:app --reload` starts without error
- [ ] `GET /api/v1/health` returns `{"status": "OK"}` when all services reachable

---

## Phase 7 — UI

### Task 7.1 — ui/streamlit_app.py
- [ ] `session_id` stored in `st.session_state` and persists across interactions
- [ ] Chat history renders with `st.chat_message` (user and assistant bubbles)
- [ ] Feasibility verdict shown as coloured badge (green=FEASIBLE, yellow=CONDITIONAL, red=NOT_FEASIBLE)
- [ ] Valve sequence rendered as numbered step list
- [ ] Safety warnings shown in `st.warning` callout boxes
- [ ] Affected consumers summary shown in `st.info` box
- [ ] `streamlit run ui/streamlit_app.py` starts without error and chatbot is usable

---

## Phase 8 — Tests

### Task 8.1–8.4 — Unit Tests
- [ ] All unit tests pass: `pytest tests/unit/ -v`
- [ ] No live service calls in unit tests (all mocked)
- [ ] Coverage ≥ 80% on tools layer (`tools/`)

### Task 8.5–8.6 — Integration Tests
- [ ] Integration tests pass against live Aura instance with seeded data: `pytest tests/integration/ -v`
- [ ] Calendar integration test uses in-memory SQLite (no file created)

### Task 8.7 — E2E Test
- [ ] MOCK_MODE: `pytest tests/e2e/ -v` passes without live services
- [ ] LIVE_MODE: `LIVE_MODE=1 pytest tests/e2e/ -v` produces a valid operations plan for test pipe

---

## Phase 9 — Verification Script

### Task 9.1 — scripts/verify_connections.py
- [ ] Tests all 4 services: Neo4j, ChromaDB, SQLite, Anthropic API
- [ ] Prints PASS/FAIL per service with error details on FAIL
- [ ] Exits with code 0 if all pass, code 1 if any fail
- [ ] `python scripts/verify_connections.py` completes in under 10 seconds

---

## System-Level Done Criteria

The system is **complete** when:

1. A user can type "Can I shut down pipe P-151 on 2026-06-01 from 08:00 to 16:00?" into the Streamlit UI and receive:
   - A feasibility verdict (FEASIBLE / NOT_FEASIBLE / CONDITIONAL)
   - A numbered valve sequence with `close V-xxx` steps, timing notes, and safety checks
   - Affected customer count pulled live from Neo4j Aura
   - Any schedule conflicts surfaced from the calendar

2. A user can type "What is pipe P-151 made of?" and receive a direct answer (general response path — no ops plan generated).

3. A user who provides only a date (no time) is asked "What start and end time do you require?" before the plan proceeds.

4. All 9 phases of unit, integration, and E2E tests pass.

5. `scripts/verify_connections.py` exits with code 0.
