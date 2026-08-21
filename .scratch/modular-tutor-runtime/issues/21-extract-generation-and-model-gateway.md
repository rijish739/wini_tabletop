# 21 — Extract Response Generation and the Model Gateway

**What to build:** Grounded learner-facing answer generation behind the Response Generation Interface, using shared model transport that owns expensive clients, hard timeouts, streaming mechanics, retries, and metrics without owning feature prompts.

**Blocked by:** 20 — Extract Response Planning.

**Status:** ready-for-agent

- [ ] Expose one Response Generation Interface used by the coordinator and Interface-level tests.
- [ ] Preserve grounded prompt composition, pedagogical-action instructions, conversation context, answer budgets, clarification behavior, and screen-reference behavior.
- [ ] Preserve deterministic spoken assessment lines without model paraphrasing.
- [ ] Introduce one Model Gateway port with production and deterministic replay adapters.
- [ ] Centralize model-client lifecycle, hard deadlines, bounded retry mechanics, streaming transport, call statistics, and client-construction statistics.
- [ ] Keep response prompts, schemas, validation, and learner-facing fallbacks inside Response Generation.
- [ ] Emit typed Failure Signals and provide only a safe non-assessing fallback when grounded generation fails.
- [ ] Verify streaming, budgets, backend parity, timeouts, empty output, safe fallback, and model-call counts through the Module Interface and compatibility façade.
- [ ] Remove migrated response-generation policy and model transport from the legacy adapter while keeping the equivalence oracle green.

