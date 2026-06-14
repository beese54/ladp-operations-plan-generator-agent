# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start the full app (FastAPI + React graph UI) — preferred startup
# Run each in a separate terminal, or use start.ps1 (Windows) / start.sh (bash)
PYTHONPATH=. uvicorn api.main:app --reload --host 0.0.0.0 --port 8001   # terminal 1
cd frontend && npm run dev                                                 # terminal 2 → http://localhost:5174

# Run FastAPI server only (always set PYTHONPATH=.)
PYTHONPATH=. uvicorn api.main:app --reload --host 0.0.0.0 --port 8001

# Run React graph UI (Cytoscape network diagram + chat panel)
cd frontend && npm run dev   # → http://localhost:5174

# Run Streamlit UI (chat-only, no graph)
streamlit run ui/streamlit_app.py

# Ingest SOP documents (drop files into data/seed/sop_documents/ first)
PYTHONPATH=. python ingestion/ingest_sop.py

# Ingest historical plans (drop files into data/seed/historical_plans/ first)
PYTHONPATH=. python ingestion/ingest_historical.py

# Bootstrap databases (SQLite schema + ChromaDB pre-warm)
PYTHONPATH=. python scripts/bootstrap_db.py

# Verify all external connections (Neo4j, ChromaDB, SQLite)
PYTHONPATH=. python scripts/verify_connections.py

# Run MLflow UI
mlflow ui --port 5000

# Run tests (currently empty; infrastructure in place)
PYTHONPATH=. pytest tests/ -v
```

**Critical:** Always use `PYTHONPATH=.` — modules import from project root. Never use `cd` into subdirectories.

**Neo4j URI:** Always use `neo4j+ssc://` (not `neo4j+s://`) — local TLS proxy intercepts `neo4j+s://` and breaks the connection.

## Architecture

This is a **multi-agent LangGraph system** that answers water utility operator questions like "Can I shut down pipe_084 on 2026-05-10?" and produces step-by-step valve operation plans grounded in live Neo4j data.

### Request Flow

```
POST /api/v1/chat
  → chat.py route
  → invoke_graph(message, session_id)       # agents/orchestrator.py
  → intent_parser_node                       # Azure OpenAI — extracts pipe_id, date, op_type
  → [calendar_agent, neo4j_agent]           # parallel
  → [sop_agent, historical_agent]           # parallel, after neo4j
  → ops_plan_generator_node                 # Azure OpenAI — synthesizes JSON plan
  → orchestrator_response_node              # formats Markdown
```

The graph is built once as a singleton (`get_graph()`) and reused across requests. State is held in `OrchestratorState` (a TypedDict) and checkpoint-persisted in memory for session continuity.

### Neo4j Schema (critical — pipes are relationships, not nodes)

```
(Valve)-[:PIPE {pipe_id, from_id, to_id, diameter_mm, length_m,
                material, status, road_name, year_installed, pressure_mRL}]->(Valve)
(Tank)-[:PIPE ...]->(Valve)
```

- **No Junction nodes.** Match pipes with `MATCH ()-[p:PIPE {pipe_id: $id}]->()`.
- `from_id` / `to_id` on the PIPE relationship are the valve `id` properties (redundant but used for SOP traversal).
- `pipe_001` and `pipe_002` are Tank-connected — they won't appear in `MATCH (v1:Valve)-[:PIPE]->(v2:Valve)` patterns.
- Variable-depth traversals must use f-string literals, not Cypher parameters: `[:PIPE*1..{depth}]` not `[:PIPE*1..$depth]`.

### Agent Responsibilities

| Agent | LLM | Source | Output |
|-------|-----|--------|--------|
| `intent_parser_node` | Azure OpenAI | user query | pipe_id, date, op_type, confidence |
| `neo4j_agent_node` | Azure OpenAI | Neo4j | TopologyContext (valves, downstream, alt path) |
| `calendar_agent_node` | none (SQL) | SQLite | CalendarContext (conflicts, blocking) |
| `sop_agent_node` | Llama 3.3 70B* | ChromaDB | SOPContext (retrieved chunks, principles) |
| `historical_agent_node` | Llama 3.3 70B* | ChromaDB | HistoricalContext (similar past plans) |
| `ops_plan_generator_node` | Azure OpenAI | all contexts | OperationsPlan JSON |

*Configurable via `AGENT_PROVIDER_SOP_AGENT` / `AGENT_PROVIDER_HISTORICAL_AGENT` env vars.

### Parallel Safety

`agents_completed` and `error_messages` in `OrchestratorState` use `Annotated[list[str], operator.add]` — required because calendar and neo4j nodes run in parallel and both append to these lists. Never change these to plain `list[str]`.

### LLM Client Routing

`config/settings.py:get_llm_client(agent_name)` returns either an `AzureOpenAI` or `OpenAI` (Together.ai-compatible) client based on `settings.agent_providers` mapping — provider values are `"azure"`, `"together"`, or `"none"` (deterministic agents). Both clients use the OpenAI `chat.completions.create` API with `max_completion_tokens`. The system was migrated off Anthropic Claude — there are no `messages.create`, `cache_control`, or `anthropic` SDK calls left; do not reintroduce them.

### Data Stores

| Store | Purpose | Path |
|-------|---------|------|
| Neo4j Aura | Live network graph (valves, pipes) | `NEO4J_URI` env var |
| ChromaDB | SOP document embeddings + historical plans | `./data/chroma_db` |
| SQLite | Scheduled operations calendar | `./data/calendar.db` |

ChromaDB collections: `sop_documents`, `historical_plans`. Embedding model: `all-MiniLM-L6-v2`.

### SOP Document Ingestion

Drop `.txt`, `.pdf`, or `.docx` files into `data/seed/sop_documents/` then run `ingest_sop.py`. Chunks are 800 chars with 100 overlap. Upsert is idempotent (chunk IDs are `{stem}_chunk_{i:04d}`).

### API Layer

`api/main.py` lifespan runs: Neo4j ping → ChromaDB pre-warm → SQLite bootstrap → MLflow tracing setup. The chat route (`api/routes/chat.py`) calls `invoke_graph()` and maps the returned `OrchestratorState` to `ChatResponse`. LangGraph `__interrupt__` (human-in-the-loop for clarification) surfaces as the `awaiting_clarification` field — the API must handle this, not treat it as an error.

### Human-in-the-Loop Clarification

The graph pauses via `interrupt()` when pipe_id or date is missing (max 2 rounds). When testing via Python directly, include the full time range in the query (`08:00 to 16:00`) to bypass the clarification interrupt, otherwise `invoke_graph()` returns state with `__interrupt__` key instead of a plan.
