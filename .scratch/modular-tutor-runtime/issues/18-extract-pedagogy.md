# 18 — Extract Pedagogy

**What to build:** A deep Pedagogy Module that selects teaching action, learning mode, practice/test progression, and pacing from validated Perception and prior-assessment outcomes.

**Blocked by:** 16 — Extract Perception; 17 — Extract prior-attempt assessment and evidence.

**Status:** ready-for-agent

- [ ] Expose one Pedagogy Interface used by the coordinator and Interface-level tests.
- [ ] Move teaching-rule priority, mode resolution, practice/test planning, pacing, acknowledgement handling, clarification behavior, and learner-problem behavior behind the Interface.
- [ ] Assign Pedagogy semantic ownership of mode, practice/test plan, pacing, progression, and pending pedagogical offers.
- [ ] Consume validated observations and the current working state projection rather than raw dictionaries.
- [ ] Decide whether assessment is pedagogically appropriate without grading, arming, or writing evidence.
- [ ] Return typed pedagogical decisions, State Changes, and Failure Signals.
- [ ] Verify explain, practice, test, hint, misconception, transfer, clarification, acknowledgement, topic-change, and stop scenarios through the compatibility façade.
- [ ] Remove migrated pedagogy policy from the legacy adapter while keeping the equivalence oracle green.

