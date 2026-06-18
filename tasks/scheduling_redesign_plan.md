# Plan — Conversational Scheduling Agent + Calendar UI

Status: **AWAITING APPROVAL** (no production code until approved — gatekeeper clause)
Date drafted: 2026-06-16

## Decisions locked with user
1. **Festive blackout = ALL 11 public holidays**, ±7 calendar days around each (including in-lieu Mondays).
2. **Emergency displacement → auto-propose next valid slot**, user confirms before commit.
3. **Emergencies bypass ALL scheduling rules** (no-Friday, 3-day gap, holiday blackout). Schedulable anytime.
4. (Assumption, correctable) A feasible **planned** request is **booked into the calendar after user confirmation** — not silently, not check-only.

## Rule set
**Intake (conversational slot-filling):** elicit any missing — pipe_id, date(s) (single day or range), start time, end time, and **planned vs emergency**. Ask one slot at a time, naturally.

**PLANNED op rules:**
- R1 — No op within ±7 calendar days of any of the 11 SG public holidays (incl. in-lieu).
- R2 — ≥3 working days clear before the next scheduled operation (no back-to-back; officer rest). Working day = Mon–Fri excluding public holidays.
- R3 — Op may not **start on a Friday** → propose the following Monday.

**EMERGENCY op rules:**
- E1 — Bypasses R1/R2/R3; can be scheduled anytime.
- E2 — Preempts any overlapping PLANNED op.
- E3 — Each displaced PLANNED op gets an auto-proposed next valid slot (satisfying R1–R3), surfaced for user confirmation, then rebooked.

## Architecture (fits existing LangGraph + React app)

### A. Holiday config (data, editable)
- `data/seed/sg_public_holidays.json` — 2026 + 2027, all 11/yr, actual + in-lieu dates. Source: MOM-gazetted (retrieved 2026-06-16). Marked as updatable config, never hardcoded in logic.

### B. Deterministic rules engine (NEW, pure Python, no LLM, fully unit-tested)
- `tools/scheduling_rules.py`:
  - `load_holidays()`, `blackout_dates()` → set of all blocked dates (±7d around each holiday).
  - `is_working_day(d)`, `working_days_between(d1, d2)`.
  - `validate_planned(pipe_id, start, end, existing_ops)` → `ValidationResult{ok, violations[]}` (checks R1–R3).
  - `next_valid_slot(desired_start, duration_hours, existing_ops)` → earliest date satisfying R1–R3.
  - `find_displaced(emergency_start, emergency_end, existing_ops)` → overlapping PLANNED ops.
- Rationale: deterministic = testable + never hallucinates a date (same philosophy as the SOP chain).

### C. Schedule agent node (evolve `agents/calendar_agent.py`)
- For PLANNED: call `validate_planned`; on failure attach violations + `next_valid_slot` suggestion to state.
- For EMERGENCY: always feasible; call `find_displaced`; compute `next_valid_slot` reschedule proposal per displaced op.
- Output flows into `ops_plan_generator` / response so the reply explains conflicts + proposals conversationally.

### D. Conversational intake (extend `intent_parser_node` + clarification interrupt)
- Intent parser extracts: pipe_id, date(s), start_time, end_time, **operation_class (PLANNED|EMERGENCY)**.
- Slot-aware clarification: extend `awaiting_clarification` enum to include `time_range` + `operation_class`; ask one missing slot at a time. May raise max clarification rounds beyond 2.
- `schemas/graph_state.py`: add `operation_class: Optional[str]` + `date_range_end` for ranges.

### E. Booking + emergency reschedule (write path, HITL-confirmed)
- Confirmation interrupt before any DB write.
- PLANNED feasible + confirm → `create_scheduled_operation(...)`.
- EMERGENCY confirm → book emergency, then per displaced op show proposed slot → on confirm update that op's dates.

### F. Calendar UI (React)
- Backend: reuse `GET /api/v1/schedule` (verify response shape); add `GET /api/v1/holidays` for blackout shading.
- Frontend: `CalendarView.jsx` — month grid; PLANNED vs EMERGENCY colour-coded; festive blackout shaded; click op → detail popover. Toggle/tab beside the existing Cytoscape network graph.

### G. Seed data
- Seed `scheduled_operations` with sample PLANNED ops across 2026–2027 (incl. the pipe_003/pipe_033 conflicts noted previously) so the calendar + conflict logic are demonstrable.

## Proposed phasing (each phase independently verifiable)
- **P1** — Holiday config + rules engine + unit tests (no graph wiring). *Verify: pytest.*
- **P2** — Schedule agent node + state fields; planned validation in chat. *Verify: chat shows violations + suggested slot.*
- **P3** — Conversational slot-filling intake (incl. planned/emergency). *Verify: missing-info dialog.*
- **P4** — Booking + emergency preemption/reschedule write path. *Verify: emergency displaces + rebooks.*
- **P5** — Calendar UI + holidays endpoint + seed data. *Verify: calendar renders in webapp.*

## RESUME HERE (paused 2026-06-17)

**Committed:** Phase 1 (commit dad9189) + network restore tool (e8f4907). Both on `main`, NOT pushed.

**Done since:** S2.1 (operation_class migration, applied to live calendar.db), S5.3 (12 planned 2026 ops loaded, created_by='seed'), S2.2 (state fields), S2.3 (schedule agent), S2.4 (schedule-agent tests). **Phase 2 complete + verified + committed.**

**S2.2–S2.4 VERIFIED (2026-06-17):**
- `schemas/graph_state.py` — CalendarContext gained operation_class/rule_violations/suggested_start/displaced_ops; OrchestratorState gained operation_class, date_range_end, schedule_proposals; awaiting_clarification doc extended.
- `tools/calendar_tools.py` — new `get_active_operations()`.
- `agents/calendar_agent.py` — rewritten as schedule agent: PLANNED → validate_planned + next_valid_slot suggestion; EMERGENCY → find_displaced + reschedule proposals. No LLM.
- `agents/orchestrator.py` — `_fmt_dt` + `_format_scheduling_section` helpers; response node renders a 🗓️/🚨 scheduling section; initial_state seeds the 3 new fields.
- `tests/test_schedule_agent.py` — 5 tests (PLANNED R3/R1/clean + EMERGENCY displace/no-overlap). All green; full scheduling suite 23 passed.
- Live check ✅: planned Fri 2026-06-19 shutdown returns 🗓️ section with R3 + R2 violations and suggested next valid start 2026-07-01.

**Phase 3 REDESIGNED + COMPLETE + verified (2026-06-17).** User changed the model mid-phase:
- Intake asks only **pipe + planned/emergency + START date** — one natural question at a time. No time-of-day input.
- Fixed daily window **10:00–16:00**; the system **computes the end date** by laying the operation's effort across working days (skip weekends + holidays), spilling past 16:00 to the next working day.
- Effort **duration = valve_count × 45min + 1h setup**, valve_count from the shutdown chain (`build_sop_chain_data → shutdown_valves`).

S3.1–S3.5 shipped (commits 95113a2 = layout engine + tests; <this commit> = intake + graph reorder + calendar wiring):
- `tools/scheduling_rules.py` — `estimate_duration_hours`, `layout_working_window`, `next_valid_layout_start` + constants. 25 rules tests.
- `agents/orchestrator.py` — intent parser extracts pipe/start-date/operation_class (+ injects today); single slot-aware `clarification_node` (pipe → date → class), `MAX_CLARIFICATION_ROUNDS=4`; removed `time_clarification`; **graph reorder: intent → neo4j → [calendar, sop, historical]**; response shows computed window + duration.
- `agents/neo4j_agent.py` — builds `sop_chain` once (reused by calendar + ops_plan_generator).
- `agents/calendar_agent.py` — sizes op from valve count, lays out window, sets scheduled_start/end + date_range_end, validates / proposes.
- `schemas/graph_state.py` — CalendarContext +estimated_duration_hours/working_days_count; comment updates.
- `tests/test_schedule_agent.py` — rewritten for the new model. Full suite 31 passed.
- Verified live (direct + HTTP): one-shot, 3-turn slot-filling, Friday R3 + suggestion, emergency. pipe_084 = 4 valves → 4h → single-day window.

**Phase 4 COMPLETE + verified (2026-06-18).** Booking write path with HITL confirmation:
- `tools/calendar_tools.py` — `create_scheduled_operation` now sets `operation_class`; new `reschedule_operation`.
- `agents/orchestrator.py` — `booking_gate_node` (after orchestrator_response): offers the bookable window (feasible PLANNED → requested window; infeasible → suggested slot; EMERGENCY → computed window), `interrupt()`s for confirm/cancel, then `_commit_booking` writes via `create_scheduled_operation` and rebooks displaced ops (`reschedule_operation`) for emergencies. Graph: orchestrator_response → booking_gate → END.
- `schemas/graph_state.py` + `api_models.py` + `chat.py` — `booked_operation_id` surfaced.
- Tests: `tests/test_calendar_tools.py` + `tests/test_booking.py` (21 new). Full suite **52 passed**.
- Verified live: planned confirm → booked → next-day request trips R2 (persistence proven); cancel → nothing booked; infeasible → offered suggested slot; emergency → booked. Test rows cleaned up via `cancel_operation`.

**NEXT STEP (Phase 5 — Calendar UI + holidays endpoint):** S5.1 `GET /api/v1/holidays` + verify/extend `GET /api/v1/schedule` response shape; S5.2 frontend `CalendarView.jsx` (month grid, PLANNED vs EMERGENCY colour-coded, festive blackout shaded, click op → detail) with a toggle beside the Cytoscape graph. S5.3 (seed 2026 ops) already done. Pre-existing note: SOP retrieval logs `'RustBindingsAPI' object has no attribute 'bindings'` (ChromaDB), degrades gracefully — unrelated to scheduling.

**Servers:** backend :8001 + frontend :5174 run in the background; restart on resume.

## Open question for approval
- OK to proceed P1→P5 in order, committing per phase? Or want the full blueprint artifacts (specification.json / definition_of_done.md / progress_tracking.json) regenerated first per your enterprise workflow?
