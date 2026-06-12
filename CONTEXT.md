# Project Context — Water Network Operations Plan Generator + MLflow

## What This Project Is

A **production-grade multi-agent AI system** that helps water utility operators answer the question:

> *"Can I shut down pipe X on date Y, and if so, what is the exact valve sequence to do it safely?"*

It combines a LangGraph agent graph, Claude Sonnet 4.6, Neo4j graph database, ChromaDB vector search, and SQLite to produce a complete, grounded operations plan — not just an LLM guess.

---

## How the System Works — Step by Step

### Step 1: User Submits a Query
The operator types a message in the Streamlit UI (or sends an HTTP POST to the API):
```
"I want to shut down pipe_001 on 2026-07-15 from 08:00 to 16:00"
```

### Step 2: Intent Parser (Claude Sonnet 4.6)
Claude reads the message and extracts structured intent:
```json
{
  "operation_type": "SHUTDOWN",
  "pipe_id": "pipe_001",
  "target_date": "2026-07-15",
  "scheduled_start": "2026-07-15T08:00:00",
  "scheduled_end": "2026-07-15T16:00:00",
  "confidence": 0.97
}
```
If the message is missing a pipe ID or date, the system asks the operator to clarify (up to 2 rounds).
If the message is a general question or off-topic, it routes to the General Response node.

### Step 3: Parallel Agent Fan-Out
Once intent is confirmed, two agents run simultaneously:

**Calendar Agent (SQLite)**
- Queries the `scheduled_operations` table
- Checks whether the requested pipe/time window conflicts with existing bookings
- Returns: is the date feasible? Any blocking or warning-level conflicts?

**Neo4j Agent (Neo4j Aura graph database)**
- Queries the live water network graph
- Retrieves: pipe properties (material, diameter, length), the two endpoint valves, downstream customer count, whether an alternative supply path exists
- Returns: full topology context for this pipe

### Step 4: Second Parallel Fan-Out (after Neo4j)
Once the topology is known, two more agents run in parallel:

**SOP Agent (ChromaDB + Together.ai Llama 3.3 70B)**
- Performs semantic vector search over SOP (Standard Operating Procedure) documents
- Retrieves the most relevant procedure chunks for this operation type and pipe properties
- Calls Llama 3.3 70B to extract the key principles from the retrieved chunks

**Historical Agent (ChromaDB, no LLM)**
- Performs semantic vector search over historical operations plans
- Returns the 3–5 most similar past operations (same pipe, similar type, or similar network zone) with their outcomes

### Step 5: Operations Plan Generator (Claude Sonnet 4.6)
All four context streams (calendar, topology, SOP principles, historical precedents) converge here.
Claude Sonnet 4.6 is prompted with everything and generates a structured JSON operations plan:
```json
{
  "feasibility_verdict": "FEASIBLE",
  "feasibility_reason": "No scheduling conflicts; alternative supply path exists via valve V_A07.",
  "pre_operation_checks": ["Verify pressure gauge at junction J12", "..."],
  "valve_sequence": [
    {"valve_id": "V_B03", "action": "CLOSE", "sequence_number": 1, "reason": "..."},
    {"valve_id": "V_A22", "action": "CLOSE", "sequence_number": 2, "reason": "..."}
  ],
  "estimated_duration_hours": 8.0,
  "affected_consumers_summary": "28 residential, 2 commercial properties affected",
  "notifications_required": ["Send 24-hour advance notice to affected customers"],
  "post_operation_steps": ["Verify pressure restoration", "Reopen valves in reverse order"],
  "safety_warnings": ["Monitor pressure surge during valve closure", "..."]
}
```

### Step 6: Orchestrator Response
The plan is formatted into a human-readable Markdown response with tables, emoji indicators, and structured sections, then returned to the Streamlit UI.

### Step 7: Audit Logging
Every conversation is logged to SQLite (`chat_sessions` table) with session ID, query, pipe ID, target date, feasibility verdict, and response summary.

---

## Technology Stack

| Component | Technology | Role |
|---|---|---|
| Agent framework | LangGraph 1.1.6 | Orchestrates the 11-node agent graph |
| Primary LLM | Claude Sonnet 4.6 (Anthropic) | Intent parsing, ops plan generation |
| Secondary LLM | Llama 3.3 70B (Together.ai) | SOP principle extraction, general Q&A |
| Network topology | Neo4j Aura (cloud graph DB) | Live pipe/valve/customer data |
| SOP search | ChromaDB + all-MiniLM-L6-v2 | Semantic vector search over SOP docs |
| Historical search | ChromaDB + all-MiniLM-L6-v2 | Semantic vector search over past plans |
| Calendar | SQLite | Scheduling conflict detection |
| API | FastAPI + uvicorn | HTTP interface |
| UI | Streamlit | Operator-facing web interface |
| Observability | MLflow (being added) | Tracing, evaluation, prompt management |

---

## MLflow Integration (Being Added)

Seven MLflow capabilities are being integrated to demonstrate LLMOps skills:

1. **Tracing** — Every LLM call and agent node is traced end-to-end in the MLflow UI, showing prompts, responses, token counts, and latency at every step
2. **Running Evaluations** — A CLI script runs the system against a golden dataset and calls `mlflow.evaluate()` with custom scorers
3. **Automatic Evaluation** — After every real API request, metrics are automatically logged to MLflow as a background task
4. **LLM Judges & Scorers** — 5 scorers including LLM-as-judge (Llama 3.3 70B) for safety compliance and plan coherence
5. **Evaluation Datasets** — Golden test cases versioned and registered in MLflow
6. **Prompt Management** — All system prompts registered in MLflow's prompt registry with version history
7. **Prompt Optimisation** — A/B compare prompt versions by running eval on v1 vs v2 and viewing metrics in MLflow

---

## Files and Directories

```
ladp_ops_generator_agent/
├── agents/                  ← LangGraph node implementations
│   ├── orchestrator.py      ← Main graph: all routing, intent parsing, response formatting
│   ├── ops_plan_generator.py ← Claude call that generates the JSON operations plan
│   ├── calendar_agent.py    ← SQLite conflict checker
│   ├── neo4j_agent.py       ← Cypher queries to Neo4j Aura
│   ├── sop_agent.py         ← ChromaDB search + LLM summarisation
│   └── historical_agent.py  ← ChromaDB search over past plans
├── api/                     ← FastAPI server
│   ├── main.py              ← App factory, lifespan hooks
│   └── routes/chat.py       ← POST /api/v1/chat endpoint
├── config/settings.py       ← Pydantic settings, LLM client factory
├── db/                      ← Database client wrappers (Neo4j, ChromaDB, SQLite)
├── tools/                   ← Query functions used by agents
├── schemas/                 ← Pydantic models and TypedDicts
├── ingestion/               ← Scripts to embed and load SOP/historical docs into ChromaDB
├── scripts/
│   ├── bootstrap_db.py      ← Initialises SQLite schema + creates ChromaDB collections
│   └── verify_connections.py ← Checks all 5 services are reachable
├── ui/streamlit_app.py      ← Operator-facing chat UI
├── data/
│   ├── seed/
│   │   ├── sop_documents/   ← *** YOU MUST DROP SOP FILES HERE ***
│   │   └── historical_plans/ ← *** YOU MUST DROP HISTORICAL PLAN FILES HERE ***
│   └── eval_datasets/       ← Golden evaluation test cases (CSV, being added)
├── evaluation/              ← MLflow integration package (being added)
├── tests/                   ← Unit/integration/E2E tests (not yet written)
├── .env                     ← API keys and connection strings (never commit)
└── requirements.txt         ← Python dependencies
```

---

## What You Still Need to Provide

### REQUIRED — System Will Not Work Without These

#### 1. SOP Documents → `data/seed/sop_documents/`
**What:** Standard Operating Procedure files for water network operations.
**Format:** `.txt` or `.pdf`
**Examples of what to include:**
- Valve isolation procedure
- Customer notification policy
- Emergency shutdown procedure
- Pressure testing procedure
- Post-operation reinstatement steps

**Why needed:** The SOP Agent does semantic search over these. Without them, every operations plan is generated without SOP grounding — the ChromaDB collection is empty.

#### 2. Historical Operations Plans → `data/seed/historical_plans/`
**What:** Records of past operations (shutdowns, inspections, maintenance) on your network.
**Format:** `.txt` or `.pdf`
**Examples of what to include:**
- "Pipe_001 emergency shutdown 2025-03-14 — outcome: successful, duration 4.5hr"
- "Inspection of pipe_033 2025-06-01 — 3 valves operated, no customer complaints"

**Why needed:** The Historical Agent retrieves similar past cases to help Claude reason about precedent. Without them, historical context is always empty.

---

### REQUIRED — Do This in Order After Dropping Files Above

#### Step 1: Run database bootstrap
```bash
# From project root
PYTHONPATH=. python scripts/bootstrap_db.py
```
This creates the SQLite schema and embeds all SOP/historical files into ChromaDB.

#### Step 2: Seed calendar test conflicts
Run this Python snippet once to create test scenarios for evaluation.
⚠️ pipe_001 and pipe_002 do NOT exist as Valve-Valve connections — use pipe_003 and pipe_033:
```python
import sqlite3, os
db_path = os.getenv("SQLITE_DB_PATH", "./data/calendar.db")
con = sqlite3.connect(db_path)
con.executescript("""
INSERT OR IGNORE INTO scheduled_operations
  (pipe_id, title, scheduled_start, scheduled_end, operation_type, status)
VALUES
  ('pipe_003','Annual pressure test','2026-07-10T07:00:00','2026-07-10T18:00:00','INSPECTION','scheduled'),
  ('pipe_033','Pipe relining','2026-08-01T06:00:00','2026-08-01T20:00:00','MAINTENANCE','scheduled');
""")
con.commit()
con.close()
print("Done.")
```

#### Step 3: Install new dependencies
```bash
pip install "mlflow>=2.20.0" "pandas>=2.0.0"
```

#### Step 4: Start the system and verify
```bash
# Terminal 1: API
PYTHONPATH=. uvicorn api.main:app --reload

# Terminal 2: Streamlit UI
streamlit run ui/streamlit_app.py

# Terminal 3: MLflow UI (after MLflow integration is implemented)
mlflow ui --port 5000
```

---

### NEEDED AFTER BOOTSTRAP — Fill in TBD Verdicts

Once the system is running, test these 4 queries and tell me the verdict each returns.
The verdict becomes the `expected_verdict` in the evaluation dataset.

| # | Query to send | Pipe | Date |
|---|---|---|---|
| A | "Shutdown pipe_003 on 2026-06-20 from 08:00 to 16:00" | pipe_003 | 2026-06-20 |
| B | "Shutdown pipe_009 on 2026-09-15 from 08:00 to 17:00" | pipe_009 | 2026-09-15 |
| C | "Inspect pipe_016 on 2026-06-30 from 09:00 to 13:00" | pipe_016 | 2026-06-30 |
| D | "Maintenance on pipe_147 on 2026-07-22 from 07:00 to 15:00" | pipe_147 | 2026-07-22 |

---

## Confirmed Network Topology (Bukit Batok, Singapore — verified 2026-04-29)

**~154 total pipes, 57+ valves. All valves status=open. Pipe status varies.**

### Schema corrections (compared to earlier memory)
- `Valve` has: `id`, `road_name`, `status`, `elevation` (Long), `diameter` (Long) — NOT `pressure_mRL`, NOT `year_installed`
- `PIPE` has: `pipe_id`, `from_id`, `to_id`, `road_name`, `status`, `pressure_mRL`, `diameter_mm`, `length_m`, `material`, `year_installed`
- `Tank` has: `id`, `elevation` only — NOT `capacity_mgd`
- `Junction` nodes do NOT exist in this database
- `has_customer` and `Number_of_customers` do NOT exist on PIPE — code bug pending fix

### Pressure tiers
| Tier | Pressure | Diameter | Valve range |
|---|---|---|---|
| Trunk main | 30 mRL | 900mm | valve_001, valve_002 |
| Primary distribution | 29 mRL | 700mm | valve_003–valve_014 |
| Secondary | 25/20 mRL | 700mm | valve_014–valve_021 |
| Local distribution | 15 mRL | 300mm | valve_022–valve_057 |

### Key hub valves
| Valve | Road | Connections (OPEN pipes out) |
|---|---|---|
| valve_001 | Bukit Batok West Ave 5, 900mm | pipe_003→v002, pipe_005→v003, pipe_006→v004, pipe_016→v008 |
| valve_002 | Bukit Batok West Ave 2, 900mm | pipe_009→v006, pipe_010→v007, pipe_033→v014 |
| valve_006 | Bukit Batok West Ave 3, 700mm | pipe_011→v008, pipe_012→v009, pipe_013→v010, pipe_014→v011, pipe_025→v013 |
| valve_014 | Bukit Batok Central, 700mm | pipe_037→v015, pipe_038→v018, pipe_039→v019, pipe_051→v020, pipe_142→v021 |

### Key pipes for operations planning (OPEN status)
| Pipe | Connection | Size | Road | Alt path? |
|---|---|---|---|---|
| pipe_003 | valve_001→valve_002 | 900mm Steel | Bukit Batok Link | YES — looped network |
| pipe_005 | valve_001→valve_003 | 700mm DI | Bukit Batok West Ave 7 | YES — via pipe_006 |
| pipe_009 | valve_002→valve_006 | 700mm DI | Bukit Batok West Ave 3 | YES — via v002→v007→v013→v006 |
| pipe_011 | valve_006→valve_008 | 700mm Steel | Bukit Batok West Ave 6 | YES — via pipe_012+pipe_020 |
| pipe_016 | valve_001→valve_008 | 700mm DI | Bukit Batok West Ave 6 | YES — via v001→v002→v006→v008 |
| pipe_033 | valve_002→valve_014 | 700mm DI | Bukit Batok Central | YES — via v002→v007→v013→v015→v014 |
| pipe_055 | valve_005→valve_022 | 300mm DI | Bukit Batok St 34 | YES — via pipe_056+pipe_152 |
| pipe_056 | valve_005→valve_023 | 300mm DI | Bukit Batok St 34 | YES — via pipe_055+pipe_151 |

### Permanently closed pipes (emergency/bypass — do not plan operations on these)
pipe_021/023, pipe_030/031, pipe_053/054, pipe_062, pipe_065, pipe_073/075, pipe_079/080, pipe_085/087/089/090, pipe_096/098/101/104, pipe_108/111/113/116, pipe_125/129/130/131, pipe_132–141 (all "Sector Connectors"), pipe_144/145/146/147/148/149, pipe_150, pipe_153/154/155/156

### pipe_001, pipe_002
Not found as Valve↔Valve connections — likely connect Tank nodes to valve_001/valve_002. Excluded from the data export. **Do not use these as eval test cases.**

---

## Important Notes

- **Neo4j connection:** Always use `neo4j+ssc://` in the `.env` — the local SSL proxy intercepts `neo4j+s://` and breaks the connection.
- **Pipes are relationships in Neo4j**, not nodes — the Cypher patterns use `(Valve)-[:PIPE]->(Valve)`.
- **LLM routing:** Claude handles intent parsing and plan generation. Llama 3.3 70B (Together.ai) handles SOP summarisation and general Q&A.
- **Prompt caching:** System prompts for the intent parser and ops plan generator are cached via Anthropic's prompt caching beta to reduce cost and latency.
- **Tests:** Unit/integration/E2E tests in `tests/` have not been written yet (Phase 8 pending).
