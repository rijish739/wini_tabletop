"""Phase 6 of RAG_upgrade_plan.md — HOPE dataset bootstrap (closes G10 = report §5.6 step 1).

Builds the curated KI / KT / CT prompt bank straight from the enriched store, then
runs the A2.3 teacher-calibration protocol BEFORE any scaling:

  bank     one LLM call per concept -> exactly 3 KI + 3 KT + 3 CT prompts grounded
           in the card's integration_links / transfer_links / ct_probes, plus one
           deterministic bridge prompt per grade-9 diagnostic (cold-start /
           persistence signals). Rows: prompt, concept_id, signal, difficulty,
           bloom_level, rubric_anchor, figure_id? — the exact shape report §5.4
           ordinal labels attach to. Target >= 1,000 rows, >= 300 per signal.
  rubric   writes hope_rubric.md — the written 0-3 ordinal rubric per signal,
           forcing the three mandatory discriminations: memorized recall vs
           representation translation (KI), surface analogy vs structural
           transfer (KT), curiosity vs genuine critical evaluation (CT).
  sample   stratified ~300-prompt gold sample (signal x difficulty band).
  answers  4 synthetic student answers per sampled prompt at weak / memorized /
           partial / strong levels (report §5.6 step 2).
  label    two INDEPENDENT raters score every answer 0-3 on the prompt's signal,
           blind to the answer's intended level (answers shuffled per prompt):
           rater A = gemini-2.5-flash strict rubric grader; rater B =
           gemini-2.5-pro experienced-teacher persona. NOTE: the plan calls for
           1 human teacher in one of these slots — rater B is the pluggable stand-in
           and should be replaced by teacher labels before production scaling.
  kappa    Cohen's kappa per signal (gate: >= 0.6), disagreement resolution
           (|A-B| >= 2 flagged for expert review), and the memorized-vs-strong
           discrimination check (separated by >= 1 ordinal on >= 85% of prompts;
           failing prompts are flagged rewrite_or_drop in the bank).
  write    hope_prompt_bank.jsonl + hope_gold_set.jsonl + hope_bank_review_sample.md
           (30 random prompts for the human spot-check) into the store.

All LLM results cached in rag_store/hope_cache.jsonl (resumable).
Env: GOOGLE_GENAI_USE_VERTEXAI=True, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION=global.
"""

from __future__ import annotations
import argparse
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tqdm import tqdm

from rag_core import GEN_MODEL, make_client

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RATER_A_MODEL = GEN_MODEL            # gemini-2.5-flash
RATER_B_MODEL = "gemini-2.5-pro"     # independent second rater (pluggable teacher slot)
SIGNALS = ["KI", "KT", "CT"]
BLOOM = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
ANSWER_LEVELS = ["weak", "memorized", "partial", "strong"]
GOLD_TARGET = 300
KAPPA_GATE = 0.6
DISCRIMINATION_GATE = 0.85


class Cache:
    def __init__(self, path: Path):
        self.path = path
        self.mem: Dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.mem[rec["key"]] = rec["data"]

    def get(self, key):
        return self.mem.get(key)

    def put(self, key, data):
        self.mem[key] = data
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "data": data}, ensure_ascii=False) + "\n")


CALL_HARD_TIMEOUT_S = 240  # wall-clock cap per LLM call, enforced outside the SDK


def call_json(client, prompt, model=GEN_MODEL, retries=2):
    """JSON-mode call with a HARD wall-clock timeout.

    SDK-level HttpOptions timeouts proved unreliable (two multi-hour stalls on a
    single dead connection), so the call runs in a worker thread and is abandoned
    after CALL_HARD_TIMEOUT_S — the timeout counts as a failure and triggers the
    normal retry with a fresh request.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    def _do():
        resp = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"))
        return json.loads(resp.text or "{}")

    last = None
    for _ in range(retries + 1):
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            return pool.submit(_do).result(timeout=CALL_HARD_TIMEOUT_S)
        except FutTimeout:
            last = f"hard timeout after {CALL_HARD_TIMEOUT_S}s"
        except Exception as e:  # noqa: BLE001
            last = e
        finally:
            pool.shutdown(wait=False)
    raise RuntimeError(f"LLM call failed after retries ({model}): {last}")


def make_timeout_client() -> genai.Client:
    return genai.Client()


# ---------------------------------------------------------------------------
# Rubric (written, versioned — the labeling contract for ALL raters)
# ---------------------------------------------------------------------------
RUBRIC = """# HOPE labeling rubric v1 ({today})

Score every student answer 0-3 on the prompt's signal. Score ONLY the signal asked for.

## KI — Knowledge Integration (representation translation)
The discrimination that matters: **memorized recall is NOT integration.** An answer that
recites a correct definition or formula without moving between representations caps at 1.
- 0: wrong or no engagement with the concept.
- 1: correct recall in a single representation (verbal definition, bare formula) — even if
  fluent and exam-perfect. Memorized != integrated.
- 2: partial translation between representations (starts linking symbolic <-> graphical /
  tabular / verbal but incomplete, or one direction only).
- 3: full, correct translation across the asked representations, with the connection made
  explicit (e.g. "the discriminant being negative MEANS the parabola never meets the x-axis").

## KT — Knowledge Transfer
The discrimination that matters: **surface analogy is NOT structural transfer.** Matching
contexts by keywords ("both mention speed") caps at 1.
- 0: wrong or refuses the transfer.
- 1: surface analogy — names the target context, reuses vocabulary, but the mathematical
  structure is not carried over (or is carried over wrongly).
- 2: partial structural transfer — the right structure is identified but applied incompletely
  or with errors in the new domain.
- 3: full structural transfer — the underlying mathematical structure is explicitly mapped
  onto the new situation and used correctly.

## CT — Critical Thinking
The discrimination that matters: **curiosity is NOT evaluation.** Asking "but what if...?"
without analyzing caps at 1.
- 0: wrong or accepts the claim uncritically.
- 1: shows curiosity or doubt ("that seems off") without justification; or restates the
  edge case without analyzing it.
- 2: partially correct evaluation — identifies the flaw / edge case and starts a
  justification, but the argument is incomplete or has gaps.
- 3: correct, justified evaluation — finds the counterexample / boundary condition and
  explains WHY it breaks or holds, in mathematically sound terms.

## bridge — prior-knowledge recall (scored on the KT scale: recall applied to the new chapter)

General rules for raters:
- Judge mathematical correctness for NCERT Class 9-10 scope only.
- Length is not quality; a short, exact answer can be a 3.
- If the answer is correct but answers a different question, cap at 1.
"""


# ---------------------------------------------------------------------------
# Stage: bank
# ---------------------------------------------------------------------------
def bank_prompt(card: dict, figures: List[dict]) -> str:
    ki_src = json.dumps(card.get("integration_links") or [], ensure_ascii=False)
    kt_src = json.dumps(card.get("transfer_links") or [], ensure_ascii=False)
    ct_src = json.dumps(card.get("ct_probes") or [], ensure_ascii=False)
    figs = json.dumps(figures, ensure_ascii=False)
    return f"""You are writing assessment prompts for the HOPE learning-quality metrics of a Class 10
Maths tutoring system. Generate prompts for ONE concept, grounded ONLY in the supplied
enrichment data (NCERT Class 9-10 scope; invent nothing beyond it). Return STRICT JSON:
{{"prompts": [
  {{"signal": "KI"|"KT"|"CT",
    "prompt": "<the task posed to the student>",
    "difficulty": <integer 1-9, near the concept difficulty {card.get('difficulty', 5)}>,
    "bloom_level": one of {BLOOM},
    "rubric_anchor": "<one line: what a level-3 answer must demonstrate>",
    "figure_id": "<id from AVAILABLE FIGURES if the prompt asks the student to read that
                   exact figure, else null>"}}
]}}
Produce EXACTLY 3 KI + 3 KT + 3 CT prompts (9 total):
- KI prompts = representation-translation tasks built from the integration links (ask the
  student to move between the named representation pair; reference a figure when one fits).
- KT prompts = transfer tasks built from the transfer links (near links: apply the structure
  to the linked concept; far links: to the real-world domain; the link's note is the anchor).
- CT prompts = edge-case / counterexample / why tasks built from the ct_probes (rephrase as
  student-facing tasks; the expected_insight is the anchor).
A prompt must be answerable WITHOUT seeing this JSON — self-contained student-facing text.

CONCEPT: {card['name']} — {card.get('summary', '')}
INTEGRATION LINKS (KI source): {ki_src}
TRANSFER LINKS (KT source): {kt_src}
CT PROBES (CT source): {ct_src}
AVAILABLE FIGURES: {figs}
"""


def validate_bank(payload: Any, cid: str, valid_figs: set) -> Tuple[List[dict], List[str]]:
    errors, out = [], []
    items = payload.get("prompts") if isinstance(payload, dict) else payload
    for p in items if isinstance(items, list) else []:
        if not isinstance(p, dict):
            continue
        sig = p.get("signal")
        if sig not in SIGNALS:
            errors.append(f"bad signal {sig!r}")
            continue
        if not p.get("prompt") or not p.get("rubric_anchor"):
            errors.append(f"{sig}: missing prompt/rubric_anchor")
            continue
        try:
            diff = max(1, min(9, int(p.get("difficulty"))))
        except (TypeError, ValueError):
            diff = 5
        fig = p.get("figure_id")
        if fig and fig not in valid_figs:
            fig = None
        out.append({"signal": sig, "prompt": str(p["prompt"]), "difficulty": diff,
                    "bloom_level": p.get("bloom_level") if p.get("bloom_level") in BLOOM else "apply",
                    "rubric_anchor": str(p["rubric_anchor"]), "figure_id": fig,
                    "concept_id": cid})
    counts = Counter(p["signal"] for p in out)
    for sig in SIGNALS:
        if counts[sig] < 3:
            errors.append(f"need 3 {sig} prompts, got {counts[sig]}")
    return out, errors


def run_bank(client, cache: Cache, concepts: List[dict], G: nx.DiGraph, limit=None) -> List[dict]:
    todo = [c for c in concepts if cache.get(f"bank::{c['concept_id']}") is None]
    if limit:
        todo = todo[:limit]
    print(f"[bank] {len(concepts)} concepts, {len(todo)} to generate")
    for card in tqdm(todo, desc="prompt bank"):
        cid = card["concept_id"]
        figures = []
        if cid in G:
            for f in G.successors(cid):
                fa = G.nodes[f]
                if fa.get("image_path") and fa.get("type") in ("figure", "table"):
                    figures.append({"figure_id": f, "label": fa.get("label", ""),
                                    "alt_text": (fa.get("alt_text") or "")[:150]})
        valid_figs = {f["figure_id"] for f in figures}
        payload = call_json(client, bank_prompt(card, figures[:5]))
        rows, errors = validate_bank(payload, cid, valid_figs)
        if errors:
            payload = call_json(client, bank_prompt(card, figures[:5])
                                + "\nPREVIOUS ATTEMPT ERRORS:\n" + "\n".join(errors))
            rows2, errors2 = validate_bank(payload, cid, valid_figs)
            if len(rows2) >= len(rows):
                rows = rows2
        cache.put(f"bank::{cid}", rows)

    bank: List[dict] = []
    for c in concepts:
        rows = cache.get(f"bank::{c['concept_id']}") or []
        for k, r in enumerate(rows):
            r = dict(r)
            r["prompt_id"] = f"hope::{c['concept_id']}::{r['signal']}::{k}"
            bank.append(r)
    # bridge prompts: deterministic from the grade-9 diagnostics (cold-start signals)
    for n, a in G.nodes(data=True):
        if a.get("type") == "grade9_concept" and a.get("diagnostic_question"):
            targets = [v for _, v in G.out_edges(n) if G.nodes[v].get("type") == "concept"]
            bank.append({"prompt_id": f"hope::{n}::bridge::0",
                         "signal": "bridge", "prompt": a["diagnostic_question"],
                         "difficulty": 3, "bloom_level": "remember",
                         "rubric_anchor": f"Recalls the Class-9 idea correctly: {a.get('expected_answer','')}",
                         "figure_id": None, "concept_id": targets[0] if targets else n,
                         "grade9_id": n})
    print(f"[bank] {len(bank)} rows; per signal: {dict(Counter(r['signal'] for r in bank))}")
    return bank


# ---------------------------------------------------------------------------
# Stage: sample + answers
# ---------------------------------------------------------------------------
def diff_band(d: int) -> str:
    return "low" if d <= 3 else ("mid" if d <= 6 else "high")


def stratified_sample(bank: List[dict], target: int) -> List[dict]:
    strata: Dict[tuple, List[dict]] = defaultdict(list)
    for r in bank:
        strata[(r["signal"], diff_band(r["difficulty"]))].append(r)
    rng = random.Random(42)
    out = []
    per = max(1, target // len(strata))
    for key in sorted(strata):
        rows = strata[key]
        rng.shuffle(rows)
        out.extend(rows[:per])
    rng.shuffle(out)
    return out[:max(target, len(strata))]


def run_answers(client, cache: Cache, gold_prompts: List[dict], batch_size=4):
    todo = [p for p in gold_prompts if cache.get(f"answers::{p['prompt_id']}") is None]
    print(f"[answers] {len(gold_prompts)} gold prompts, {len(todo)} need synthetic answers")
    for start in tqdm(range(0, len(todo), batch_size), desc="synthetic answers"):
        batch = todo[start:start + batch_size]
        items = [{"prompt_id": p["prompt_id"], "prompt": p["prompt"], "signal": p["signal"]}
                 for p in batch]
        prompt = f"""For EACH assessment prompt below, write 4 synthetic Class-10 student answers at
exactly these levels (report definitions):
- "weak": confused or mathematically wrong.
- "memorized": fluent, exam-style recall of the right definition/formula — sounds correct —
  but NO representation translation / NO structural transfer / NO genuine evaluation
  (whatever the signal asks for). This is the answer of a student who memorized the textbook.
- "partial": on the right track with real understanding but incomplete or with one error.
- "strong": full correct answer demonstrating exactly what the signal asks
  (KI: explicit representation translation; KT: explicit structural mapping; CT: justified
  evaluation/counterexample; bridge: correct recall applied to the question).
Answers must differ in SUBSTANCE, not length or politeness. 2-5 sentences each.
Return STRICT JSON: {{"items": [{{"prompt_id": "<copy>", "answers": {{"weak": "...",
"memorized": "...", "partial": "...", "strong": "..."}}}}]}}

Prompts:
{json.dumps(items, ensure_ascii=False, indent=1)}
"""
        try:
            payload = call_json(client, prompt)
        except RuntimeError as e:
            print(f"  answers batch failed: {e}")
            continue
        raw = payload if isinstance(payload, list) else (payload.get("items") or [])
        got = {o.get("prompt_id"): o for o in raw if isinstance(o, dict)}
        for p in batch:
            o = got.get(p["prompt_id"])
            ans = (o or {}).get("answers") or {}
            if all(isinstance(ans.get(l), str) and ans[l].strip() for l in ANSWER_LEVELS):
                cache.put(f"answers::{p['prompt_id']}", {l: ans[l] for l in ANSWER_LEVELS})


# ---------------------------------------------------------------------------
# Stage: label (two independent raters, blind to intended level)
# ---------------------------------------------------------------------------
RATER_PERSONAS = {
    "A": ("strict rubric grader for a learning-science lab; apply the rubric mechanically "
          "and conservatively — when in doubt between two scores, give the lower one"),
    "B": ("experienced Class 10 mathematics teacher with 15 years of grading experience; "
          "apply the rubric with professional judgment about what real students mean"),
}


def shuffled_answers(prompt_id: str, answers: Dict[str, str]) -> List[Tuple[str, str]]:
    """Deterministic per-prompt shuffle so raters never see the level order."""
    rng = random.Random(prompt_id)
    pairs = list(answers.items())
    rng.shuffle(pairs)
    return pairs


def run_label(client, cache: Cache, gold_prompts: List[dict], rater: str, model: str,
              batch_size=3):
    todo = [p for p in gold_prompts
            if cache.get(f"answers::{p['prompt_id']}") is not None
            and cache.get(f"label{rater}::{p['prompt_id']}") is None]
    print(f"[label {rater}] {len(todo)} prompts to label with {model}")
    for start in tqdm(range(0, len(todo), batch_size), desc=f"rater {rater}"):
        batch = todo[start:start + batch_size]
        items = []
        order_maps = {}
        for p in batch:
            answers = cache.get(f"answers::{p['prompt_id']}")
            pairs = shuffled_answers(p["prompt_id"], answers)
            order_maps[p["prompt_id"]] = [lvl for lvl, _ in pairs]
            items.append({"prompt_id": p["prompt_id"], "signal": p["signal"],
                          "prompt": p["prompt"], "rubric_anchor": p["rubric_anchor"],
                          "answers": [txt for _, txt in pairs]})
        prompt = f"""You are a {RATER_PERSONAS[rater]}.

Label each student answer 0-3 on the prompt's signal using THIS rubric, nothing else:

{RUBRIC.format(today=date.today().isoformat())}

Return STRICT JSON: {{"items": [{{"prompt_id": "<copy>", "scores": [s1, s2, s3, s4]}}]}}
where scores[k] is the 0-3 label of answers[k], in the given order.

Items:
{json.dumps(items, ensure_ascii=False, indent=1)}
"""
        try:
            payload = call_json(client, prompt, model=model)
        except RuntimeError as e:
            print(f"  label batch failed: {e}")
            continue
        raw = payload if isinstance(payload, list) else (payload.get("items") or [])
        got = {o.get("prompt_id"): o for o in raw if isinstance(o, dict)}
        for p in batch:
            o = got.get(p["prompt_id"])
            scores = (o or {}).get("scores")
            if not (isinstance(scores, list) and len(scores) == 4):
                continue
            try:
                scores = [max(0, min(3, int(s))) for s in scores]
            except (TypeError, ValueError):
                continue
            by_level = {lvl: scores[i] for i, lvl in enumerate(order_maps[p["prompt_id"]])}
            cache.put(f"label{rater}::{p['prompt_id']}", by_level)


# ---------------------------------------------------------------------------
# Stage: kappa + discrimination
# ---------------------------------------------------------------------------
def cohen_kappa(a: List[int], b: List[int]) -> float:
    assert len(a) == len(b) and a
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = 0.0
    for c in range(4):
        pe += (a.count(c) / n) * (b.count(c) / n)
    return (po - pe) / (1 - pe) if pe < 1.0 else 1.0


def run_kappa(cache: Cache, gold_prompts: List[dict]):
    per_signal_a: Dict[str, List[int]] = defaultdict(list)
    per_signal_b: Dict[str, List[int]] = defaultdict(list)
    gold_rows, flagged, discrim_ok, discrim_n = [], 0, 0, 0
    for p in gold_prompts:
        pid = p["prompt_id"]
        answers = cache.get(f"answers::{pid}")
        la, lb = cache.get(f"labelA::{pid}"), cache.get(f"labelB::{pid}")
        if not (answers and la and lb):
            continue
        sig = p["signal"] if p["signal"] in SIGNALS else "KT"  # bridge scored on KT scale
        finals = {}
        for lvl in ANSWER_LEVELS:
            a, b = la[lvl], lb[lvl]
            per_signal_a[sig].append(a)
            per_signal_b[sig].append(b)
            needs_expert = abs(a - b) >= 2
            flagged += int(needs_expert)
            finals[lvl] = round((a + b) / 2)
            gold_rows.append({"prompt_id": pid, "signal": p["signal"], "prompt": p["prompt"],
                              "answer_level": lvl, "answer_text": answers[lvl],
                              "rater_a": a, "rater_b": b, "final_label": finals[lvl],
                              "needs_expert_review": needs_expert,
                              "rubric_anchor": p["rubric_anchor"]})
        discrim_n += 1
        discrim_ok += int(finals["strong"] - finals["memorized"] >= 1)
        p["discriminates"] = finals["strong"] - finals["memorized"] >= 1

    kappas = {sig: cohen_kappa(per_signal_a[sig], per_signal_b[sig])
              for sig in per_signal_a if per_signal_a[sig]}
    discrim_rate = discrim_ok / discrim_n if discrim_n else 0.0
    return gold_rows, kappas, discrim_rate, flagged


# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--limit", type=int, default=None, help="Concept cap for smoke tests.")
    ap.add_argument("--gold", type=int, default=GOLD_TARGET)
    ap.add_argument("--skip-calibration", action="store_true",
                    help="Bank generation only (no gold set / kappa).")
    args = ap.parse_args()

    store = Path(args.store)
    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    G = nx.node_link_graph(json.loads((store / "graph.json").read_text(encoding="utf-8")))
    cache = Cache(store / "hope_cache.jsonl")
    client = make_timeout_client()

    (store / "hope_rubric.md").write_text(RUBRIC.format(today=date.today().isoformat()),
                                          encoding="utf-8")

    bank = run_bank(client, cache, concepts[:args.limit] if args.limit else concepts, G,
                    limit=args.limit)

    gold_rows, kappas, discrim_rate, flagged = [], {}, 0.0, 0
    if not args.skip_calibration:
        gold_prompts = stratified_sample(bank, args.gold)
        print(f"[sample] {len(gold_prompts)} gold prompts "
              f"({dict(Counter(p['signal'] for p in gold_prompts))})")
        run_answers(client, cache, gold_prompts)
        run_label(client, cache, gold_prompts, "A", RATER_A_MODEL)
        run_label(client, cache, gold_prompts, "B", RATER_B_MODEL)
        gold_rows, kappas, discrim_rate, flagged = run_kappa(cache, gold_prompts)

        # prompts that fail to discriminate memorized vs strong are flagged in the bank
        bad = {p["prompt_id"] for p in gold_prompts if p.get("discriminates") is False}
        for r in bank:
            if r["prompt_id"] in bad:
                r["status"] = "rewrite_or_drop"

    (store / "hope_prompt_bank.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in bank), encoding="utf-8")
    if gold_rows:
        (store / "hope_gold_set.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in gold_rows), encoding="utf-8")

    # 30-prompt human review sample (plan verify)
    rng = random.Random(7)
    sample = rng.sample(bank, min(30, len(bank)))
    lines = ["# HOPE bank — 30-prompt human review sample\n"]
    for r in sample:
        lines += [f"## {r['prompt_id']}",
                  f"*signal:* {r['signal']}  |  *difficulty:* {r['difficulty']}  |  "
                  f"*bloom:* {r['bloom_level']}  |  *figure:* {r.get('figure_id')}",
                  f"\n**Prompt:** {r['prompt']}",
                  f"\n**Rubric anchor:** {r['rubric_anchor']}\n"]
    (store / "hope_bank_review_sample.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n=== Phase 6 summary ===")
    print(f"bank rows: {len(bank)}  per signal: {dict(Counter(r['signal'] for r in bank))}")
    if kappas:
        print(f"gold set: {len(gold_rows)} labeled answers; {flagged} flagged for expert review")
        for sig, k in sorted(kappas.items()):
            gate = "PASS" if k >= KAPPA_GATE else "FAIL"
            print(f"  kappa[{sig}] = {k:.3f}  ({gate}, gate >= {KAPPA_GATE})")
        gate = "PASS" if discrim_rate >= DISCRIMINATION_GATE else "FAIL"
        print(f"  memorized-vs-strong separated on {discrim_rate:.1%} of gold prompts "
              f"({gate}, gate >= {DISCRIMINATION_GATE:.0%})")
        if all(k >= KAPPA_GATE for k in kappas.values()) and discrim_rate >= DISCRIMINATION_GATE:
            print("KAPPA GATE PASSED — scaling beyond the seed bank is unlocked "
                  "(replace rater B with human teacher labels before production).")
        else:
            print("KAPPA GATE NOT PASSED — do NOT scale; resolve disagreements / amend rubric.")


if __name__ == "__main__":
    main()
