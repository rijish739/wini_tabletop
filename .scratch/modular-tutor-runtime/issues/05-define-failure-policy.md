# Define failure classification, recovery policy, and supervisor health

Status: resolved
Type: grilling
Blocked by: 03, 04

## Question

How are local Module failures represented as typed Failure Signals, how does Turn Coordinator policy map them to continue, explicit degradation, safe non-assessing fallback, or fail-closed termination, and how does the Runtime Supervisor maintain service health?

## Resolution

- Defined typed `FailureSignal` contract carrying `capability`, `phase`, `severity`, `recoverability`, and `cause`.
- Set fail-closed policy for identity mismatch, corrupted state, safety-integrity failures, assessment tampering, and commit failures.
- Established explicit degradation paths for non-essential visual, filler, or presentation failures.
- Specified Runtime Supervisor 4-state lifecycle (`STARTING`, `READY`, `DEGRADED`, `UNAVAILABLE`) based on turn-level failure patterns.
