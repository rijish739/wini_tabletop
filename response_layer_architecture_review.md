# Response Layer Architecture — Review & Proposed Fixes

Companion to `response_layer_architecture_plan.md`. Each item states the **problem**
(edge case or architectural flaw the plan does not resolve) and a **proposed fix**
grounded in the system as it exists today (streaming brain, voice-first thin client,
Gemini planner/generator, probe-before-correct learner loop).

The core correction in the plan — a single canonical Teaching Script as the source of
instructional truth — is sound and directly addresses the speech/visual mismatch and the
"visuals must be text-aware" feedback. The fixes below are about making that idea
survive contact with streaming latency, adaptive pedagogy, and the constrained device.

---

## Part A — Critical flaws

### A1. The commit pipeline reverses Part 13 streaming, with no latency budget

**Problem.** The pipeline is a *commit* model (§6 steps 4–8, "Response Commit" §1.6):
plan the whole script → validate → compile all modalities → build package → then
execute. Part 13 spent significant effort taking TTFA from ~10–20 s to 3.3–4.4 s by
streaming speech as the first sentence lands. This design front-loads a structured LLM
planning call **plus** validation **plus** all-modality compilation before the first word
plays, and adds a likely **second serial Gemini call** (perception, then planner) where
generation used to be a single streamed call. §18 gestures at this but sets no target.

**Proposed fix.**
- **State a TTFA budget of ≤ 4 s (match Part 13) as a hard architectural constraint**, and
  treat any design that cannot meet it as failing, not "slightly slower."
- **Make the script stream beat-first, not whole-script-first.** The planner emits beats
  as a JSON *array*; the runtime consumes `beat[0]` (speech + visual decision) as soon as
  it is complete and begins compile → package → play, while later beats are still
  generating. A truncated stream then yields a usable *prefix* of valid beats, not invalid
  JSON.
- **Two-tier planning to protect the fast path.** The PDE-driven template selector
  produces the beat *spine* (structure + visual-gate decisions) with near-zero latency;
  Gemini fills `spoken_content` per beat, streamed. Reserve the full-LLM medium path for
  turns where no template fits.
- **Commit only the first beat, not the whole script.** "Response commit" = first beat
  validated and armed. Later beats may still validate/compile behind the playing audio.

### A2. Beat-level grounding proves *citation*, not *entailment*

**Problem.** `atomic_learning_claim` / `spoken_content` are the actual answer, so the
planner is still generating substantive content (§3.3's "LLMs plan, systems render" is
only half true). §3.4 requires each beat to cite `evidence_refs`, but the validator
(§5.3) checks that citations exist and schema is valid — not that the claim *matches* the
cited chunk. An LLM can cite a real evidence ID and still misstate it. The hallucination
surface is relocated, not removed.

**Proposed fix.**
- **Add a claim↔evidence consistency check to the validator**, tiered by cost:
  - *Deterministic cross-check where it is cheap and where hallucination hurts most:*
    formulas and numbers in a beat must appear in (or be derivable from) the cited chunk.
    Reuse the existing `formula_links.json` / `link_formulas.py` machinery.
  - *For factual/definitional beats:* constrain the planner to **paraphrase-bounded**
    claims — claim text must be grounded in a cited evidence span, not free-invented.
  - *Only for novel, uncached claims:* an optional lightweight NLI-style verification pass.
    Do not run it on cached/template scripts (latency/cost).
- Keep the existing manifest grounding as the floor; the new check is additive, mirroring
  the safety-gate philosophy ("the model may add recall, never remove the deterministic
  floor").

### A3. The beat model is linear, but the pedagogy is adaptive

**Problem.** A single Teaching Script is committed and validated up front, then beats
"advance" (§11). Yet §16 embeds assessment hooks *inside* beats. When a learner's answer
to an in-script probe should change the rest of the script (probe reveals misconception →
correct; not revealed → extend), the plan offers only *fallback* branching, never
*pedagogical* branching. This collides with the existing probe-before-correct, "state
moves only on evidence," inherently multi-turn loop, and risks pre-authoring a correction
as if the misconception were already confirmed.

**Proposed fix.**
- **Make the script a shallow, bounded branching DAG, not a linear list.** Assessment
  hooks carry `on_correct` / `on_incorrect` / `on_nonresponse` targets. Cap the branch
  factor and depth (e.g. one probe → at most 2 branches, one level deep) for *immediate*
  remediation/hint only.
- **Anything deeper terminates the script and hands the outcome to the existing
  multi-turn loop.** Within-turn branching = immediate hint/remediation; cross-turn
  adaptation stays in the PDE loop via `apply_probe_result` / `apply_bridge_result`.
- **Enforce probe-before-correct in the planner:** a probe beat may only *arm* a probe. It
  may not author the correction beat as reachable until the probe result confirms the
  misconception. The validator rejects scripts that "correct" an unconfirmed misconception.

### A4. Voice-first assessment and barge-in are unmodeled

**Problem.** §11/§13 lean on touch ("wait for touch or timeout") and local scoring, but
the primary input is the mic and the device has "no brain." A *spoken* answer inside a
beat needs STT → perception → grading — a full cloud round-trip — which the local
beat-completion model has no place for. And there is **no interruption/barge-in path** at
all, though kids talk over the robot and the live pipeline already runs VAD/endpointing.

**Proposed fix.**
- **Define two assessment execution modes on each hook:**
  - `local` — tap/MCQ/drag scored on-device against a rule; completes locally.
  - `spoken` — `completion_condition` = "await utterance → cloud grade → resume/branch."
    Model this explicitly as a **checkpoint that suspends the runtime and re-enters the
    cloud** (a mini-turn), not a locally-completed beat.
- **Add a barge-in contract to the Device Script Runner.** While speech plays, VAD listens;
  on detected speech it (1) ducks/pauses TTS, (2) emits an `interrupt` event with captured
  audio, (3) the cloud decides *answer the interjection (new turn)* vs *resume*. Each beat
  carries a `resumable` flag and a resume point.

---

## Part B — Edge cases and gaps

### B1. Non-teaching turns fall through the pipeline

**Problem.** The pipeline assumes every turn has concept + evidence + beats. "hi Wini",
"I'm bored", off-domain questions, and the scripted session-end farewell have no concept
and do not retrieve; the Context Adapter's "missing concept" failure mode would trip.

**Proposed fix.** Add a top-level `response_kind: instructional | social |
administrative` to the script. Social/farewell/off-domain get a minimal speech-only
script with **no concept/evidence requirement**; the Context Adapter enforces the full
grounding path only for `instructional`. Route `response_kind` from the existing intent
router.

### B2. Two writers to learner state → race / double-apply

**Problem.** §21 emits outcome events "asynchronously after response" into learner-state
APIs, while the existing loop applies state *synchronously*. With atomic-save +
active-test protection + frozen-test resume already in place, a second async writer
invites double-apply and ordering bugs. §5.7 lists "duplicate event delivery" but
designs no dedup.

**Proposed fix.** **Single-writer rule.** The Telemetry/Outcome Emitter never writes
learner state directly — it emits *events* that flow through the same synchronous
`apply_probe_result` / `apply_bridge_result` path, applied once at turn close. Every
assessment event carries an idempotency key (`script_id + beat_id + attempt`). Events
arriving during a frozen/active test are recorded but gated by the existing
active-test protection, not applied out of band.

### B3. Beat caps risk clamping answer length (a hard rule)

**Problem.** §24.3 sets `max beats per script`, and "beat = sentence." A beat cap clamps
answer length — explicitly forbidden ("answer length stays dynamic"). Native
atomic-beat generation may also read as choppier than the current streamed prose.

**Proposed fix.** **Beat count is a transport/packaging concern, never a content-length
limiter.** No hard beat cap on RPi. On ESP32, split a long script into *sequential
packages* (ship/stream package N+1 while N plays) rather than truncating — the answer
stays as long as pedagogy requires; only transport is chunked. State this explicitly in
§24.3.

### B4. The two-narration "solution" underestimates re-authoring cost

**Problem.** §1.5 demotes scene narration to metadata and makes script narration the sole
authority — but the tier-0 EXPLAIN path currently has the *scene replace the spoken
answer* for authored chapters (e.g. jemh104). Re-fitting every authored scene contradicts
"renderer remains unchanged."

**Proposed fix.** Add an `adaptation_contract` to authored scenes and tag each scene with
the claim it teaches. The planner may then either (a) use the scene as-is when its
narration matches the planned claim, or (b) use the scene **visual only** and override
narration from the script. Budget the re-authoring as an explicit roadmap phase between
Phase 2 and Phase 3, not a no-op.

### B5. The final-script cache almost never hits

**Problem.** §17.3 keys the instance cache on `learner_state_bucket` +
`evidence_manifest_hash`. The manifest hash varies per turn (near-zero hit rate) and
`learner_state_bucket` is undefined (risking serving one learner's script to a
meaningfully different one). The "fast path" it is meant to protect is undermined.

**Proposed fix.** Drop `evidence_manifest_hash` from the instance key; key on
`(concept_id, pedagogical_action, representation_target, learner_state_bucket,
device_class)`. Define `learner_state_bucket` as a coarse discretization of only the
dimensions that change teaching (mastery tier {low/med/high} × active-misconception
present/absent × grade). Rely on the **template cache** (§17.2) for the real latency win;
treat the instance cache as best-effort. Cache-safety rule: never serve a cached
instructional script that assumes a misconception resolved when the learner still has it
active/unconfirmed.

### B6. Structured-output token traps

**Problem.** Per the project's own gotchas: Gemini 2.5 Flash thinking-on can consume the
whole `max_output_tokens` budget → empty output with `finish_reason=MAX_TOKENS`; and
`response_schema` enums stop *invented* values, not *wrong-but-valid* ones. A large
multi-beat structured script is exactly the big-output case that truncates → invalid JSON
→ reject → regenerate → latency, with "regenerate once then speech-only" silently
degrading turns.

**Proposed fix.**
- Set `thinking_config=ThinkingConfig(thinking_budget=0)` on the planner call.
- Stream beats as an array so truncation yields a usable prefix (see A1).
- Bound beats-per-call; continue in a second call if more are needed rather than one giant
  output.
- Validator gains **enum-consistency rules** (e.g. `visual_type` must be compatible with
  `pedagogical_step`) to catch wrong-but-valid picks.
- Track `MAX_TOKENS` finish reasons and speech-only-degradation rate in telemetry.

### B7. Device Capability Profile has no handshake or versioning

**Problem.** The profile is treated as a static cloud-side reference. Real firmware drifts
(e.g. robot ears disabled by a firmware defect). Cloud-assumed capabilities → the planner
schedules primitives the device silently drops.

**Proposed fix.** The device **reports** its capabilities (including known quirks like
disabled ears) at session start via a handshake; the cloud caches the reported profile per
session and versions the schema. The planner reads the *reported* profile; any scheduled
primitive absent from it is dropped at compile time by the Modality Compiler, logged, and
never assumed executed.

### B8. Pedagogy-ownership boundary bleeds

**Problem.** §4.2 says the Response Layer does *not* own pedagogical policy selection, but
§5.2 gives the planner per-beat `pedagogical_step` plus the visual/interaction/assessment
decisions. Without a sharp line the planner and PDE can make conflicting moves.

**Proposed fix.** **PDE owns the macro action** (the turn's `pedagogical_action`); the
**planner owns micro choreography** (how to stage that action across beats) and may not
select a different action. Add a validator rule: every beat's `pedagogical_step` must be a
legal decomposition of the turn's `pedagogical_action` (maintain an allowed
step-sequence table per action).

### B9. Input safety is not mentioned

**Problem.** §20 is entirely output-focused. The existing near-total deterministic SAFETY
gate runs on the *learner's utterance* (self-harm detection). The Response Layer sits after
retrieval and is silent on it, risking the impression it moves or disappears.

**Proposed fix.** State explicitly in §4 (Boundaries) that the deterministic **input**
safety gate runs *before* the Response Layer, unchanged, on the learner utterance, and is
unaffected by this redesign. §20's content safety is additive, on output only.

### B10. Network drop mid-turn can strand the learner mid-sentence

**Problem.** §19's "complete cached beats if already available" fails when later beats
depend on cloud-produced TTS/script the device never received; the child is left
mid-explanation. Reconnect replay/idempotency is a listed failure mode but undesigned.

**Proposed fix.** Where feasible (RPi), package the **whole turn** in one deterministic
bundle so it completes offline once received. For ESP32 streamed packages, define a
**minimum coherent unit** = a full teaching *move* must be shipped before its speech
starts (never start a move you cannot finish). On drop mid-move: finish the cached move,
then show a graceful "let's pick this up in a moment" fallback rather than a mid-sentence
stop. Telemetry replay on reconnect uses the B2 idempotency keys.

---

## Part C — Three decisions to pin down before building

These gate whether the design layers onto the current live loop or forces a rewrite of it.

| # | Decision | Recommended resolution |
|---|---|---|
| C1 | **How does streaming coexist with commit, and what is the TTFA budget?** | ≤ 4 s TTFA; commit *first beat* only; stream beats as an array; template fast-path default (A1). |
| C2 | **Does an in-script assessment result branch the script or end the turn?** | Bounded within-turn branch (1 probe → ≤2 branches, 1 level) for immediate remediation; deeper adaptation ends the turn and re-enters the PDE loop (A3). |
| C3 | **What is the interruption / spoken-assessment path?** | Barge-in ducks TTS + emits `interrupt`; spoken assessment is an explicit cloud-checkpoint mini-turn, not a local beat completion (A4). |

## Summary

The plan's diagnosis and the script-as-single-source-of-truth principle are correct. The
risk is entirely in the execution model: as written it trades away streaming, assumes a
linear script where the pedagogy is adaptive, assumes touch/local assessment on a
voice-first no-brain device, and proves citation rather than entailment. The fixes above
keep the plan's principle while preserving streaming (beat-first commit), restoring
adaptivity (bounded branching + cross-turn handoff), honouring the voice-first thin client
(spoken-assessment checkpoints + barge-in), and closing the state-writeback, caching,
grounding, and safety gaps.
