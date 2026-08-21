# Define the failure taxonomy and runtime state machines

Status: open
Type: grilling
Blocked by: 03, 04

## Question

What typed Failure Signals can each Module emit, which facts must each signal carry, and how do the Turn Coordinator and Runtime Supervisor map them to retry, explicit degradation, safe non-assessing fallback, fail-closed termination, or `STARTING`/`READY`/`DEGRADED`/`UNAVAILABLE` transitions?

Specify provisional-output and commit-failure behavior without allowing Modules to choose recovery policy or silently swallow failures.

## Comments
