"""Phase 2.5 authored-scene adaptation contracts."""
from __future__ import annotations
import argparse
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NARRATION_AS_AUTHORED = "as_authored"
NARRATION_VISUAL_ONLY = "visual_only"
NARRATION_SCRIPT_OVERRIDE = "script_override"
NARRATION_MODES = frozenset((NARRATION_AS_AUTHORED, NARRATION_VISUAL_ONLY, NARRATION_SCRIPT_OVERRIDE))
SCHEMA_VERSION = 1
_ROOT = Path(__file__).resolve().parent.parent
_SPEC_DIR = _ROOT / "rag_store" / "figure_specs"

@dataclass(frozen=True)
class SceneReview:
    ok: bool
    issues: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    beat_to_claims: dict[str, tuple[str, ...]] = field(default_factory=dict)
    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": list(self.issues), "claim_ids": list(self.claim_ids),
                "beat_to_claims": {k: list(v) for k, v in self.beat_to_claims.items()}}

def review_scene(scene: dict[str, Any] | None) -> SceneReview:
    scene = scene or {}
    beats = scene.get("beats")
    if not isinstance(beats, list) or not beats:
        return SceneReview(False, ("scene has no beats",))
    contract = scene.get("adaptation_contract")
    if not isinstance(contract, dict):
        return SceneReview(False, ("missing adaptation_contract",))
    issues: list[str] = []
    if contract.get("schema_version") != SCHEMA_VERSION:
        issues.append("unsupported adaptation_contract schema_version")
    modes = contract.get("allowed_narration_modes")
    if not isinstance(modes, list) or not NARRATION_MODES.issubset(set(modes)):
        issues.append("contract must declare all narration modes")
    elif not set(modes).issubset(NARRATION_MODES):
        issues.append("contract contains an unknown narration mode")
    if contract.get("default_live_narration_mode") != NARRATION_SCRIPT_OVERRIDE:
        issues.append("live narration must be script_override")
    claims = contract.get("claims")
    claim_ids: set[str] = set()
    if not isinstance(claims, list) or not claims:
        issues.append("missing visual claim catalog")
    else:
        for claim in claims:
            if not isinstance(claim, dict) or not str(claim.get("claim_id") or "").strip():
                issues.append("claim catalog has a blank claim_id")
                continue
            claim_id = str(claim["claim_id"])
            if claim_id in claim_ids:
                issues.append("claim catalog has a duplicate claim_id")
            claim_ids.add(claim_id)
            if not str(claim.get("claim") or "").strip():
                issues.append("every visual claim needs claim text")
    mapping = contract.get("beat_to_claims")
    mapped: dict[str, tuple[str, ...]] = {}
    if not isinstance(mapping, dict):
        issues.append("missing beat_to_claims mapping")
    else:
        for index, beat in enumerate(beats):
            tags = mapping.get(str(index))
            if not isinstance(tags, list) or not tags:
                issues.append(f"beat {index} has no claim mapping")
                continue
            tags_tuple = tuple(str(tag) for tag in tags)
            if set(tags_tuple) - claim_ids:
                issues.append(f"beat {index} references an unknown claim")
            if list(beat.get("claim_tags") or []) != list(tags_tuple):
                issues.append(f"beat {index} claim_tags do not match beat_to_claims")
            mapped[str(index)] = tags_tuple
        if set(mapping) - {str(i) for i in range(len(beats))}:
            issues.append("mapping contains an unknown beat index")
    return SceneReview(not issues, tuple(issues), tuple(sorted(claim_ids)), mapped)

def scene_for_narration_mode(scene: dict[str, Any], mode: str,
                             script_spoken_by_beat: dict[str, str] | None = None) -> dict[str, Any]:
    review = review_scene(scene)
    if not review.ok:
        raise ValueError("scene failed adaptation review: " + "; ".join(review.issues))
    if mode not in NARRATION_MODES:
        raise ValueError(f"unknown narration mode: {mode}")
    if mode not in scene["adaptation_contract"]["allowed_narration_modes"]:
        raise ValueError(f"scene does not allow narration mode: {mode}")
    adapted = copy.deepcopy(scene)
    adapted["runtime_narration_mode"] = mode
    if mode == NARRATION_AS_AUTHORED:
        return adapted
    for index, beat in enumerate(adapted["beats"]):
        beat["narration"] = (str((script_spoken_by_beat or {}).get(str(index), ""))
                             if mode == NARRATION_SCRIPT_OVERRIDE else "")
    return adapted

def _claim_text(beat: dict[str, Any], index: int) -> str:
    labels = [str(item.get("text")).strip() for item in beat.get("in", [])
              if isinstance(item, dict) and item.get("t") == "label"
              and str(item.get("text") or "").strip()]
    if labels:
        return "Visual step: " + " | ".join(labels[:2])
    narration = str(beat.get("narration") or "").strip()
    return narration or f"Visual progression step {index + 1}"

def add_contract(scene: dict[str, Any]) -> bool:
    beats = scene.get("beats")
    if not isinstance(beats, list) or not beats:
        return False
    concept_tag = f"concept:{scene.get('concept_id') or 'unknown'}"
    claims: list[dict[str, Any]] = []
    mapping: dict[str, list[str]] = {}
    changed = False
    for index, beat in enumerate(beats):
        claim_id = f"visual_step_{index + 1}"
        tags = [claim_id]
        if beat.get("claim_tags") != tags:
            beat["claim_tags"] = tags
            changed = True
        claims.append({"claim_id": claim_id, "claim": _claim_text(beat, index),
                       "tags": ["visual", f"beat:{index}", concept_tag]})
        mapping[str(index)] = tags
    contract = {
        "schema_version": SCHEMA_VERSION,
        "allowed_narration_modes": sorted(NARRATION_MODES),
        "default_live_narration_mode": NARRATION_SCRIPT_OVERRIDE,
        "claims": claims,
        "beat_to_claims": mapping,
        "review": {"status": "approved", "reviewed_by": "response_layer_phase_2_5",
                   "note": "Live speech is owned by the Teaching Script; authored narration is demo-only."},
    }
    if scene.get("adaptation_contract") != contract:
        scene["adaptation_contract"] = contract
        changed = True
    return changed

def review_authored_scenes(spec_dir: Path = _SPEC_DIR, write: bool = False) -> dict[str, SceneReview]:
    results: dict[str, SceneReview] = {}
    for path in sorted(spec_dir.glob("*.scene.json")):
        scene = json.loads(path.read_text(encoding="utf-8"))
        if write and add_contract(scene):
            path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results[str(path)] = review_scene(scene)
    return results

def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/upgrade Phase-2.5 scene contracts.")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    results = review_authored_scenes(write=args.write)
    failed = [(path, result) for path, result in results.items() if not result.ok]
    for path, result in results.items():
        detail = "" if result.ok else ": " + "; ".join(result.issues)
        print(f"{'PASS' if result.ok else 'FAIL'} {Path(path).name}{detail}")
    return 1 if failed else 0

if __name__ == "__main__":
    raise SystemExit(main())

