# Tech Stack

A multi-agent system that answers water-utility operator questions
(e.g. "Can I shut down pipe_084?") and produces HITL-confirmed, calendar-booked
valve operation plans grounded in live network data.

## Architecture at a glance

```
React/Cytoscape UI ──HTTP──▶ FastAPI ──▶ LangGraph orchestrator (multi-agent)
                                              │
                 ┌────────────────────────────┼─────────────────────────────┐
              Neo4j Aura                 Azure OpenAI / Together         SQLite
            (network graph)               (LLM agents)              (calendar + checkpoints)
                                          ChromaDB (RAG)            MLflow (tracing)
```

The orchestrator is a stateful graph (not a linear chain): a request flows
through intent parsing → conversational slot-filling → Neo4j topology → parallel
SOP/historical retrieval + deterministic scheduling → LLM plan synthesis →
conversational response → human-in-the-loop booking.

## Backend / orchestration
- **Python 3.12**
- **LangGraph 1.1** — the agent runtime. A `StateGraph` of nodes over a typed
  `OrchestratorState`, with conditional edges, `Send` fan-out for parallel
  agents, `interrupt()` / `Command(resume=...)` for human-in-the-loop.
- **LangGraph checkpointer (SQLite)** — `langgraph-checkpoint-sqlite`; durable
  per-session state keyed by `thread_id = session_id` (`./data/checkpoints.db`).
  Powers slot-filling, pending bookings, the chat transcript, and "show the
  steps" across backend restarts.
- **FastAPI 0.111 + Uvicorn** — async HTTP API (`/api/v1/chat`, `/schedule`,
  `/graph`, `/health`); lifespan wires up Neo4j / ChromaDB / SQLite / MLflow.
- **Pydantic v2 / pydantic-settings** — request/response models and env config.

## LLM providers (pluggable per agent)
- **Azure OpenAI** — default chat model (`gpt-5.4-mini-pub`); intent parsing,
  plan generation, general chat.
- **Together.ai** — `meta-llama/Llama-3.3-70B-Instruct-Turbo`, used for the SOP
  and historical retrieval agents (OpenAI-compatible API).
- Routing via `config/settings.py:get_llm_client(agent_name)` against an
  `AGENT_PROVIDER_*` mapping (`"azure"` | `"together"` | `"none"`). Both use the
  OpenAI `chat.completions` API through the `openai` SDK — **no LangChain chains
  or agents** are used for reasoning.

## Deterministic engines (no LLM — testable, reproducible)
- **`tools/scheduling_rules.py`** — holiday-blackout (R1), working-day-gap (R2),
  no-Friday-start (R3); working-day layout of an operation across 10:00–16:00
  days, skipping weekends/holidays.
- **`tools/valve_operation_rules.py`** — operation duration from valve diameter
  (turns + per-phase open/close rates + travel) per the valve-operation SOP.
- **`prompts/sop_walkthrough_prompt.py`** — Neo4j-traversal shutdown chain
  (isolation valves, alternate feed, reverse-isolation) rendered deterministically.

## Data stores
- **Neo4j Aura 5.x** (`neo4j` driver) — live network graph; pipes are
  relationships between Valve/Tank nodes.
- **ChromaDB 1.5** — vector store for SOP documents + historical plans
  (collections `sop_documents`, `historical_plans`).
- **SQLite** — operations calendar (`./data/calendar.db`) and the LangGraph
  checkpoint store (`./data/checkpoints.db`).

## ML / embeddings / retrieval
- **sentence-transformers** — `all-MiniLM-L6-v2` embeddings for RAG.
- **langchain-text-splitters** — document chunking during ingestion (the only
  LangChain usage in the project).
- **pypdf**, **pandas** — document parsing and tabular handling.

## Observability
- **MLflow 3.11** — request tracing (spans per agent) and auto-evaluation
  metrics, grouped per chat run.

## Frontend
- **React 18 + Vite 6** (ES modules).
- **Cytoscape.js** (`react-cytoscapejs`, `cytoscape-cose-bilkent` layout) — the
  network graph diagram, with an auto-trace highlight of a resolved pipe's
  shutdown chain.
- Chat panel calls `/api/v1/chat` with a stable per-session id.

## Alternate UI
- **Streamlit** — a chat-only UI (`ui/streamlit_app.py`), no graph.

## Testing & tooling
- **pytest** (+ `pytest-asyncio`, `pytest-mock`) — 70 tests across the rules
  engines, schedule agent, booking gate, valve timing, checkpointer durability,
  and transcript accumulation.
- **python-dotenv** — local secrets via `.env`.
- Git / GitHub for version control.

## Key runtime notes
- Always run with `PYTHONPATH=.` (imports resolve from project root).
- Neo4j URI must use `neo4j+ssc://` on the dev machine (local TLS proxy).
- Start everything with `start.ps1` (Windows) / `start.sh`, or run Uvicorn +
  `npm run dev` separately (API :8001, UI :5174).
