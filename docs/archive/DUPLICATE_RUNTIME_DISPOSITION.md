# Duplicate runtime disposition

Status: reviewed with the two-axis repository review workflow; findings and their
resolution are recorded below. No runtime behavior was copied or deleted by this
disposition.

Inventory snapshot: repository commit `2c1f86a`, 2026-08-14. The canonical behavioral
source is `cloud_run_service/`. The duplicate runtime is `cloud_workspace_v8/` plus
the root-level brain files that mirror it. Device clients, authored data sources, and
build/evaluation tools at the repository root are outside the duplicate runtime even
when an old workspace happens to contain another copy of them.

## Decision

Delete `cloud_workspace_v8/` only after the gates in this document pass. Do not merge
its divergent runtime code into `cloud_run_service/`: the canonical versions win.
Keep active root commands temporarily, but reduce brain entrypoints to thin adapters
that import or execute the canonical implementation. Keep device/client code and
source/provenance assets outside the runtime. Migrate only tests that protect a current
production contract. Remove generated, cached, and explicitly experimental artifacts.

This is a disposition, not authorization to perform those migrations or deletions in
this ticket.

## Evidence and scope

The inventory used tracked paths (`git ls-files`) and byte comparisons, not filenames
alone:

| Observation | Result | Meaning |
|---|---:|---|
| Files under `cloud_workspace_v8/` | 1,435 | Complete deletion scope |
| Workspace paths with a tracked root counterpart | 1,415 | The workspace is primarily a second copy of root material |
| Byte-identical workspace/root files | 1,404 | No migration is needed from the workspace copy |
| Divergent workspace/root files | 11 | Must be resolved explicitly; listed below |
| Workspace-only files | 20 | Must be resolved explicitly; listed below |
| Workspace paths also present in `cloud_run_service/` | 109 | 82 identical, 27 divergent |
| Workspace paths absent from `cloud_run_service/` | 1,326 | Mostly source/provenance data and generated visual assets, not missing runtime behavior |

`DUPLICATE_RUNTIME_DISPOSITION.csv` is the normative item-level inventory. It has
1,435 rows covering every tracked workspace path and its corresponding root path, plus
1,123 rows for root-only callers/artifacts and every tracked file in the active client,
delivery, and platform packages. Every row records both physical
dispositions, the item class, whether the canonical path is byte-identical, divergent,
or absent, the corresponding canonical capability (or an explicit statement that no
runtime equivalent is required), one exact retained destination, and evidence required
before deletion. The Markdown tables summarize that manifest; they do not replace it.

The active Cloud Run image is self-contained under `cloud_run_service/`: its Dockerfile
copies that directory and the canonical tree contains the 10 model files, curated
dataset, and 25 immutable RAG/runtime assets shared with the workspace. The root and
workspace Dockerfiles are byte-identical copies. Repository deployment notes and
`cloud_run_service/baseline_oracle/CALLER_INVENTORY.md` identify the canonical server
and Turn contract. Device launchers still name root `wini_server.py`, which is why root
compatibility cannot be removed at the same time as the experimental tree.

Reproduce the tracked-file counts with:

```powershell
(git ls-files cloud_workspace_v8 | Measure-Object).Count
git diff --no-index -- cloud_workspace_v8/tutor_loop.py cloud_run_service/tutor_loop.py
git diff --no-index -- cloud_workspace_v8/wini_server.py cloud_run_service/wini_server.py
rg -n "cloud_workspace_v8|cloud_run_service" .
rg -n "from tutor_loop|import tutor_loop|TutorLoop\(" --glob "*.py" .
```

## Exhaustive workspace disposition

The following precedence rules classify every one of the 1,435 tracked workspace
files exactly once. A later rule applies only if an earlier rule did not. The CSV
expands these rules to one row per path and independently disposes the root counterpart,
so the root half of the duplicate is not inferred from workspace disposition.

### 1. Discard canonical-present copies (109 files)

Every workspace path that also exists under `cloud_run_service/` is discarded with
the duplicate tree. There are 82 byte-identical copies. For the following 27 divergent
paths, retain the canonical file without merging workspace behavior:

```text
learner_state.py
llm_vertex.py
query.py
state_backend.py
tutor_loop.py
wini_server.py
cognitive_analyzer/analyzer.py
cognitive_classifier/cues.py
perception/gates.py
perception/gemini_perception.py
perception/route.py
rag_store/learning_log.jsonl
response_layer/__init__.py
response_layer/adapter.py
response_layer/board_buddy_author.py
response_layer/board_buddy_caps.py
response_layer/board_buddy_orchestrator.py
response_layer/compilers.py
response_layer/contracts.py
response_layer/outcomes.py
response_layer/scene_author.py
response_layer/test_board_buddy.py
response_layer/test_response_layer.py
response_layer/test_runner_outcomes.py
response_layer/validator.py
response_layer/visual_gate.py
voice/cloud_stt.py
```

The workspace `learning_log.jsonl` is learner/audit output, not source. It must not be
merged. Preserve production logs according to the operational retention policy before
tree deletion; repository copies are not the production system of record.

### 2. Adapt active compatibility entrypoints (6 files)

These canonical-missing workspace files have active root equivalents. Discard the
workspace copies only after the root equivalents have become thin entrypoints:

```text
run_wini_package.sh
stop_wini_package.sh
Wini.desktop
voice_cloud_tutor.py
voice_hybrid_runner.py
wini_ui_server.py
```

The adapters may perform argument/environment translation, process launch, transport,
and compatibility serialization. They may not contain prompts, policy, state mutation,
retrieval, grading, assessment, generation, or presentation selection.

### 3. Migrate current contract tests (5 files)

Move the valuable cases to the canonical seam, then discard the workspace copies:

```text
cognitive_analyzer/test_analyzer.py
perception/test_perception.py
response_layer/test_board_buddy_author_live.py
smoke_test_phase5.py
test_session_modes.py
```

The live Board Buddy test becomes part of the bounded, separately invoked live-smoke
suite; normal tests remain offline and non-billed. Perception front-door and session
mode cases should target the canonical Turn/coordinator interface, not import private
root feature helpers. Existing equivalent canonical tests need not be duplicated.

### 4. Discard obsolete/generated items (8 files)

```text
.pytest_cache/CACHEDIR.TAG
.pytest_cache/v/cache/lastfailed
.pytest_cache/v/cache/nodeids
dataset/_pipeline_test_report.json
dataset/_pipeline_test_sent_frame.png
dataset/_pipeline_test_utterances.json
voice/board_output.png
voice_latency_spike.py
```

The first seven are cache/probe output. `voice_latency_spike.py` declares itself a
throwaway experiment and has no runtime caller. Any useful latency scenario belongs in
the canonical performance harness rather than retaining this implementation.

### 5. Archive the remaining canonical-missing items outside the runtime (1,307 files)

All canonical-missing files not named in rules 2-4 are archived outside the runtime;
their workspace copies are discarded after the manifest's destination checksum and
archive/consumer evidence is recorded. If an identical tracked root file exists, that
exact root path is the destination. If it does not, the CSV names an exact path under
`docs/archive/duplicate-runtime/`. This rule covers:

- authored/build inputs and generators (`dataset/`, `build_*.py`, `figures/`, model
  builders, curation/audit scripts, `crop_figures.py`, `enrich_concepts.py`, and
  `link_formulas.py`);
- source and provenance artifacts such as the fixed dataset, audit reports, prompt
  banks, scorecards, page summaries, and architectural notes;
- 923 generated figure-crop files and 276 page images used as device/offline source
  assets, not as canonical brain behavior;
- local/device utilities (`touch_*`, `check_touch.py`, `deploy_to_pi.py`,
  `wini_pipeline.launch.py`, `Wini-Letters.desktop`, `parent_dashboard.py`, and
  `progress_report.py`);
- store verification/evaluation tools (`verify_store.py`, `eval_phase01.py`) and their
  source data;
- voice/device support modules absent from the cloud image; and
- the remaining workspace-only plans and notes.

The count is the residual of the complete inventory:
`1,435 - 109 - 6 - 5 - 8 = 1,307`. “Archive” means the item is not copied into
`cloud_run_service/`; where an identical tracked root file already exists, that root
file is the retained copy. A later ticket may deliberately revise a destination through
review, but this disposition's recorded destination remains the deletion gate until
that reviewed revision exists.

## Canonical capability mapping

The manifest makes the capability decision per item rather than assuming equivalence
from a filename:

- `byte_identical` means the canonical file has the same SHA-256 content and is the
  corresponding capability;
- `divergent` means the canonical same-path implementation is authoritative and the
  workspace behavior is explicitly rejected, with canonical tests/oracle evidence
  required before removal;
- compatibility entrypoints map to the canonical Turn façade or HTTP/NDJSON contract,
  even when no same-path canonical launcher exists;
- migrated tests map to a named canonical test destination and Module/Turn seam; and
- canonical-absent source, tool, asset, documentation, cache, and experiment rows state
  either that no canonical runtime equivalent is required or that the item is obsolete.

This mapping distinguishes “capability exists” from “same relative path exists.”

## Workspace-only and divergent-to-root audit

The precedence rules above cover all 20 workspace-only paths. They are: three pytest
cache files; four Board Buddy plans/notes; three pipeline probe outputs; the frozen
split provenance file; `rag_store/safety_alerts.jsonl`; seven Board Buddy
implementation/test/render files; and `voice/board_output.png`. The canonical tree
already has the frozen split, safety log shape, and five of the seven runtime/test
Board Buddy counterparts; only `render_board_payloads.py` and the live author test
lack canonical counterparts, so they fall under archive and migrate respectively.

The 11 workspace/root divergences are:

```text
run_wini_package.sh
tutor_loop.py
wini_server.py
perception/gates.py
perception/gemini_perception.py
rag_store/learning_log.jsonl
response_layer/__init__.py
response_layer/compilers.py
response_layer/device_profile.py
response_layer/device_runner.py
voice/cloud_stt.py
```

For `tutor_loop.py`, `wini_server.py`, and all feature modules, the canonical version
wins and the root entrypoint becomes an adapter where required. Root
`run_wini_package.sh` is identical to the device delivery copy in
`pi_client_package/`; preserve that operational contract while removing its ability to
select a second brain implementation. Logs are retained operationally, not merged.

The root inventory is exhaustive within the duplicate-runtime boundary: every one of
the 1,415 tracked root paths that mirrors the workspace has its own `root_disposition`
in the CSV, including 11 divergent files. The 20 workspace-only paths are marked
`not_present` at root. Root files outside that mirrored set enter scope when they call,
launch, deploy, probe, or package the brain. The manifest adds exact rows for the five
root-only Turn/visual probes, `tools/rl_integration_check.py`, every named HTTP, STT,
diagnostic, and latency probe, both deployment/sync tools, all six tracked root ZIP
artifacts, the platform supervisor/launcher, and every tracked file in `wini_client/`,
`pi_client_package/`, and `wini_platform/`. The three active Jetson launch scripts are
also individual rows. No brace or glob row stands in for several items. Other
repository packages are not tutor-runtime implementations or callers and therefore are
outside this deletion boundary.

## Active requirements versus experiments and artifacts

| Class | Items | Disposition |
|---|---|---|
| Production brain | `cloud_run_service/Dockerfile`, `wini_server.py`, `tutor_loop.py`, canonical runtime packages/assets | Remain the only behavioral source |
| Active device consumer | `wini_client/client.py`, `ModeChannelSink`, Board/scene players | Remain outside the brain; verify HTTP/NDJSON compatibility |
| Device launch/lifecycle | root and `pi_client_package` launcher, desktop, stop script | Keep as thin operational entrypoints; do not embed a brain copy |
| Manual development callers | root tutor CLI, voice runners, Flask UI | Keep thin compatibility entrypoints until their documented callers migrate |
| Scripted HTTP probes | `run_live_5_turns.py`, `test_turns.py`, `_dump_turn.py`, `_test_live_turn.py`, relevant `tools/` probes | Remain clients of the canonical HTTP service; they are not runtime implementations |
| Build/eval/source assets | dataset/model/RAG builders, authored files, scorecards, parent reporting | Keep outside the runtime or artifact storage; do not promote into canonical behavior |
| Device visual assets | root/package figure crops, page images, scene assets | Keep with device/artifact delivery; canonical brain retains only indexes/specs it reads |
| Experiments/generated output | latency spike, pytest cache, probe screenshots/results, workspace logs | Discard after any required operational log retention |

No evidence was found for an active deployment that requires
`cloud_workspace_v8/Dockerfile`, its ignore files, or its requirements file. They are
identical to the canonical build files and are obsolete deployment paths.

## Root compatibility contracts

These are the root entrypoints with an active or documented caller. “Retain” means the
contract survives through a thin adapter, not that the root implementation survives.

| Root entrypoint | Evidence of caller | Compatibility to retain | Required disposition evidence |
|---|---|---|---|
| `wini_server.py` | device launch scripts, onboarding/runbook commands, and `wini_client` | Server startup flags (`--port`/`PORT`), health endpoint, `POST /turn`, `/stream_turn`, `/voice_turn`; JSON fields and NDJSON order documented in `baseline_oracle/CALLER_INVENTORY.md` | All launchers resolve to canonical server; HTTP contract/oracle and device smoke pass; adapter contains no feature policy |
| `tutor_loop.py` | server, README/onboarding CLI, voice/UI tools, characterization tests | `TutorLoop` construction; `turn(text, answer_budget, precomputed_analysis, precomputed_grade, stt_confidence, turn_id, learner_id)`; `--once`, interactive CLI, full dictionary serialization | Import/CLI tests resolve to canonical coordinator/façade; baseline oracle passes; private-helper imports have migrated |
| `run_wini_package.sh` + `Wini.desktop` | desktop launcher and device runbook; same root script is shipped in `pi_client_package` | Environment/brain URL selection, single-instance process lifecycle, client/display/touch startup, log locations, exit behavior | Thin-client launch smoke passes against canonical service; no root brain process or module is selected |
| `stop_wini_package.sh` | launcher/UI close path and alphabet-game handoff | Stop client/UI processes, release audio/touch resources, restore touch service | Device lifecycle smoke passes without killing unrelated processes |
| `voice_cloud_tutor.py` | cloud voice status guide and manual mic test | Existing CLI flags, STT -> Turn -> TTS behavior, termination semantics | Runner imports/calls canonical façade; bounded voice smoke passes |
| `voice_hybrid_runner.py` | README, architecture guide, Windows dev/test rig | Existing text/push-to-talk/auto/live flags, sentence streaming callback, display and TTS timing | Runner uses canonical façade or HTTP client; offline fake-voice and bounded live smoke pass |
| `wini_ui_server.py` | documented dev/test UI | Flask routes, Turn JSON passthrough, store asset serving | UI calls canonical façade/service; route smoke passes; no global feature implementation remains |

`rules_decide`, `qwen_chat`, `ROOT`, and other feature helpers currently imported by
old tests/runners are not public compatibility contracts. Migrate those consumers to a
deep canonical seam or an injected port instead of exporting feature policy from a root
adapter.

Root `Dockerfile`, `.dockerignore`, `.gcloudignore`, and `requirements-cloud.txt` are
not compatibility entrypoints. Update every build/deploy command to use
`cloud_run_service/`, then remove the root copies with the duplicate behavior. Root
build tools, parent reporting, device packages, and source assets remain outside the
brain and do not need a runtime adapter.

## Review record

The staged disposition was reviewed on 2026-08-14 against commit `2c1f86a` using the
repository's required two-axis review:

| Axis | Reviewer | Result |
|---|---|---|
| Standards | independent `standards_review` agent | No findings; the documentation-only change does not trigger the four-document lockstep rule and changes no behavior/schema |
| Spec | independent `spec_review` agent | Initial four findings were corrected; final re-review found no remaining findings and mechanically verified all 2,558 unique manifest rows |

All four spec findings were accepted. They were resolved by adding the item-level CSV
with root dispositions, exact retained destinations and per-item evidence; adding the
capability mapping above; enumerating root-only/external callers; and adding this review
record. The corrected staged diff was submitted to the same spec reviewer for closure.
The final re-review closed the Spec axis with no remaining findings; the Standards
re-review also remained clear.

## Migration and deletion gates

Deletion of `cloud_workspace_v8/` is allowed only when one reviewed evidence bundle
shows all of the following:

1. Canonical unit, architecture, baseline-oracle, and full offline suites pass.
2. The five retained test groups above run at canonical seams; billed tests are
   segregated into the bounded live-smoke suite.
3. Root server and Tutor CLI resolution tests prove imports/execution reach
   `cloud_run_service/` and root adapters contain no feature implementation.
4. Device HTTP/NDJSON scenarios prove `turn_meta` precedes ordered audio and exactly
   one final result, including termination and degraded presentation.
5. Launcher lifecycle smoke proves the device starts/stops against the canonical brain
   without spawning a root or workspace Tutor implementation.
6. Cloud build/deploy configuration names `cloud_run_service/`; no command or CI path
   names `cloud_workspace_v8/` or the root Docker context.
7. The 10 model files, curated dataset, 25 immutable RAG assets, figure-spec index, and
   any device visual artifact manifest are checksummed at their reviewed destinations.
8. Production learner state, evidence, safety alerts, and logs have an explicit owner
   and retention/export record; repository log copies are not merged as state.
9. `rg` finds no active import, launcher, deployment, documentation command, or test
   that resolves behavioral code from `cloud_workspace_v8/` or root feature modules.
10. A deletion diff contains the workspace tree and obsolete root behavior/build
    copies only; device/client packages, source assets, and approved thin adapters are
    still present.

The later consolidation ticket owns these mutations and the final deletion. This
ticket establishes what that review must prove.
