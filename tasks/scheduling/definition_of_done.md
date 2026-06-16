# Definition of Done — Conversational Scheduling Agent + Calendar UI

Each task is **Completed** only when ALL its criteria pass. Verification commands assume `PYTHONPATH=.`.

---

## Phase 1 — Holiday config + deterministic rules engine

### Task S1.1 — `data/seed/sg_public_holidays.json`
- [ ] Contains all 11 gazetted SG public holidays for **2026** and **2027** with `date`, `observed` (in-lieu Monday or null), `name`.
- [ ] Chinese New Year present as 2 entries each year; in-lieu dates correct (2026: 1 Jun, 10 Aug, 9 Nov; 2027: 8 Feb, 17 May).
- [ ] Valid JSON; loads via `json.load` without error.

### Task S1.2 — `tools/scheduling_rules.py` (deterministic, no LLM)
- [ ] `blackout_dates(["2026","2027"])` returns a set including e.g. `2026-02-10..2026-02-25` (CNY ±7d) and excludes a date >7d from any holiday.
- [ ] `is_working_day` returns False for Sat/Sun and for every holiday/observed date.
- [ ] `working_days_between` excludes weekends + holidays.
- [ ] `validate_planned` flags R1 (blackout), R2 (<3 working days to next op), R3 (Friday start) with a distinct violation string each.
- [ ] `next_valid_slot` never returns a Friday start, a blackout date, or a date violating the 3-working-day gap.
- [ ] `find_displaced` returns exactly the PLANNED ops overlapping a given emergency window.

### Task S1.3 — Unit tests `tests/test_scheduling_rules.py`
- [ ] Covers: blackout boundaries (day 7 blocked, day 8 allowed), Friday→Monday, 3-working-day gap across a holiday, emergency bypass (validate returns ok), displacement detection.
- [ ] `pytest tests/test_scheduling_rules.py -v` passes with 0 failures.

---

## Phase 2 — Schedule agent node + planned validation in chat

### Task S2.1 — `scheduled_operations` migration + `operation_class`
- [ ] `operation_class` column added (`PLANNED|EMERGENCY`, default `PLANNED`), idempotent (`IF NOT EXISTS` / guarded).
- [ ] Existing rows retain data; bootstrap runs twice without error.

### Task S2.2 — `schemas/graph_state.py` fields
- [ ] Adds `operation_class`, `date_range_end`, `schedule_proposals`; extends `awaiting_clarification`.
- [ ] `python -c "from schemas.graph_state import OrchestratorState"` imports cleanly.

### Task S2.3 — Evolve `agents/calendar_agent.py` → schedule agent
- [ ] PLANNED path: invalid window returns violations + a `next_valid_slot` suggestion in `calendar_context`.
- [ ] EMERGENCY path: always feasible; populates `schedule_proposals` for each displaced op.
- [ ] No LLM call inside rule evaluation (deterministic engine only).
- [ ] A chat query for a blackout/Friday date returns a response naming the violated rule + the suggested slot.

---

## Phase 3 — Conversational slot-filling intake

### Task S3.1 — Intent parser extracts all slots
- [ ] Extracts pipe_id, single date OR date range, start_time, end_time, operation_class.
- [ ] Missing slot → routes to slot-aware clarification.

### Task S3.2 — Slot-aware clarification
- [ ] Asks for exactly one missing slot at a time, in conversational tone, in order pipe_id → dates → time → planned/emergency.
- [ ] If user never states planned/emergency, agent explicitly asks.
- [ ] Manual webapp check: a bare "I want to shut a pipe" walks the user through all slots.

---

## Phase 4 — Booking + emergency preemption/reschedule

### Task S4.1 — Confirmation interrupt before writes
- [ ] No `scheduled_operations` write occurs without a user confirmation step.

### Task S4.2 — Planned booking
- [ ] Feasible planned + confirm → row inserted; reappears as a conflict for a subsequent overlapping query.

### Task S4.3 — Emergency preemption + reschedule
- [ ] Emergency books regardless of rules.
- [ ] Each displaced planned op shows a proposed valid new slot; on confirm it is rebooked (PATCH), and the rebooked date satisfies R1–R3.
- [ ] Verify end-to-end: schedule a planned op, then an overlapping emergency → planned op is moved to a proposed valid date.

---

## Phase 5 — Calendar UI + holidays endpoint + seed data

### Task S5.1 — `GET /api/v1/holidays` + extended `GET /api/v1/schedule`
- [ ] `/holidays?year=2026` returns 11 holidays + blackout date list.
- [ ] `/schedule?start=&end=` returns ops in range incl. `operation_class`.

### Task S5.2 — `CalendarView.jsx`
- [ ] Month grid renders; PLANNED and EMERGENCY ops visually distinct; festive blackout days shaded.
- [ ] Clicking an op shows its details; navigation between months works.
- [ ] Toggle between network graph and calendar in the running webapp (http://localhost:5174).

### Task S5.3 — Seed `scheduled_operations`
- [ ] Sample 2026–2027 planned ops seeded (incl. a deliberate pipe conflict) so the calendar and conflict logic are demonstrable on a fresh DB.

---

## Global done criteria
- [ ] `pytest tests/ -v` green.
- [ ] Backend + frontend start clean via existing run flow; `/api/v1/health` all OK.
- [ ] Each phase committed atomically; `progress_tracking.json` synced immediately after each.
- [ ] No regression to existing pipe_084 shutdown plan flow.
