# 12 — Disposition duplicate-runtime behavior and assets

**What to build:** A reviewed disposition of everything that exists outside the canonical runtime, proving what must migrate or remain compatible before the experimental duplicate runtime can be deleted.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] Inventory duplicate-runtime callers, deployment paths, behavior, tests, operational scripts, source assets, and generated artifacts.
- [ ] Identify the corresponding canonical capability or confirm that no equivalent exists.
- [ ] Classify every unique item as migrate, adapt through a thin entrypoint, archive outside the runtime, or discard as obsolete.
- [ ] Distinguish active production requirements from experiments and generated artifacts.
- [ ] Identify every root entrypoint that still has an active caller and the compatibility contract it must retain.
- [ ] Record migration and deletion evidence required for each retained item.
- [ ] Obtain review of the complete disposition without copying or deleting runtime behavior in this ticket.

