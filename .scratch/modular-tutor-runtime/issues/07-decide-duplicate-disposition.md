# Decide duplicate-runtime disposition

Status: resolved
Type: grilling
Blocked by: 06

## Question

For every unique caller, deployment path, test, behavior, asset, and operational script in the duplicate runtime or root tree, what is its explicit disposition: migrate, adapt, archive outside the runtime, or discard as obsolete?

## Resolution

- Completely deleted `cloud_workspace_v8` directory tree as obsolete duplicate snapshot.
- Kept root entrypoint adapters and minimal test fixtures for backward compatibility.
- Consolidated all canonical modular components within `cloud_run_service`.
