# Water Network Fundamentals — Reference Guide

> **DISCLAIMER:** This document was created for the LADP project demonstration.
> Content is derived from SME input (Barry Koh, ex-PUB ops), codebase constants,
> and general water engineering knowledge. It is NOT an official PUB document and
> has not been formally reviewed or approved by PUB operations management. For
> production deployment, this must be replaced with or validated against official
> PUB procedures.

This document provides background knowledge about water distribution network
concepts relevant to PUB operations staff. It covers terminology, design
principles, and physical phenomena that affect operations planning.

---

## Gate Valves

A **gate valve** is the most common type of valve in a water distribution network.
It controls flow by raising or lowering a flat gate (a disc or wedge) inside the
valve body.

**Key characteristics:**
- **Full-bore:** when fully open, the gate retracts completely out of the flow
  path, providing unrestricted flow with minimal pressure loss
- **Not suitable for throttling:** gate valves are designed to be either fully
  open or fully closed. Leaving them partially open causes the gate to vibrate
  in the flow, leading to premature wear and eventual failure
- **Bidirectional:** can be installed in either direction and will seal against
  flow from either side
- **Operated by handwheel:** requires multiple full turns to move from open to
  closed (see valve operation manual for turn counts by diameter)

**At PUB:** Gate valves are operated **anticlockwise to close** and **clockwise
to open**. This is the confirmed PUB standard and differs from many manufacturer
defaults.

Other valve types exist in water networks (butterfly valves, ball valves, check
valves) but gate valves are by far the most common for isolation purposes in
PUB's distribution network.

---

## Pressure Measurement: mRL (metres Relative Level)

**mRL** stands for **metres Relative Level** — a unit of pressure used in water
distribution engineering.

It expresses pressure as the equivalent height of a column of water that would
produce that pressure. For example, 30 mRL means the pressure at that point is
equivalent to having a 30-metre-tall column of water above it.

**Why mRL instead of bar or psi?**
- It directly relates to elevation — a tank at 45 metres elevation produces
  45 mRL of pressure at ground level (minus friction losses in the pipe)
- It makes hydraulic calculations intuitive — you can compare a pipe's pressure
  to the elevation of the tank feeding it
- It's the standard unit in Singapore's water network modelling

**Conversion:** 1 mRL ≈ 0.098 bar ≈ 1.42 psi (approximately, since 1 bar =
10.2 metres of water head)

**In the PUB Bukit Batok network:**
| Tier | Typical Pressure | Pipe Diameter |
|------|-----------------|---------------|
| Trunk main | 30 mRL | 900 mm |
| Primary distribution | 29 mRL | 700 mm |
| Secondary distribution | 20–25 mRL | 700 mm |
| Local distribution | 15 mRL | 300 mm |

Higher-pressure mains carry more water and serve larger areas. Isolating a trunk
main (30 mRL, 900 mm) affects far more customers than isolating a local
distribution pipe (15 mRL, 300 mm).

---

## Looped Networks vs Branched Networks

### Why Water Networks Are Built in Loops

A **looped network** (also called a ring main or meshed network) connects pipes
in closed circuits, so water can reach any point from multiple directions.

A **branched network** (also called a tree or dead-end system) has pipes that
terminate at endpoints — water can only reach those endpoints from one direction.

**PUB's Bukit Batok network is a looped network.** This is deliberate:

| Property | Looped Network | Branched Network |
|----------|---------------|-----------------|
| Redundancy | High — if one pipe is shut, water reaches customers via an alternate path | None — shutting one pipe cuts off everyone downstream |
| Isolation impact | Usually limited to a small zone; alternate feed available | Can affect many customers with no alternate supply |
| Water quality | Better — water circulates continuously, reducing stagnation | Poorer at dead ends — water sits idle and chlorine residual drops |
| Maintenance | Easier to isolate individual pipes without disrupting large areas | Difficult — any shutdown propagates to all downstream customers |
| Cost | More pipe, more valves, more expensive to build | Less infrastructure needed |

**Alternate feed** — the key concept in PUB's isolation planning — exists because
the network is looped. When pipe_084 is shut down, the tail-end valve (valve_037)
can still receive water from pipe_091 via valve_040, keeping downstream customers
supplied. This would be impossible in a branched network.

---

## Water Hammer (Pressure Transient)

**Water hammer** is a sudden pressure spike that travels through a pipe system
when the flow of water is abruptly stopped or changed in direction.

**Cause:** Water is nearly incompressible. When a valve is closed quickly, the
moving water has nowhere to go — its kinetic energy converts into a pressure wave
that travels at the speed of sound in water (~1400 m/s) back through the pipe.

**Effects:**
- A loud banging or hammering noise in the pipes
- Pressure spikes that can exceed the pipe's design pressure, potentially causing:
  - Burst joints or fittings
  - Cracked pipe walls
  - Damage to valves, meters, and other fittings
- Over time, repeated water hammer weakens pipe joints and causes fatigue failure
- Vibration to fittings and connected infrastructure

**Prevention during valve operations:**
- **Close valves slowly** — especially the final 30% of closure (see valve
  operation manual for rate guidance by valve size)
- **Open valves slowly** — especially the initial 30% to prevent a sudden rush
  of water into a depressurised section
- Large valves (> 500 mm) require even slower operation because the volume of
  water being redirected is much larger

**Relationship to pipe diameter:** Larger-diameter pipes carry more water at
higher velocity. Closing a 900 mm trunk main valve creates a far more severe
pressure transient than closing a 300 mm local distribution valve, because the
mass of water in motion is proportionally larger.

---

## Trunk Mains vs Distribution Mains

The water network is organised in a hierarchy based on pipe size and pressure:

### Trunk Mains

- **Diameter:** 900 mm (the largest pipes in the network)
- **Pressure:** 30 mRL (highest operating pressure)
- **Role:** Carry bulk water from treatment plants or service reservoirs to the
  distribution network. They are the "highways" of the water system.
- **Valves:** valve_001 and valve_002 in the Bukit Batok network
- **Customer connections:** None directly — trunk mains feed distribution mains,
  not individual properties
- **Isolation impact:** Very high — shutting a trunk main can affect the entire
  downstream distribution network if no alternate feed exists

### Primary Distribution Mains

- **Diameter:** 700 mm
- **Pressure:** 29 mRL
- **Role:** Distribute water from trunk mains to secondary and local pipes.
  These are the "arterial roads" of the network.
- **Customer connections:** Rarely connected directly to customers
- **Isolation impact:** High — typically serves multiple secondary mains

### Secondary Distribution Mains

- **Diameter:** 700 mm (same as primary, but at lower pressure)
- **Pressure:** 20–25 mRL
- **Role:** Further distribute water from primary mains to local distribution

### Local Distribution Mains

- **Diameter:** 300 mm (the smallest pipes planned in this system)
- **Pressure:** 15 mRL (lowest operating pressure)
- **Role:** Directly supply water to customer properties and buildings
- **Customer connections:** Service pipes branch off these mains to individual
  premises
- **Isolation impact:** Limited — usually affects a street or a few buildings

### Why This Hierarchy Matters for Isolation Planning

Isolating a higher-tier main:
- Affects more customers (larger zone)
- Takes longer (more valves, larger valves with more turns)
- Has higher consequence if something goes wrong (higher pressure, larger water
  volume)
- Is more likely to need the emergency preemption process

This is why the scheduling rules include working-day gaps (R2) and why the system
calculates duration from valve count — bigger operations need more care, more
time, and more planning buffer.
