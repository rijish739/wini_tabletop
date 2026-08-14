# Canonical Turn caller and compatibility inventory

Canonical source: `cloud_run_service/tutor_loop.py::TutorLoop.turn` at commit
`772c0b6`. The root and `cloud_workspace_v8` copies are divergent duplicate runtimes,
not canonical callers; their disposition belongs to the duplicate-runtime work.

## Direct callers

| Caller | Invocation | Contract consumed |
|---|---|---|
| `WiniBrain.text_turn` in `wini_server.py` | Calls `turn(text, answer_budget, precomputed_analysis, precomputed_grade, stt_confidence, turn_id, learner_id)` under the per-learner lock. | Reads `answer`, `display`, `session_ended`, `action`, `action_reason`, `need`, `concept.concept_id`, `gen_backend`, `mode_reason`, `test`, `writeback.outcome`, `visual`, `signals`, `cognitive_update`, `pending_check`, `pending_hope`, `n_evidence`, `hope_update`, and `layer_latency_ms`. It also reads committed state for resolved mode/mastery and persists at the Turn boundary. |
| Canonical `tutor_loop.py` CLI | Calls `turn(text)` for `--once` and the interactive loop. | Requires `action`, `concept.concept_id`, `n_evidence`, and `answer`; optionally reads `shadow.action` and `session_ended`. `--once` serializes the entire dictionary. |
| Topic-shift re-entry inside `TutorLoop` | `_maybe_topic_shift` and `_consume_pending_shift` re-enter `turn(..., _allow_shift=False)`. | Returns the complete nested Turn result; generation accounting must remain one outer-Turn ledger. |
| `test_p0_evidence.py` characterization path | Constructs a minimal loop and calls a low-confidence Turn. | Requires `action == CONFIRM_LOW_CONFIDENCE` and byte-equivalent state preservation. Other tests statically enforce evidence/arming ownership around the Turn seam. |

## Indirect active callers

`wini_server.py` exposes the direct caller through three active contracts:

- `POST /turn`: JSON input (`text`, optional `speak`, `mode`, `turn_id`) and one final
  compatibility JSON object.
- `POST /stream_turn`: the same text input and an NDJSON stream.
- `POST /voice_turn`: PCM plus sample-rate/mode/turn headers, speculative perception
  and grading, then the same NDJSON stream and final compatibility object.

The active `wini_client/client.py` consumes `/turn` and `/voice_turn`. Its NDJSON
ordering contract is: optional `filler`; `turn_meta` before answer audio; `audio`
chunks in `seq` order; one untagged final result. An ended stream without that final
result is an error. The client consumes:

- `turn_meta`: `answer`, `display`, `visual` (including board payload/segments),
  `concept`, `mode`, `test`, and `writeback`;
- audio: `audio_b64`, `audio_rate`, and `seq`;
- final result: all compatibility fields plus `audio_streamed`, `audio_chunks`,
  `latency_ms`, optional `audio_b64`/`audio_rate`, and `stt_confidence`.

`ModeChannelSink` additionally uses full-result `mode`, `test`, `writeback.outcome`,
`display[0].kind`, and `concept` to select screens, feedback, progress, and headers.

## Canonical Turn dictionary

The full learning-path result contains:

`action`, `action_reason`, `need`, `shadow`, `concept`, `signals`,
`cognitive_update`, `n_evidence`, `bridge_ids`, `writeback`, `hope_update`,
`pending_check`, `pending_hope`, `layer_latency_ms`, `answer_budget`, `pace`,
`display`, `visual`, `mode`, `mode_reason`, `test`, `session_ended`, `gen_backend`,
and `answer`.

Early deterministic paths are structurally inconsistent today: low-confidence has
most fields, while the hint path omits several. The oracle preserves each path's exact
serialization rather than filling absent fields in candidate captures.

## Server compatibility serialization

`WiniBrain.text_turn` maps a Turn to:

`turn_id`, `transcript`, `answer`, `display`, `session_ended`, `action`, `need`,
`concept`, `gen_backend`, `mode`, `test`, slim `writeback`, `visual`, `diagnostics`,
and `latency_ms`; it conditionally adds streaming/audio fields. `diagnostics` carries
the action reason, mode reason, mastery, signals, numeric cognitive updates,
assessment/HOPE status, evidence count, writeback outcome, and visual decision.

## State and side-effect observations

- Learner/Session State after the Turn is authoritative only after persistence at the
  caller's Turn boundary.
- Evidence is append-only and identified by idempotency key; a non-attempt must not
  append evidence or clear a valid pending assessment.
- Assessment arming/voiding is compared independently from answer text.
- `learning_log.jsonl` and redacted safety alerts are externally inspectable audit
  effects, but learner utterances and credentials are never copied into fixtures.
- `display` and `visual` are intended presentation; the oracle separately records the
  Realization Receipt and stream order so intended output cannot masquerade as delivery.

