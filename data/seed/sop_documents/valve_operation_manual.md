# Valve Operation Manual — PUB Water Network

> **DISCLAIMER:** This document was created for the LADP project demonstration.
> Content is derived from SME input (Barry Koh, ex-PUB ops), codebase constants,
> and general water engineering knowledge. It is NOT an official PUB document and
> has not been formally reviewed or approved by PUB operations management. For
> production deployment, this must be replaced with or validated against official
> PUB procedures.

## ⚠️ IMPORTANT: PUB Valve Direction Convention

PUB valves follow the **opposite** convention to most manufacturer documentation:

- **Anticlockwise (counter-clockwise) to CLOSE**
- **Clockwise to OPEN**

This is the confirmed PUB standard. Do not follow generic valve manuals that state
"clockwise to close" — those refer to a different convention used outside PUB's
network. If in doubt, check the valve marker plate on site before operating.

---

## Handwheel Turns

The number of full handwheel turns required to fully open or close a gate valve
depends on its diameter:

**Formula:** turns = ceiling(diameter_in_inches × 2 + 1)

| Valve Diameter (mm) | Approximate Turns | Classification |
|---------------------|-------------------|----------------|
| 100 mm              | 9 turns           | Small          |
| 150 mm              | 13 turns          | Small          |
| 200 mm              | 17 turns          | Small          |
| 300 mm              | 25 turns          | Small          |
| 500 mm              | 41 turns          | Small (boundary)|
| 700 mm              | 57 turns          | Large          |
| 900 mm              | 73 turns          | Large          |

**Large valves** are those with diameter greater than 500 mm.

---

## Closing Speed — Why Slow Closure Matters

**Never close a valve quickly.** Rapid closure causes water hammer (pressure
transient) — a sudden spike in pressure that can burst fittings, damage pipe
joints, and disturb sediment throughout the network.

### Closing Rate by Valve Size

**Small valves (≤ 500 mm):**
- First 70% of turns: close at normal speed (approximately 1 turn per minute)
- Final 30% of turns: slow to half speed (approximately 1 turn per 2 minutes)

**Large valves (> 500 mm):**
- First 70% of turns: close at normal speed (approximately 1 turn per minute)
- Final 30% of turns: reduce to quarter speed (approximately 1 turn per 4 minutes)

The slow final phase is critical for large valves because the volume of water
being redirected is proportionally larger, making the pressure transient more
severe if the last portion of closure is rushed.

### Opening Rate (All Sizes)

- First 30% of turns: open slowly (approximately 1 turn per 2 minutes)
- Remaining 70% of turns: open at normal speed (approximately 1 turn per minute)

Opening is generally faster than closing because the risk of pressure surge is
lower when increasing flow than when restricting it.

---

## Approximate Operation Times

Based on the closing rates above, the approximate time to fully operate a valve:

| Valve Diameter | Time to Close | Time to Open |
|----------------|---------------|--------------|
| 300 mm         | ~33 minutes   | ~33 minutes  |
| 500 mm         | ~53 minutes   | ~53 minutes  |
| 700 mm         | ~108 minutes  | ~74 minutes  |
| 900 mm         | ~139 minutes  | ~95 minutes  |

Large valves take noticeably longer to close than to open because of the slower
final-30% rate during closure.

**Travel time between consecutive valves:** Allow approximately 20 minutes
between operating one valve and starting the next, for walking between valve
locations and verifying the previous operation.

---

## Torque and Manpower

Gate valves require physical force (torque) applied through the handwheel. The
required effort scales with diameter:

| Valve Diameter | Manpower Required | Method |
|----------------|-------------------|--------|
| ≤ 300 mm       | 1 person          | Standard key bar |
| 500 mm         | 2 people          | Key bar, turning together |
| 700 mm         | 4 people          | Key bar, turning concurrently |
| 900 mm         | 4+ people         | Key bar, turning concurrently; consider mechanical assist |

**For a 700 mm gate valve:** four people are needed to manually apply sufficient
torque. They should turn the valve concurrently (not sequentially) to maintain
steady rotational force.

**Damage risk:** If the valve does not move with the correct number of people
applying force together, **do not use excessive force or improvised leverage**.
Stop and inform your supervisor. A seized valve may have corrosion, debris, or
gland packing failure that requires maintenance, not brute force.

---

## Valve Operation Sequence During Isolation

When isolating a pipe section, valves are operated in a specific order determined
by the SOP shutdown chain (traced from the network graph). The general principle:

1. **Close valves in the order specified by the isolation plan** — from the
   upstream valve towards the tail-end valve, following the pipe route.
2. **Verify isolation** after closing all valves — check a nearby fitting
   downstream of the last closed valve. If pressurised water is still flowing,
   a valve is not fully seated.
3. **Re-open valves in reverse order** when the work is complete — tail-end valve
   first, working back towards the upstream valve. This prevents a sudden pressure
   wave from hitting the work site.

**Never re-open valves in a random order.** The reverse sequence ensures pressure
is restored gradually from the supply side, preventing surge damage.

---

## Troubleshooting During Operation

### Valve Stuck (Will Not Turn)

1. Turn the valve **one full round in the opposite direction** to unseat any debris
   or corrosion at the current position.
2. Try again in the intended direction.
3. If still stuck, repeat the reverse-then-forward motion up to **five times**.
4. If it still will not turn after five attempts, **stop and inform your
   supervisor**. Do not use excessive force, pipe wrenches on the handwheel, or
   improvised extensions — these can shear the spindle or crack the valve body.

### Valve Only Partially Closes (e.g. 80% Closed)

1. Apply the same reverse-then-forward technique described above.
2. Repeat up to five times.
3. If the valve still cannot be fully closed, **stop and inform your supervisor**
   — the operations plan may need to be revised because a partially closed valve
   does not guarantee isolation.

### Spindle Leaking After Operation

A small weep at the spindle gland is common after operating a valve that has been
static for a long period — the gland packing may have settled.

1. Try the reverse-then-forward technique (one full round opposite, then back) up
   to five times. This can reseat the packing.
2. If leaking persists after five attempts, **inform your supervisor** for the
   next course of action. The valve may need gland packing adjustment or
   replacement, which is a maintenance task, not a field-crew task.

### Water Still Flowing After All Valves Closed

If you have closed all valves in the isolation plan but water is still flowing
through the pipe section:

1. A valve is likely **not fully seated**. Return to each valve and confirm it is
   at full closure (no further turns possible in the closing direction).
2. Apply the reverse-then-forward technique on any valve that feels like it has
   not bottomed out.
3. If all valves are confirmed fully closed and water still flows, there may be an
   **uncharted bypass or an interconnection not shown in the plan**. Stop and
   inform your supervisor immediately — the operations plan may be based on
   incomplete network data.

---

## Water Quality After Reopening

When valves are reopened after an isolation:

- Residents downstream may experience **dirty or discoloured water** for a short
  period. This is caused by resuspension of naturally occurring mineral deposits
  (iron, manganese) that settle in the pipe during normal operation and are
  disturbed when flow direction or velocity changes.
- Advise residents to **flush their taps for 10 to 15 minutes**. If the water is
  still discoloured after 15 minutes, ask them to contact you again.
- In cases where turbidity remains high (measured with a turbidity meter, target
  < 5 NTU), extend flushing to **20–30 minutes** before restoring supply to
  customers.

---

## Air Locks After Refilling

When a pipe section is refilled after isolation work:

- Air can become trapped in high points of the pipe, creating an **air lock** that
  blocks water flow even though the pipe is technically pressurised.
- Check the **nearby air valves** — these are automatic devices that should vent
  trapped air as the pipe refills.
- If the air lock persists, the air valve may not be functioning correctly.
  Schedule a **maintenance check on the air valves** for a later date.
- Do **not** attempt to dismantle or repair an air valve in the field during an
  isolation operation — it is a separate maintenance task.

---

## Safety Reminders

- **PPE required for all valve operations:** Helmet, safety gloves, and safety
  shoes as a minimum.
- **Water spraying from a fitting** after you loosen it means the pipe is still
  pressurised — a valve upstream has not been fully closed. Retighten the fitting
  immediately and recheck all valves before proceeding.
- **Excavations filling with water:** deploy a submersible pump to remove the
  water first. If the level does not drop, deploy a second pump. If it still does
  not drop, **stop work and inform your supervisor** — there may be an active
  leak or an unclosed valve feeding the excavation.
- **Never enter a flooded excavation** without confirming the water source has
  been isolated and the water level is dropping under pumping.
