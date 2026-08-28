# 06 — Maths grammar slice

**What to build:** The complete maths-parse path: a `lark` grammar fills `MathParse`, and Assessment
grades the interpretation **when and only when** the grammar accepted it — so "three squared" parses to
`3^2` and is graded as `3^2`, not silently folded to "3 squared" and graded wrong. Ambiguous spoken maths
is refused into the repair screen rather than guessed.

**Blocked by:** 01, 05 (Assessment's interpretation-grading layers on the authorization precondition and
the repair path).

**Status:** ready-for-agent

- [ ] `lark` added to `requirements.txt`; grammar at `cloud_run_service/utterance_intake/grammar/`;
  Earley with `ambiguity='explicit'`; `len(CollapseAmbiguities(tree)) > 1` **is** the refusal predicate
  and the competing trees are the clarification material.
- [ ] v1 scope = what `math_grade` grades **plus exponents**; `PASSTHROUGH` is the common legitimate
  outcome (`span is None` a type invariant); only the two `REFUSE` outcomes set `doubtful`; no error
  screen for non-maths input. R1/R2 live here; R3/R4 do not.
- [ ] Assessment grades `MathParse.interpretation` **iff `ACCEPT`**, falls back to `math_grade` on
  `PASSTHROUGH`, never grades on `REFUSE` — does not breach the one-published-string rule.
- [ ] The four measured confident false negatives each become a correct parse **or** a refusal — never a
  silent wrong (fixtures assert this).
- [ ] Refusal rate measured over **claimed maths spans**, recorded against the 5%–15% band (calibration
  target, not a Stage-1 gate); hard per-utterance wall-clock cap → `PASSTHROUGH`; the grammar sits beside
  `math_grade.normalize`, not over it (retiring it is out of scope).
- [ ] Perf microbenchmark guards Earley blowup (p95 > 3× baseline fails, CI-only); baseline + dated
  record committed. Fixtures in the conformance suite; green in CI.
