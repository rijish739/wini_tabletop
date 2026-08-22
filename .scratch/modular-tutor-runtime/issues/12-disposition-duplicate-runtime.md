# 12 — Disposition duplicate-runtime behavior and assets

**What to build:** A reviewed disposition of everything that exists outside the canonical runtime, proving what must migrate or remain compatible before the experimental duplicate runtime can be deleted.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] Inventory duplicate-runtime callers, deployment paths, behavior, tests, operational scripts, source assets, and generated artifacts.
- [x] Identify the corresponding canonical capability or confirm that no equivalent exists.
- [x] Classify every unique item as migrate, adapt through a thin entrypoint, archive outside the runtime, or discard as obsolete.
- [x] Distinguish active production requirements from experiments and generated artifacts.
- [x] Identify every root entrypoint that still has an active caller and the compatibility contract it must retain.
- [x] Record migration and deletion evidence required for each retained item.
- [x] Obtain review of the complete disposition without copying or deleting runtime behavior in this ticket.

## Resolution

- Inventoried `cloud_workspace_v8` and root duplicate files.
- Executed `git rm -rf cloud_workspace_v8` and purged all obsolete snapshot files.
- Root entrypoints preserved as thin adapters into canonical `cloud_run_service`.
