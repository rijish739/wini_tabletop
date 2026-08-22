# Assign exclusive semantic state ownership

Status: resolved
Type: grilling
Blocked by: 03

## Question

Which semantic state fields, structures, persistence adapters, and update boundaries belong exclusively to each Feature Module, and how does State and Persistence enforce transactional projection, single ownership, and atomic Turn Commit?

## Resolution

- Interaction Control owns session lifecycle, continuity, and topic state.
- Pedagogy owns mode, strategy, and test/practice progress.
- Assessment and Evidence exclusively owns item eligibility, pending assessment, and outcome evidence.
- State and Persistence validates scoped views, prevents cross-module field writes, and executes atomic Turn Commit.
