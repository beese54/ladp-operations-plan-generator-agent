# Valve & Isolation Troubleshooting Guide — PUB Water Network

> **DISCLAIMER:** This document was created for the LADP project demonstration.
> Content is derived from SME input (Barry Koh, ex-PUB ops), codebase constants,
> and general water engineering knowledge. It is NOT an official PUB document and
> has not been formally reviewed or approved by PUB operations management. For
> production deployment, this must be replaced with or validated against official
> PUB procedures.

This guide covers common problems encountered during valve operations and pipe
isolation work. It is intended for field crew and ops planners.

---

## Valve Stuck (Will Not Turn)

**Symptom:** The handwheel will not rotate in the intended direction despite
applying normal force.

**Remedy:**
1. Turn the valve **one full round in the opposite direction** to unseat any
   debris, corrosion, or sediment that has built up at the current position.
2. Try again in the intended direction (anticlockwise to close at PUB).
3. If still stuck, repeat the reverse-then-forward motion up to **five times**.
4. If it still will not turn after five attempts:
   - **Stop immediately.** Do not use excessive force, pipe wrenches on the
     handwheel, or improvised lever extensions.
   - **Inform your supervisor.** The valve may have internal corrosion, debris
     lodged in the gate channel, or gland packing failure that requires
     maintenance intervention, not field-crew force.

**Why this matters:** Forcing a seized valve risks shearing the spindle, cracking
the valve body, or stripping the handwheel nut — any of which would leave the
valve inoperable and the pipe unable to be isolated at all.

---

## Valve Only Partially Closes (e.g. 70–90% Closed)

**Symptom:** The handwheel has reached resistance before the expected number of
turns for full closure. The valve is mostly closed but not fully seated.

**Remedy:**
1. Apply the same **reverse-then-forward** technique: one full round in the
   opposite direction, then try closing again.
2. Repeat up to **five times**.
3. If the valve still cannot reach full closure after five attempts:
   - **Stop and inform your supervisor.** A partially closed valve does **not**
     guarantee isolation — pressurised water can still flow past a gate that is
     not fully seated against its seating face.
   - The operations plan may need to be **revised** because the isolation is not
     complete. Do not proceed with downstream work if the pipe is not confirmed
     fully isolated.

**Risk of proceeding with partial closure:** If the valve is only 80% closed,
the remaining 20% gap allows water to flow. This means:
- Downstream fittings opened by the crew will spray pressurised water
- The pipe section is NOT safe to work on
- Customer supply interruption may differ from what was planned

---

## Spindle Leaking After Operation

**Symptom:** Water weeping or dripping from around the valve spindle (the shaft
that connects the handwheel to the gate) after operating the valve.

**Cause:** The gland packing (a sealing material around the spindle) may have
dried out, compressed, or been disturbed by the rotation after being static for
an extended period.

**Remedy:**
1. Try the **reverse-then-forward** technique — one full round in the opposite
   direction, then back to the operating position. This can reseat the packing.
2. Repeat up to **five times**.
3. If leaking persists after five attempts:
   - **Inform your supervisor** for the next course of action.
   - The valve may need **gland packing adjustment or replacement**, which is a
     maintenance task, not a field-crew task during an isolation operation.
   - A small weep is common on long-static valves and is not dangerous in the
     short term, but it should be logged and scheduled for repair.

---

## Water Still Flowing After All Valves Closed

**Symptom:** All valves in the isolation plan have been operated to full closure,
but the pipe section downstream still has water flowing through it.

**Diagnosis:**
1. A valve is likely **not fully seated**. Return to each valve in the isolation
   sequence and confirm it is at the mechanical stop (no further rotation possible
   in the closing direction — anticlockwise at PUB).
2. Apply the **reverse-then-forward** technique on any valve that feels like it
   has not reached its fully-closed limit.
3. If all valves are confirmed fully closed and water still flows:
   - There may be an **uncharted bypass, crossover connection, or hidden
     interconnection** not shown in the isolation plan.
   - **Stop work immediately and inform your supervisor.** The operations plan may
     be based on incomplete or outdated network data.
   - Do NOT proceed with any downstream work on a pipe section that has not been
     confirmed as depressurised.

---

## Valve Found Already Closed When Plan Said It Was Open

**Symptom:** You arrive at a valve location and find the valve already in the
closed position, but the operations plan shows it as open.

**Action:**
- **Stop and immediately inform your supervisor.** This is a topology mismatch
  between the network data and the real-world state.
- It directly affects the operations plan because:
  - The planned isolation sequence assumed this valve was open (and would need to
    be closed by the crew).
  - If it was already closed, the upstream/downstream flow may be different from
    what the plan modelled.
  - Other valves in the chain may be affected by this discrepancy.
- Do NOT continue with the next step until the supervisor has reviewed the plan
  and confirmed it is still valid given the actual valve state.
- The network graph (Neo4j) should be updated to reflect the real status after
  the operation is complete.

---

## Pressurised Water Spraying from a Fitting

**Symptom:** When loosening a fitting downstream of closed valves, water sprays
out under pressure.

**Immediate action:**
1. **Retighten the fitting immediately.** Do not continue loosening it.
2. The pipe is **still pressurised**, which means at least one upstream valve has
   not been fully closed.
3. Return to the isolation valves and check each one is at full mechanical closure.
4. Re-verify isolation by slowly loosening the fitting again — if no pressure, the
   pipe is confirmed isolated.

**Root cause:** This occurs when a valve in the isolation plan is not fully seated
against its gate face. Even a small gap allows system pressure to reach the work
area.

---

## General Troubleshooting Principles

1. **The reverse-then-forward technique** (one full round opposite, then try
   again) is the standard first remedy for any valve that is stuck, partially
   closed, or leaking at the spindle. It works by dislodging debris or corrosion
   from the seating face.

2. **Five attempts maximum.** If five cycles of reverse-then-forward do not resolve
   the problem, stop and escalate. Further force is more likely to damage the valve
   than to fix it.

3. **Never proceed with uncertain isolation.** If there is any doubt about whether
   the pipe section is fully depressurised:
   - Do not open fittings or cut into pipe.
   - Do not allow crew to enter excavations adjacent to the pipe.
   - Escalate to your supervisor.

4. **Log everything.** Any valve found in an unexpected state, any stuck operation,
   any partial closure, and any leak should be reported — even if it resolved after
   the reverse-then-forward technique. This information helps maintain accurate
   network records.

5. **Escalation is not failure.** Field crews are expected to escalate early rather
   than improvise fixes that could compromise safety or damage assets. The
   supervisor has access to additional resources (maintenance crews, updated network
   records, and authority to revise the plan).
