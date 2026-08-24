# Specify the Baseline Split sequence and rollback checkpoints

Status: resolved
Type: grilling
Blocked by: 02, 03, 04, 05, 07

## Question

In what exact sequence will the Baseline Split be implemented by one coordinated effort, what are the stable checkpoints, what equivalence evidence is required before advancing, and what rollback action is specified for each?

## Resolution

- Formulated the sequential implementation order (Tickets 11–28):
  1. Freeze baseline oracle and contracts (Tickets 11–14).
  2. Extract feature modules incrementally: interaction control, perception, assessment & evidence, pedagogy, retrieval, response planning, generation (Tickets 15–21).
  3. Presentation & realization pipeline and state ownership enforcement (Tickets 22–25).
  4. Contract legacy turn, consolidate canonical runtime, and delete duplicates (Tickets 26–27).
  5. Ownership handoff verification (Ticket 28).
- Ensured zero breaking changes, continuous suite execution, and clean rollback boundaries.
