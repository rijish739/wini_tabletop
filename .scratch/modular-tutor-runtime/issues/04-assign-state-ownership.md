# Assign state ownership and transaction semantics

Status: open
Type: grilling
Blocked by: 03

## Question

Which Module owns every Learner State and Session State field, which immutable typed view may each other Module read, which State Changes may it request, how are conflicts and invariants validated, and how does the one-Turn working projection become one atomic Turn Commit?

The resolution must eliminate raw shared-dictionary mutation and preserve the evidence ledger's single-writer and idempotency guarantees.

## Comments
