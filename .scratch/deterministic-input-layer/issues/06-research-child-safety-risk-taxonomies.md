# Research: child-safety risk taxonomies for input-side routing

Status: done
Type: research
Blocked by: —

Findings: `docs/architecture/CHILD_SAFETY_RISK_TAXONOMIES_RESEARCH.md`. Ticket 07 owns the taxonomy decision.

## Question

Docx §14 requires splitting the single broad SAFETY route into six: **personal data,
ordinary distress, harassment/threat, abuse/violence, imminent danger, and uncertain-STT
safety** — "each needs different language and case handling." What established taxonomies
exist, and which distinctions are actually detectable deterministically from one utterance?

Today `perception/gates.py:81-93` `classify_safety` returns a 2-tuple: tier 3
`urgent_danger`, tier 2 `protected_disclosure`, tier 2 `safety_concern`. Three outcomes,
two tiers, one regex per tier.

Research targets (high-trust primary sources only):

- UNICEF *Policy guidance on AI for children* v2.0 (docx source [1]) — the child-centred
  requirement set the spec leans on.
- WHO / War Trauma Foundation / World Vision, *Psychological first aid: Guide for field
  workers* (source [5]) — what "listening without forcing the person to talk" implies for a
  first-response classifier, and what it forbids.
- Established safeguarding risk taxonomies used by child helplines and online-safety
  regulators — how they carve self-harm vs. abuse-disclosure vs. peer harassment vs.
  imminent danger, and what evidence each tier requires.
- Published work on self-harm / crisis text classification: what recall is achievable
  lexically, where lexicons systematically fail (indirect disclosure, code-switching,
  euphemism, negation, third-person framing).
- India-specific: Tele-MANAS and ERSS 112 (sources [6][7]) — what a tier actually has to
  carry for a hand-off to be actionable.

Deliverable: a Markdown findings file in the repo, capturing (a) a candidate six-way
taxonomy with a one-line detectability verdict per route, (b) the known failure modes of
lexical detection with citations, and (c) what each route needs to carry downstream.

Do **not** decide the taxonomy here — ticket 07 owns that. This ticket gathers the evidence.

Note for the researcher: CLAUDE.md records that the existing lexicon measured **0.75 recall**
and missed gerunds ("ending my life" vs "end my life") and oblique phrasings, and that recall
must be measured directly with `python -m eval.perception_eval --gates`, never inferred.
