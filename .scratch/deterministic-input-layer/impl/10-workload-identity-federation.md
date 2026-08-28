# 10 — Workload Identity Federation for billed CI

**What to build:** The billed CI jobs authenticate to Vertex via federation behind a GitHub Environment
with required reviewers, so a paid run is a deliberate act with a name attached. **Out of scope of the
input-layer effort itself** — tracked here only because slices 12 and 13 block on it.

**Blocked by:** None — can start immediately (independent, external track).

**Status:** ready-for-agent

- [ ] `WIF_PROVIDER` secret / workload-identity provider configured so `billed-safety` and
  `billed-personal-data` authenticate without a static key.
- [ ] Billed jobs sit behind a GitHub Environment with required reviewers; the developer is prompted with
  the run's cost; no path-based auto-skip.
- [ ] Until this lands, the two billed jobs (shipped wired in slices 12/13) fail loudly as **unconfigured**
  rather than pretending they ran.
