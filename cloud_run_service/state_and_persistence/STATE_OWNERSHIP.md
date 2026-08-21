# State ownership matrix

The executable matrix is [`ownership.py`](ownership.py). Each durable learner
field and session-continuity field has exactly one semantic writer. Modules may
read only the paths listed in `readers`, receive those paths as immutable
capability views, and request writes with lifecycle `StateChange` values. The
State and Persistence module validates ownership, idempotency, conflicts, and
cross-state invariants before applying the working projection.

| Scope | Owned fields | Owner |
| --- | --- | --- |
| Learner | identity and schema bookkeeping | State and Persistence |
| Learner | concept, misconception, evidence ledger/index/projection, hope | Assessment and Evidence |
| Learner | global observations and global perception state | Perception |
| Learner | safety alerts | Interaction Control |
| Session | continuity, safety, pacing, response continuity | Interaction Control |
| Session | mode, test, and practice plans | Pedagogy |
| Session | pending assessment, hints, pending hope, voided checks | Assessment and Evidence |
| Session | served items and bridges | Retrieval |

`canonical_capability_access()` is the only production grant builder. The
architecture tests reject Feature Module implementation imports and direct
shared-state `.data` writes.
