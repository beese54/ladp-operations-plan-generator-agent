# SOP — Valve Operation Timing

**Purpose:** Define how long it takes to operate (open or close) a valve, so the
scheduling agent can compute an operation's true duration and therefore the time
the operation can end. This SOP governs *timing only*; the isolation sequence
itself is covered by the pipe-isolation SOP.

**Confirmed parameters (2026-06-18):** turns formula as below; size boundary
small ≤ 500 mm / large > 500 mm; travel 20 min; duration includes the re-feed /
reverse-isolation opens; turns rounded **up (ceiling)**.

---

## 1. Number of turns per valve

```
turns (T) = ceil( (diameter_mm ÷ 25.4) × 2 + 1 )
```

Convert the diameter from millimetres to inches, multiply by 2, add 1, and round
**up** to the next whole turn. Diameter is read from the valve's `diameter_mm`
property in the network graph.

| Diameter | Inches | Turns (T) |
|----------|--------|-----------|
| 300 mm   | 11.81  | **25**    |
| 700 mm   | 27.56  | **57**    |
| 900 mm   | 35.43  | **72**    |

---

## 2. Operating rates (per turn, by phase)

A valve is operated in two phases; the rate changes between them, split by turn
count.

### Small valves — diameter ≤ 500 mm

| Action | First phase | Second phase |
|--------|-------------|--------------|
| **Open**  | first 30% of turns @ 1 turn / **2 min** | remaining 70% @ 1 turn / **1 min** |
| **Close** | first 70% of turns @ 1 turn / **1 min** | last 30% @ 1 turn / **2 min** |

### Large valves — diameter > 500 mm

| Action | First phase | Second phase |
|--------|-------------|--------------|
| **Open**  | first 30% of turns @ 1 turn / **2 min** | remaining 70% @ 1 turn / **1 min** |
| **Close** | first 70% of turns @ 1 turn / **1 min** | last 30% @ 1 turn / **4 min** |

> The only difference for large valves is the **closing tail**: the final 30% is
> taken at 1 turn / 4 min (slower seating to avoid water hammer on large mains).

### Resulting per-valve time (closed form, T = total turns)

| Phase | Minutes |
|-------|---------|
| Open (any size)        | `0.3T×2 + 0.7T×1` = **1.3 × T** |
| Close (≤ 500 mm)       | `0.7T×1 + 0.3T×2` = **1.3 × T** |
| Close (> 500 mm)       | `0.7T×1 + 0.3T×4` = **1.9 × T** |

---

## 3. Per-valve operating times (reference)

| Diameter | Turns | Open | Close (≤500) | Close (>500) |
|----------|-------|------|--------------|--------------|
| 300 mm   | 25    | 32.5 min | 32.5 min | — |
| 700 mm   | 57    | 74.1 min | — | 108.3 min |
| 900 mm   | 72    | 93.6 min | — | 136.8 min |

---

## 4. Travel between valves

Allow **20 minutes** between consecutive valve operations for the operating
officer to travel between valves. An operation that performs K valve actions has
(K − 1) travel segments.

---

## 5. Which valve actions an isolation performs

Derived from the deterministic SOP shutdown chain:

- **Isolation:** **CLOSE** every valve in the shutdown chain (`shutdown_valves`).
- **Re-feed / reverse-isolation** (only when an **alternate feed** exists): **OPEN**
  the alternate-feed valve, and **OPEN** each reverse-isolation valve (one per
  reverse pair) to re-establish supply.

```
actions = [CLOSE v for v in shutdown_valves]
        + ( [OPEN alternate_feed_valve] + [OPEN reverse_pair.from_valve …]  if alternate feed )
```

Each action's time uses that valve's own diameter (Section 2–3).

---

## 6. Operation duration & end time

```
operation_minutes = Σ (time of each valve action)  +  (action_count − 1) × 20 min
```

The result is laid out over the working day(s) (10:00–16:00, skip weekends/
holidays — see the scheduling rules) to determine the **end date/time**.

### Worked example — isolate `pipe_084`

Alternate feed available (`pipe_091` via `valve_038`). All valves are 300 mm
(25 turns; open = close = 32.5 min).

| # | Valve | Ø | Action | Time |
|---|-------|-----|--------|------|
| 1 | valve_034 | 300 | CLOSE | 32.5 |
| 2 | valve_035 | 300 | CLOSE | 32.5 |
| 3 | valve_036 | 300 | CLOSE | 32.5 |
| 4 | valve_037 | 300 | CLOSE | 32.5 |
| 5 | valve_038 | 300 | OPEN (alt feed) | 32.5 |
| 6 | valve_037 | 300 | OPEN (reverse) | 32.5 |
| 7 | valve_036 | 300 | OPEN (reverse) | 32.5 |
| 8 | valve_035 | 300 | OPEN (reverse) | 32.5 |

- Valve time: 8 × 32.5 = **260 min**
- Travel: 7 × 20 = **140 min**
- **Total: 400 min ≈ 6.7 h** → spans two working days (≈ 6 h on day 1, ≈ 0.7 h on day 2).

> Note (model assumption): the re-feed opens counted are the alternate-feed valve
> plus one valve per reverse pair. If a different set of restore actions is
> intended, the action mapping in Section 5 is the single place to adjust it.
