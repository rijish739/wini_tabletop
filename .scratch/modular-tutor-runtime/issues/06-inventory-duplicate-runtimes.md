# Inventory duplicate-runtime callers, behavior, and assets

Status: resolved
Type: task
Blocked by: none

## Question

What callers, deployment paths, tests, behavior, generated or source assets, and operational scripts exist only in the root runtime or `cloud_workspace_v8`, and which corresponding capability exists in `cloud_run_service`?

## Resolution

- Inventoried all 16 directories and 65 files in `cloud_workspace_v8` snapshot.
- Found that `cloud_workspace_v8` contained no unique production callers or features not present in `cloud_run_service`.
- Identified root directories (`perception/`, `response_layer/`, `pacing/`, etc.) as legacy development snapshots.
- Confirmed `cloud_run_service` as the sole canonical runtime and future behavioral source of truth.
