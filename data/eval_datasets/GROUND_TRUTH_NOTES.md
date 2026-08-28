# Ground Truth Provenance — RAG Probe Question Bank

Ground-truth answers in `rag_probe_questions.csv` (column `ground_truth`,
flagged by `sme_verified=YES`) were provided by **Barry Koh Jun Yong**, who
previously worked in the PUB water network operations department.

20 of 58 questions are SME-verified. The remainder are either awaiting an answer
or are out-of-scope rows graded on refusal rather than content.

Original wording was lightly edited for grammar and typos only. **No answer's
substance was changed.** Where an answer was ambiguous it was left as-is and
flagged below rather than guessed at.

---

## ⚠️ C01 — PUB valve direction is the OPPOSITE of industry convention

> **Q:** Which direction do I turn to close the valve?
> **A (SME, confirmed twice):** Turn **anticlockwise to close** and **clockwise to open**.

This contradicts the near-universal "clockwise to close" (right-hand-thread)
convention found in virtually every public valve manual and manufacturer
datasheet.

**Barry has explicitly confirmed this is correct for PUB.**

### Why this matters for the RAG corpus

Any generic valve operation manual sourced from the internet will state
*clockwise to close*. If such a document is ingested unmodified, the assistant
will confidently teach field crews the **wrong direction** — the single most
consequential error this system could make, because a crew member following it
would open a valve they were told to close, on a live main.

**Rules for anyone adding valve documentation:**

1. Do **not** ingest a third-party valve manual verbatim.
2. Any ingested valve document **must** state the PUB anticlockwise-to-close
   convention explicitly, and should say plainly that it differs from the
   general industry convention so a reader doesn't "correct" it later.
3. `C01` must stay in the probe bank permanently as a regression test. If the
   assistant ever answers "clockwise to close", the corpus has been contaminated.

---

## Answers that repeat a common remedy

`C05`, `C06`, `C07`, `C11` all centre on the same physical technique:

> Turn the valve one full round in the opposite direction, then try again in the
> intended direction.

This is not a copy-paste error — it is the standard first remedy for a valve that
is stuck, not fully seated, or leaking at the spindle. `C07` and `C11` add
"repeat up to five times, then inform your supervisor".

Implication for scoring: an exact-match scorer will look artificially strong on
these four rows. Prefer semantic similarity plus a check that the escalation step
is present, rather than string overlap.

## Escalation is the consistent theme in field-crew answers

`C07`, `C11`, `C15`, `C16`, `C20` all terminate in "inform your supervisor".
`C20` (valve found closed when the plan said open) escalates **immediately** with
no self-remedy attempt, because it invalidates the operations plan.

A good crew-facing answer should therefore almost always end with a clear
escalation path. Worth asserting as a behavioural check, not just a text match.

## Notification lead time appears twice

`P13` and `P18` both give **one week before, and again one day before**. These
should stay consistent with each other; if a future SME pass changes one, change
both.

## Open questions for the next SME session

- `C19` gives manpower (four people, turning concurrently) rather than a torque
  figure in N·m. If a numeric limit exists, it would be more useful.
- `C14` covers air-valve inspection but not how to clear an air lock that is
  already present.
- `C09` describes checking a nearby fitting for pressurised water. Is a pressure
  gauge reading also required, or is the visual check sufficient?
- 38 rows remain unanswered — the OPS_PLANNER set (16 blank) is the thinnest and
  would benefit most from a second pass.
