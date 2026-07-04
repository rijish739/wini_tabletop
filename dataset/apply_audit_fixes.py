"""apply_audit_fixes.py
─────────────────────────────────────────────────────────────────────────────
Second-pass corrections for exemplar_dataset_10000_fixed.json, derived from the
external semantic audits (cats 1-3, 4-6, 7-9, last-100).

Every rule is gated on STUDENT UTTERANCE TEXT (see audit_fix_detectors.py) and
only proposes a change when the CURRENT action is one the audit flagged as a
contradiction for that pattern, so already-correct rows are left untouched and
the script is idempotent.

Usage:
  python dataset/apply_audit_fixes.py            # dry-run: per-rule counts + samples
  python dataset/apply_audit_fixes.py --apply    # write the corrected dataset + report
"""
from __future__ import annotations
import json
import sys
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import audit_fix_detectors as D

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "dataset" / "exemplar_dataset_10000_fixed.json"
BACKUP = ROOT / "dataset" / "exemplar_dataset_10000_fixed.backup_preaudit2.json"
REPORT = ROOT / "dataset" / "audit_fix_change_report.csv"
SUMMARY = ROOT / "dataset" / "audit_fix_summary.md"


# ── ACTION classifier: returns (new_action, rule_name) or (None, None) ──────
def propose_action(text: str, action: str):
    t = text.lower()

    # 1. Manipulative / hands-on request mis-routed to talk/test/reflect
    if D.is_manipulative_request(t) and action in {
            "EXPLAIN", "SOCRATIC_Q", "METACOGNITIVE_REFLECT", "QUIZ",
            "MISCONCEPTION_PROBE"}:
        return "REPRESENTATION_TRANSLATION", "manipulative->repr_translation"

    # 2. Visual translation (animation/moving/drawing) mis-routed to verbal/explain
    if D.is_visual_translation_request(t) and action in {"VERBAL_ANALOGY", "EXPLAIN"}:
        return "REPRESENTATION_TRANSLATION", "visual->repr_translation"

    # 3. Everyday / real-world analogy example mis-routed to worked-math/probe
    if D.is_everyday_example_request(t) and action in {
            "WORKED_EXAMPLE", "SOCRATIC_Q"}:
        return "ANALOGOUS_EXAMPLE", "everyday->analogous_example"

    # 4. Numeric worked-example request mis-routed to explain/probe
    if (D.is_numeric_example_request(t) and not D.is_everyday_example_request(t)
            and action in {"EXPLAIN", "SOCRATIC_Q"}):
        return "WORKED_EXAMPLE", "numeric_example->worked_example"

    # 4b. Big-picture / utility question routed to a visual/reflection action
    if D.is_utility_bigpicture(t) and action in {
            "REPRESENTATION_TRANSLATION", "METACOGNITIVE_REFLECT"}:
        return "EXPLAIN", "utility->explain"

    # 5. Pure overload / need-a-break / passing-intent → emotional support
    if (D.is_pure_overload(t) or D.is_passing_intent(t)) and action in {
            "EXPLAIN", "ISOMORPHIC_PRACTICE", "SOCRATIC_Q", "METACOGNITIVE_REFLECT"}:
        return "ENCOURAGE", "overload->encourage"

    # 6. Give-up / self-doubt → emotional support (prevent dropout).
    #    Skip when the row is really a factual syllabus question ("...in exam?").
    if (D.is_give_up_self_doubt(t) and not D.is_syllabus_exam_query(t)
            and action in {"EXPLAIN", "METACOGNITIVE_REFLECT", "ISOMORPHIC_PRACTICE",
                           "MISCONCEPTION_PROBE", "SOCRATIC_Q"}):
        return "ENCOURAGE", "giveup->encourage"

    # 6b. Confusion / simplification request met with Socratic probing → explain
    if (action == "SOCRATIC_Q"
            and (D.is_simplify_request(t) or D.has_explicit_dont_understand(t))
            and not D.is_give_up_self_doubt(t)
            and not D.is_manipulative_request(t)
            and not D.is_visual_translation_request(t)):
        return "EXPLAIN", "confusion->explain"

    # 7. Source / answer-key conflict → factual clarification
    if D.is_source_conflict(t) and action in {"MISCONCEPTION_PROBE"}:
        return "EXPLAIN", "source_conflict->explain"

    # 8. Syllabus / exam / grading factual query → factual answer.
    #    Skip affect-dominant rows (frustration/avoidance) that need ENCOURAGE.
    if (D.is_syllabus_exam_query(t) and not D.is_affect_dominant(t) and action in {
            "ENCOURAGE", "METACOGNITIVE_REFLECT", "MISCONCEPTION_PROBE"}):
        return "EXPLAIN", "syllabus->explain"

    # 9. Shortcut "just the steps, no why" → give the procedure
    if D.is_shortcut_steps(t) and action in {
            "SOCRATIC_Q", "METACOGNITIVE_REFLECT", "REQUEST_HINT"}:
        return "WORKED_EXAMPLE", "shortcut->worked_example"

    # 10. Prerequisite recap request → bridge back
    if D.is_prereq_recap_request(t) and action in {"SOCRATIC_Q", "REQUEST_HINT"}:
        return "BRIDGE_RECAP", "prereq->bridge_recap"

    # 11. Mastery-based advance request mis-routed to current-topic work/test
    if action in {"QUIZ", "EXPLAIN", "METACOGNITIVE_REFLECT", "SOCRATIC_Q"}:
        adv = D.is_advance_request(t)
        if adv == "transfer":
            return "TRANSFER_PROBLEM", "advance->transfer_problem"
        if adv == "next":
            return "RESUME_STATE", "advance->resume_state"

    # 12. Stuck / calculation-error student given active practice/test
    if D.is_stuck_calc_error(t) and action in {"ISOMORPHIC_PRACTICE", "QUIZ"}:
        return "REVIEW", "stuck->review"

    return None, None


# ── LABEL fixes: return (new_label_list, [ops]) ─────────────────────────────
def propose_labels(text: str, labels: list[str], new_action: str, rule_name):
    t = text.lower()
    lab = list(labels)
    ops = []

    def add(x):
        if x not in lab:
            lab.append(x); ops.append("+" + x)

    def drop(x):
        if x in lab:
            lab.remove(x); ops.append("-" + x)

    # self_correction noise: remove when no change-of-mind cue
    if "self_correction" in lab and not D.has_self_correction_cue(t):
        drop("self_correction")

    # physical label: ensure on manipulative requests; remove when hallucinated
    if D.is_manipulative_request(t):
        add("physical")
    elif "physical" in lab and not D.has_any_physical_cue(t):
        drop("physical")

    # high_confidence contradicting explicit confusion
    if "high_confidence" in lab and D.has_strong_confusion_cue(t):
        drop("high_confidence")

    # representation labels + drop verbal_analogy when we routed a visual request
    if rule_name == "visual->repr_translation":
        add("representation_shift"); add("request_representation")
        drop("verbal_analogy")

    # manipulative routing implies representation request
    if rule_name == "manipulative->repr_translation":
        add("representation_shift"); add("request_representation")

    # example_request label when we routed an example request
    if rule_name in {"everyday->analogous_example", "numeric_example->worked_example"}:
        add("example_request")

    # curiosity contradicts pure overload / give-up emotional states
    if rule_name in {"overload->encourage", "giveup->encourage"}:
        drop("curiosity")

    # big-picture utility wants a verbal explanation, not a visual representation
    if rule_name == "utility->explain":
        drop("representation_shift"); drop("request_representation")
        drop("verbal_analogy")

    # confusion label when student explicitly says they don't understand
    if D.has_explicit_dont_understand(t) and "confusion" not in lab:
        # don't add to clearly-positive states
        if not (D.is_advance_request(t)):
            add("confusion")

    return lab, ops


def main():
    apply = "--apply" in sys.argv
    data = json.loads(SRC.read_text(encoding="utf-8"))

    rule_counts = Counter()
    label_op_counts = Counter()
    action_transition = Counter()
    samples = defaultdict(list)
    changes = []  # (idx, cat, utt, old_action, new_action, rule, old_labels, new_labels)

    for idx, row in enumerate(data):
        utt = row["student_utterance"]
        old_action = row["target_policy_action"]
        old_labels = D.parse_labels(row["miniLM_labels"])

        new_action, rule = propose_action(utt, old_action)
        eff_action = new_action if new_action else old_action
        new_labels, ops = propose_labels(utt, old_labels, eff_action, rule)

        action_changed = new_action is not None and new_action != old_action
        labels_changed = set(new_labels) != set(old_labels)
        if not action_changed and not labels_changed:
            continue

        if action_changed:
            rule_counts[rule] += 1
            action_transition[f"{old_action} -> {new_action}"] += 1
            if len(samples[rule]) < 6:
                samples[rule].append(
                    f"cat{row['category']} {old_action}->{new_action} | {utt[:80]}")
        for o in ops:
            label_op_counts[o] += 1

        changes.append((idx, row["category"], utt, old_action, eff_action,
                        rule or "(labels-only)",
                        D.join_labels(old_labels), D.join_labels(new_labels)))

        if apply:
            row["target_policy_action"] = eff_action
            row["miniLM_labels"] = D.join_labels(new_labels)
            # validate vocab
            assert eff_action in D.VALID_ACTIONS, eff_action
            for l in new_labels:
                assert l in D.VALID_LABELS, l

    # ── report ──
    print("=" * 70)
    print(f"  {'APPLY' if apply else 'DRY-RUN'}: audit second-pass fixes")
    print("=" * 70)
    print(f"Rows total: {len(data)}   Rows changed: {len(changes)}")
    print(f"Action changes: {sum(rule_counts.values())}   "
          f"Label-only changes: {len(changes) - sum(rule_counts.values())}")
    print("\n-- action changes by rule --")
    for rule, c in rule_counts.most_common():
        print(f"  {rule:34s} {c:5d}")
    print("\n-- label operations --")
    for op, c in label_op_counts.most_common():
        print(f"  {op:28s} {c:5d}")
    print("\n-- action transitions --")
    for tr, c in action_transition.most_common():
        print(f"  {tr:42s} {c:5d}")
    if not apply:
        print("\n-- samples per rule --")
        for rule in rule_counts:
            print(f"\n[{rule}]")
            for s in samples[rule]:
                print("   " + s)

    if apply:
        shutil.copy2(SRC, BACKUP)
        SRC.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        import csv
        with REPORT.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["index", "category", "utterance", "old_action",
                        "new_action", "rule", "old_labels", "new_labels"])
            w.writerows(changes)
        # summary md
        lines = ["# Audit Second-Pass Fix Summary", "",
                 f"- Source/output: `exemplar_dataset_10000_fixed.json` (backup: `{BACKUP.name}`)",
                 f"- Rows total: {len(data)}",
                 f"- Rows changed: {len(changes)}",
                 f"- Action changes: {sum(rule_counts.values())}",
                 f"- Label-only changes: {len(changes) - sum(rule_counts.values())}",
                 "", "## Action changes by rule", ""]
        for rule, c in rule_counts.most_common():
            lines.append(f"- {rule}: {c}")
        lines += ["", "## Label operations", ""]
        for op, c in label_op_counts.most_common():
            lines.append(f"- `{op}`: {c}")
        lines += ["", "## Action transitions", ""]
        for tr, c in action_transition.most_common():
            lines.append(f"- {tr}: {c}")
        # new action distribution
        dist = Counter(r["target_policy_action"] for r in data)
        lines += ["", "## New target_policy_action distribution", ""]
        for a, c in dist.most_common():
            lines.append(f"- {a}: {c}")
        SUMMARY.write_text("\n".join(lines), encoding="utf-8")
        print(f"\nWrote: {SRC.name}, {BACKUP.name}, {REPORT.name}, {SUMMARY.name}")


if __name__ == "__main__":
    main()
