# 27 — Consolidate the canonical runtime

**What to build:** One behavioral source of truth, with every retained caller and required asset using the canonical modular runtime, only necessary thin compatibility entrypoints remaining, and the experimental duplicate runtime removed.

**Blocked by:** 12 — Disposition duplicate-runtime behavior and assets; 26 — Contract the legacy Turn implementation.

**Status:** ready-for-agent

- [ ] Execute every reviewed migrate, adapt, archive, and discard action from the duplicate-runtime disposition.
- [ ] Verify each active server, voice, UI, scripted, deployment, and operational caller against the canonical runtime.
- [ ] Convert demonstrably required root entrypoints into thin adapters with no feature policy or copied implementation.
- [ ] Migrate only required source assets and tests; do not promote experiments automatically.
- [ ] Remove obsolete deployment paths and duplicate feature implementations.
- [ ] Delete the experimental duplicate runtime after all blocking evidence passes.
- [ ] Verify retained assets resolve correctly and no active caller imports or executes the deleted runtime.
- [ ] Pass the frozen oracle and deletion-focused architecture checks after consolidation.

