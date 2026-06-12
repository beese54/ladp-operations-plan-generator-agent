# Lessons

## Session: 2026-04-27 — Initial Build

### Schema Correction
**Mistake pattern:** Assumed water network would use `Pipe` as a node. Actual schema uses `[:PIPE]` as a relationship between `Valve` nodes. Consumer data lives on the relationship, not a separate node.

**Rule:** Before generating any Cypher queries, always confirm whether the target entity is a node or a relationship. Ask the user for their actual schema early.

**How to apply:** When given a Neo4j project, always inspect `CALL db.schema.visualization()` or ask for the schema explicitly before writing any graph queries.

---

### LangGraph Clarification Loop
**Pattern:** When user does not provide time (only date), the agent must ask — not assume a default.

**Rule:** Never silently fill in missing required parameters. Use `interrupt()` to surface the missing field to the user.

**How to apply:** Any parameter that affects scheduling or feasibility must be explicitly provided by the user. Add it to the clarification check in `route_after_intent`.
