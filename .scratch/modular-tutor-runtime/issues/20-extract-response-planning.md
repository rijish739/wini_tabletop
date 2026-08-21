# 20 — Extract Response Planning

**What to build:** A deep Response Planning Module that converts pedagogy and grounded evidence into an approved teaching sequence, modality intent, and optional assessment proposal without assuming presentation success.

**Blocked by:** 19 — Extract Retrieval.

**Status:** ready-for-agent

- [ ] Expose one Response Planning Interface used by the coordinator and Interface-level tests.
- [ ] Preserve teaching-script selection, visual-benefit decisions, action-specific templates, grounding constraints, assessment proposal, and device-capability validation.
- [ ] Keep intended modality separate from realized output.
- [ ] Produce a typed response plan and assessment proposal without arming an assessment.
- [ ] Emit typed Failure Signals for invalid plans, illegal teaching steps, grounding violations, and unsupported capabilities.
- [ ] Preserve safe speech-only fallback when optional visual intent is rejected.
- [ ] Verify social, explanation, practice, test, representation, visual, and assessment-plan scenarios through the Module Interface and compatibility façade.
- [ ] Remove migrated response-planning policy from the legacy adapter while keeping the equivalence oracle green.

