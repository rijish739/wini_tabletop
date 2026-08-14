# Equivalence normalization rules

Normalization is deliberately limited to `result.answer` and
`compatibility.answer`:

1. Convert curly single/double quotation marks to their ASCII equivalents.
2. Collapse whitespace runs to one space and trim leading/trailing whitespace.

No word, sentence, token, or field is removed. In particular, the oracle never
normalizes numbers, operations, assessment questions/answers, evidence or idempotency
keys, State Changes, committed state, manifests/provenance, visual decisions,
Realization Receipts, stream ordering, failure signals, or degradation reasons.

Adding a rule requires a failing public-seam test that demonstrates a genuinely
nondeterministic presentation-only difference and a review showing that the rule
cannot hide state-affecting meaning.

