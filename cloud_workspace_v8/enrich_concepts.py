"""Phase 1 of RAG_upgrade_plan.md — concept-card + misconception + schema + hint enrichment.

Closes gaps G1 (KT transfer links), G2 (KI integration links), G3 (CT probes +
misconception enrichment), G4 (concept difficulty), G5 (applications), G6
(vocabulary), plus reviewer points A1.1/A1.3 (problem schemas + isomorphic
variables), A1.2 (3-step hint chains), A1.4 (metacognitive prompts).

Same cache pattern as pedagogy_enrich.py: every LLM result is appended to
rag_store/concept_enrich_cache.jsonl keyed by stage::id, so a crashed or
re-run is resumable and never re-bills a finished call.

Stages (all run by default, each skippable with --only):
  repair   deterministic graph fix: vision-era edges use un-prefixed concept ids
           (e.g. `quadratic_coefficients`); re-point to `<doc>__<id>` when the
           target node's doc resolves it. No LLM. Required for schema clustering
           ("grouped via existing has_example/has_exercise edges") to see anything.
  concepts one JSON call per concept -> difficulty, transfer_links,
           integration_links, ct_probes, applications, vocabulary,
           metacognitive_prompts (after_success / after_struggle).
  misconceptions  batched (~30/call) -> why_wrong, correct_idea,
           diagnostic_question, expected_answer on all misconception nodes.
  schemas  one call per concept with instances -> problem_schema nodes with
           method_steps, instance_ids, isomorphic_variables, trap_steps.
  hints    batched (~25/call) -> hint_chain (exactly 3, no answer leak) on every
           exercise node and every misconception diagnostic.
  write    apply everything to concepts.json + graph.json (additive; .bak backups).

Validation (plan Phase 1 step 3, hard): any transfer/integration target not in
the 108-id list is rejected; one retry with the errors fed back, then the bad
items are dropped and logged to rag_store/concept_enrich_issues.log.

Env (plan §6 risk 4): GOOGLE_GENAI_USE_VERTEXAI=True, GOOGLE_CLOUD_PROJECT,
GOOGLE_CLOUD_LOCATION=global.
"""

from __future__ import annotations
import argparse
import json
import re
import shutil
import statistics
import sys
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

ANSWER_LEAK_RE = re.compile(r"\b(the\s+)?(final\s+)?answer\s*(is|=|:)", re.IGNORECASE)
PROBE_KINDS = {"edge_case", "why", "counterexample"}
HINT_KINDS = ["conceptual_nudge", "method_recall", "partial_first_step"]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class Cache:
    """Append-only JSONL cache: {"key": "<stage>::<id>", "data": {...}}."""

    def __init__(self, path: Path):
        self.path = path
        self.mem: Dict[str, Any] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.mem[rec["key"]] = rec["data"]

    def get(self, key: str):
        return self.mem.get(key)

    def put(self, key: str, data: Any):
        self.mem[key] = data
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "data": data}, ensure_ascii=False) + "\n")


class IssueLog:
    def __init__(self, path: Path):
        self.path = path

    def log(self, where: str, msg: str):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(f"[{where}] {msg}\n")


def call_json(client: genai.Client, prompt: str, retries: int = 2) -> Any:
    """One JSON-mode generation call with transient-error retry."""
    last = None
    for _ in range(retries + 1):
        try:
            resp = client.models.generate_content(
                model=GEN_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return json.loads(resp.text or "{}")
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"LLM call failed after retries: {last}")


# ---------------------------------------------------------------------------
# Store loading + deterministic edge repair
# ---------------------------------------------------------------------------
def load_store(store: Path):
    chunks = [json.loads(l) for l in (store / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    concepts = json.loads((store / "concepts.json").read_text(encoding="utf-8"))
    graph = nx.node_link_graph(json.loads((store / "graph.json").read_text(encoding="utf-8")))
    return chunks, concepts, graph


def doc_of_node(node_id: str) -> Optional[str]:
    parts = node_id.split("::")
    return parts[1] if len(parts) >= 3 else None


def repair_dangling_edges(G: nx.DiGraph, valid_ids: set, issues: IssueLog) -> int:
    """Re-point vision-era edges whose source is an un-prefixed concept id.

    `<doc>__<source>` must exist in the 108-id list, where doc comes from the
    target node's own id (e.g. example::jemh102::...). Cross-doc references stay
    untouched — Phase 3's dangling-prereq resolution (G7) owns those, along with
    prerequisite_of edges.
    """
    moves = []
    for u, v, d in G.edges(data=True):
        if G.nodes[u] or u in valid_ids:          # attributed node: not dangling
            continue
        if d.get("relation") == "prerequisite_of":  # Phase 3 territory
            continue
        doc = doc_of_node(v)
        cand = f"{doc}__{u}" if doc else None
        if cand in valid_ids:
            moves.append((u, v, dict(d), cand))
    for u, v, d, cand in moves:
        G.remove_edge(u, v)
        d["repaired_from"] = u
        G.add_edge(cand, v, **d)
    if moves:
        issues.log("repair", f"re-pointed {len(moves)} dangling-source edges to doc-prefixed concept ids")
    return len(moves)


# ---------------------------------------------------------------------------
# Per-concept context gathering
# ---------------------------------------------------------------------------
def concept_context(G: nx.DiGraph, chunks: List[dict], card: dict) -> dict:
    cid = card["concept_id"]
    own_chunks = sorted(
        (c for c in chunks if cid in (c.get("concept_ids") or [])),
        key=lambda c: (c.get("concept_scores") or {}).get(cid, 0.0),
        reverse=True,
    )
    neighbors: Dict[str, list] = {"formula": [], "example": [], "exercise": [], "misconception": [], "application": []}
    if cid in G:
        for nbr in G.successors(cid):
            t = G.nodes[nbr].get("type")
            if t in neighbors:
                neighbors[t].append((nbr, G.nodes[nbr]))

    diffs = [c["difficulty"] for c in own_chunks if c.get("difficulty") is not None]
    diffs += [a.get("difficulty") for _, a in neighbors["exercise"] if a.get("difficulty") is not None]
    anchor = statistics.median(diffs) if diffs else 5

    return {"own_chunks": own_chunks, "neighbors": neighbors, "difficulty_anchor": anchor}


# ---------------------------------------------------------------------------
# Stage: concept enrichment
# ---------------------------------------------------------------------------
CONCEPT_FIELDS_SPEC = """{
  "difficulty": <integer 1-9, anchored near the supplied median difficulty of this concept's own material>,
  "transfer_links": [
    {"target": "<concept_id from the VALID ID LIST>", "transfer_type": "near", "note": "<why the idea transfers>"},
    ... at least 2 near links (cross-chapter allowed and encouraged),
    {"target": "<real-world or Science domain, free text>", "target_chapter": "<domain/chapter name>", "transfer_type": "far", "note": "<the structural bridge>"},
    ... at least 1 far link
  ],
  "integration_links": [
    {"concept_id": "<concept_id from the VALID ID LIST>", "representation_pair": "<rep1<->rep2 e.g. symbolic<->graphical>", "note": "<what combining/translating them teaches>"}
    ... at least 1
  ],
  "ct_probes": [
    {"kind": "edge_case"|"why"|"counterexample", "question": "<probing question>", "expected_insight": "<one rubric line: the insight a strong answer shows>"}
    ... 2-3 total, at least one of kind "counterexample"
  ],
  "applications": [
    {"text": "<application of the concept>", "domain": "<target domain>", "transfer_type": "near"|"far"}
    ... at least 1; dedupe/normalize the supplied application nodes, add grounded ones from the chunks if none supplied
  ],
  "vocabulary": ["<key term>", ...  chapter key terms a learner must know for this concept],
  "metacognitive_prompts": [
    {"when": "after_success", "prompt": "<post-solve self-explanation prompt>"},
    {"when": "after_struggle", "prompt": "<reflection prompt for a learner who exhausted hints or failed twice>"}
  ]
}"""


def concept_prompt(card: dict, ctx: dict, valid_ids: List[str], feedback: str = "") -> str:
    chunk_txt = "\n".join(f"- (difficulty {c.get('difficulty','?')}, role {c.get('pedagogical_role','?')}) "
                          f"{(c.get('text') or '')[:600]}" for c in ctx["own_chunks"][:8])
    formulas = "\n".join(f"- {a.get('formula','')[:150]}" for _, a in ctx["neighbors"]["formula"][:10])
    miscs = "\n".join(f"- {a.get('text','')[:200]}" for _, a in ctx["neighbors"]["misconception"][:8])
    apps = "\n".join(f"- {a.get('text','')[:250]} (domain: {a.get('target_domain','')})"
                     for _, a in ctx["neighbors"]["application"][:8])
    fb = f"\nYOUR PREVIOUS ATTEMPT HAD ERRORS — fix them this time:\n{feedback}\n" if feedback else ""
    return f"""You are enriching one concept card of an NCERT Class 10 Mathematics knowledge graph
for a pedagogy-first tutoring system. Ground EVERYTHING in the supplied material; invent nothing
outside NCERT Class 9-10 scope. Return STRICT JSON with exactly this shape:

{CONCEPT_FIELDS_SPEC}

Hard rules:
- Every "near" transfer target and every integration_links concept_id MUST be copied exactly
  from the VALID ID LIST below (never this concept's own id: {card['concept_id']}).
- difficulty must stay within +/-2 of the supplied median anchor unless the material clearly says otherwise.
- representation_pair sides must come from: symbolic, verbal, graphical, diagrammatic, tabular, algebraic.
- ct_probes must be answerable from Class 10 knowledge; expected_insight is a grader's rubric line.
- metacognitive prompts: exactly one "after_success" and one "after_struggle"; they ask the learner
  to self-explain, not to re-solve.
{fb}
CONCEPT CARD:
{json.dumps({k: card[k] for k in ('concept_id', 'name', 'summary', 'aliases', 'prerequisites', 'representations', 'misconceptions') if k in card}, ensure_ascii=False)}

MEDIAN DIFFICULTY ANCHOR of this concept's own chunks/exercises: {ctx['difficulty_anchor']}

THIS CONCEPT'S TEXTBOOK CHUNKS:
{chunk_txt or '(none)'}

LINKED FORMULAS:
{formulas or '(none)'}

KNOWN MISCONCEPTIONS:
{miscs or '(none)'}

APPLICATION NODES TO PROMOTE (dedupe/normalize):
{apps or '(none — derive 1-2 from the chunks)'}

VALID ID LIST (the only legal near-transfer / integration targets):
{json.dumps(valid_ids)}
"""


def validate_concept_payload(payload: Any, cid: str, valid_ids: set) -> Tuple[dict, List[str]]:
    errors: List[str] = []
    clean: Dict[str, Any] = {}
    if not isinstance(payload, dict):
        return {}, ["payload is not a JSON object"]

    try:
        d = int(payload.get("difficulty"))
        clean["difficulty"] = max(1, min(9, d))
    except (TypeError, ValueError):
        errors.append("difficulty missing or not an integer 1-9")

    near, far = [], []
    for t in payload.get("transfer_links") or []:
        if not isinstance(t, dict):
            continue
        tt = t.get("transfer_type")
        if tt == "near":
            tgt = t.get("target") or t.get("target_concept_id")
            if tgt in valid_ids and tgt != cid:
                near.append({"target": tgt, "transfer_type": "near", "note": str(t.get("note", ""))})
            else:
                errors.append(f"near transfer target {tgt!r} is not in the valid id list")
        elif tt == "far":
            if t.get("target"):
                far.append({"target": str(t["target"]), "target_chapter": str(t.get("target_chapter", "")),
                            "transfer_type": "far", "note": str(t.get("note", ""))})
    if len(near) < 2:
        errors.append(f"need >=2 valid near transfer links, got {len(near)}")
    if len(far) < 1:
        errors.append(f"need >=1 far transfer link, got {len(far)}")
    clean["transfer_links"] = near + far

    integ = []
    for l in payload.get("integration_links") or []:
        if not isinstance(l, dict):
            continue
        tgt = l.get("concept_id")
        pair = str(l.get("representation_pair", "")).replace("↔", "<->")
        if tgt in valid_ids and tgt != cid and "<->" in pair:
            integ.append({"concept_id": tgt, "representation_pair": pair, "note": str(l.get("note", ""))})
        else:
            errors.append(f"integration link target {tgt!r} invalid or bad representation_pair {pair!r}")
    if not integ:
        errors.append("need >=1 valid integration link")
    clean["integration_links"] = integ

    probes = []
    for p in payload.get("ct_probes") or []:
        if isinstance(p, dict) and p.get("question") and p.get("expected_insight"):
            kind = p.get("kind") if p.get("kind") in PROBE_KINDS else "why"
            probes.append({"kind": kind, "question": str(p["question"]),
                           "expected_insight": str(p["expected_insight"])})
    if len(probes) < 2:
        errors.append(f"need >=2 ct_probes with question+expected_insight, got {len(probes)}")
    if not any(p["kind"] == "counterexample" for p in probes):
        errors.append("need at least one ct_probe of kind 'counterexample'")
    clean["ct_probes"] = probes

    apps = [{"text": str(a["text"]), "domain": str(a.get("domain", "")),
             "transfer_type": a.get("transfer_type", "near")}
            for a in (payload.get("applications") or []) if isinstance(a, dict) and a.get("text")]
    if not apps:
        errors.append("need >=1 application")
    clean["applications"] = apps

    vocab = [str(v) for v in (payload.get("vocabulary") or []) if isinstance(v, (str, int))]
    if not vocab:
        errors.append("need non-empty vocabulary")
    clean["vocabulary"] = vocab

    metas, whens = [], set()
    for m in payload.get("metacognitive_prompts") or []:
        if isinstance(m, dict) and m.get("when") in ("after_success", "after_struggle") and m.get("prompt"):
            metas.append({"when": m["when"], "prompt": str(m["prompt"])})
            whens.add(m["when"])
    if whens != {"after_success", "after_struggle"}:
        errors.append("metacognitive_prompts must cover both after_success and after_struggle")
    clean["metacognitive_prompts"] = metas

    return clean, errors


def run_concepts(client, cache: Cache, issues: IssueLog, concepts, G, chunks, limit=None):
    valid_ids = [c["concept_id"] for c in concepts]
    valid_set = set(valid_ids)
    todo = [c for c in concepts if cache.get(f"concept::{c['concept_id']}") is None]
    cached = len(concepts) - len(todo)
    if limit:
        todo = todo[:limit]
    print(f"[concepts] {len(concepts)} cards, {len(todo)} to enrich ({cached} cached)")
    for card in tqdm(todo, desc="concept enrichment"):
        cid = card["concept_id"]
        ctx = concept_context(G, chunks, card)
        payload = call_json(client, concept_prompt(card, ctx, valid_ids))
        clean, errors = validate_concept_payload(payload, cid, valid_set)
        if errors:  # one retry with the errors fed back (plan Phase 1 step 3)
            payload = call_json(client, concept_prompt(card, ctx, valid_ids,
                                                       feedback="\n".join(f"- {e}" for e in errors)))
            clean, errors = validate_concept_payload(payload, cid, valid_set)
            if errors:
                issues.log("concepts", f"{cid}: kept valid subset, dropped/short on: {errors}")
        cache.put(f"concept::{cid}", clean)


# ---------------------------------------------------------------------------
# Stage: misconception enrichment
# ---------------------------------------------------------------------------
def run_misconceptions(client, cache: Cache, issues: IssueLog, G, concepts, batch_size=30, limit=None):
    cards = {c["concept_id"]: c for c in concepts}
    owner: Dict[str, str] = {}
    for u, v, d in G.edges(data=True):
        if d.get("relation") == "has_misconception" and u in cards:
            owner.setdefault(v, u)

    nodes = [(n, a) for n, a in G.nodes(data=True) if a.get("type") == "misconception" and a.get("text")]
    todo = [(n, a) for n, a in nodes if cache.get(f"misc::{n}") is None]
    if limit:
        todo = todo[:limit]
    print(f"[misconceptions] {len(nodes)} nodes, {len(todo)} to enrich")

    def attempt(batch):
        items = []
        for n, a in batch:
            oc = cards.get(owner.get(n, ""), {})
            items.append({"id": n, "misconception": a["text"],
                          "concept": oc.get("name", ""), "concept_summary": oc.get("summary", "")})
        prompt = f"""You are enriching misconception nodes of an NCERT Class 10 Maths tutoring graph.
For EACH item return an object. Return STRICT JSON: {{"items": [...]}} in the same order, each:
{{
  "id": "<copy the input id exactly>",
  "why_wrong": "<1-2 sentences: the faulty reasoning behind this misconception>",
  "correct_idea": "<1-2 sentences: the correct conception, stated positively>",
  "diagnostic_question": "<one short question that a student holding this misconception answers WRONG and a student with the correct idea answers RIGHT>",
  "expected_answer": "<the correct answer to the diagnostic question, brief>"
}}
The diagnostic must discriminate: do NOT ask 'is this misconception true?'; pose a concrete task.

Items:
{json.dumps(items, ensure_ascii=False, indent=1)}
"""
        payload = call_json(client, prompt)
        out = {}
        for obj in (payload.get("items") or []) if isinstance(payload, dict) else []:
            if (isinstance(obj, dict) and obj.get("id") and obj.get("why_wrong")
                    and obj.get("correct_idea") and obj.get("diagnostic_question") and obj.get("expected_answer")):
                out[obj["id"]] = {k: str(obj[k]) for k in
                                  ("why_wrong", "correct_idea", "diagnostic_question", "expected_answer")}
        return out

    pending = todo
    for round_no in (1, 2):  # second round = retry of failures
        failed = []
        for start in tqdm(range(0, len(pending), batch_size), desc=f"misconception batches (round {round_no})"):
            batch = pending[start:start + batch_size]
            try:
                got = attempt(batch)
            except RuntimeError as e:
                issues.log("misconceptions", f"batch failed: {e}")
                got = {}
            for n, a in batch:
                if n in got:
                    cache.put(f"misc::{n}", got[n])
                else:
                    failed.append((n, a))
        if not failed:
            break
        pending = failed
    for n, _ in pending if failed else []:
        issues.log("misconceptions", f"{n}: no valid enrichment after retry")


# ---------------------------------------------------------------------------
# Stage: problem schemas (A1.1 + A1.3)
# ---------------------------------------------------------------------------
def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(s or "").strip())
    return s.strip("_").lower() or "schema"


def schema_instances(G, chunks, card) -> List[dict]:
    """Same-doc worked examples / exercises: graph nodes (post-repair) + chunks."""
    cid, doc = card["concept_id"], card.get("chapter_doc")
    inst = []
    if cid in G:
        for nbr in G.successors(cid):
            a = G.nodes[nbr]
            if a.get("type") in ("example", "exercise") and a.get("text") and doc_of_node(nbr) == doc:
                inst.append({"id": nbr, "kind": a["type"], "text": a["text"][:400],
                             "difficulty": a.get("difficulty")})
    for c in chunks:
        if cid in (c.get("concept_ids") or []) and c.get("pedagogical_role") in ("worked_example", "practice", "challenge"):
            inst.append({"id": c["chunk_id"], "kind": "chunk", "text": (c.get("text") or "")[:400],
                         "difficulty": c.get("difficulty")})
    return inst[:25]


def run_schemas(client, cache: Cache, issues: IssueLog, concepts, G, chunks, limit=None):
    todo = [c for c in concepts if cache.get(f"schema::{c['concept_id']}") is None]
    if limit:
        todo = todo[:limit]
    print(f"[schemas] {len(concepts)} concepts, {len(todo)} to process")
    for card in tqdm(todo, desc="problem schemas"):
        cid = card["concept_id"]
        inst = schema_instances(G, chunks, card)
        if not inst:
            cache.put(f"schema::{cid}", {"schemas": [], "reason": "no instances"})
            continue
        misc_ids = [n for n in G.successors(cid) if G.nodes[n].get("type") == "misconception"] if cid in G else []

        def attempt(feedback=""):
            fb = f"\nPREVIOUS ATTEMPT ERRORS — fix them:\n{feedback}\n" if feedback else ""
            prompt = f"""You are extracting PROBLEM-TYPE SCHEMAS for one Class 10 Maths concept: students fail at
problem classes ("boat upstream/downstream word problem"), not at concepts. Cluster the instances
below into 1-4 problem types. Return STRICT JSON:
{{"schemas": [
  {{
    "name": "<problem-type name, e.g. 'upstream/downstream speed word problem'>",
    "slug": "<short_snake_case_slug>",
    "method_steps": ["<ordered algorithmic step>", ... 3-8 steps a student executes],
    "instance_ids": ["<ids copied EXACTLY from the instances below that instantiate this type>"],
    "isomorphic_variables": ["<surface variable swappable without changing structure/difficulty, e.g. 'names', 'speeds (numbers)', 'context: boat->train'>"],
    "trap_steps": [{{"step": <1-based index into method_steps>, "trap": "<error students make here>", "misconception_id": "<id from the misconception list, or null>"}}]
  }}
]}}
Rules: every instance_id must come from the given instances; method_steps are the general
algorithm, not one instance's numbers; cover as many instances as genuinely fit.
{fb}
CONCEPT: {card['name']} — {card.get('summary','')}

MISCONCEPTION IDS for trap linking: {json.dumps(misc_ids)}

INSTANCES:
{json.dumps(inst, ensure_ascii=False, indent=1)}
"""
            payload = call_json(client, prompt)
            valid_inst = {i["id"] for i in inst}
            schemas, errs = [], []
            for s in (payload.get("schemas") or []) if isinstance(payload, dict) else []:
                if not isinstance(s, dict) or not s.get("name"):
                    continue
                steps = [str(x) for x in (s.get("method_steps") or []) if str(x).strip()]
                ids = [i for i in (s.get("instance_ids") or []) if i in valid_inst]
                bad = [i for i in (s.get("instance_ids") or []) if i not in valid_inst]
                if bad:
                    errs.append(f"schema {s.get('slug')}: unknown instance_ids {bad}")
                if len(steps) < 3:
                    errs.append(f"schema {s.get('slug')}: needs >=3 method_steps")
                    continue
                if not ids:
                    errs.append(f"schema {s.get('slug')}: no valid instance_ids")
                    continue
                traps = []
                for t in s.get("trap_steps") or []:
                    if isinstance(t, dict) and t.get("trap"):
                        mid = t.get("misconception_id")
                        try:
                            step_no = max(1, int(t.get("step")))
                        except (TypeError, ValueError):
                            step_no = 1
                        traps.append({"step": step_no, "trap": str(t["trap"]),
                                      "misconception_id": mid if mid in misc_ids else None})
                schemas.append({
                    "name": str(s["name"]), "slug": slugify(s.get("slug") or s["name"]),
                    "method_steps": steps, "instance_ids": ids,
                    "isomorphic_variables": [str(x) for x in (s.get("isomorphic_variables") or [])],
                    "trap_steps": traps,
                })
            if not schemas:
                errs.append("no valid schemas produced")
            return schemas, errs

        schemas, errs = attempt()
        if errs:
            schemas2, errs2 = attempt(feedback="\n".join(f"- {e}" for e in errs))
            if schemas2:
                schemas, errs = schemas2, errs2
            if errs:
                issues.log("schemas", f"{cid}: {errs}")
        cache.put(f"schema::{cid}", {"schemas": schemas})


# ---------------------------------------------------------------------------
# Stage: hint chains (A1.2)
# ---------------------------------------------------------------------------
def hint_targets(G, cache: Cache) -> List[dict]:
    """Every exercise node + every enriched misconception diagnostic needs a chain."""
    # exercise -> owning schema method_steps (via cached schemas)
    steps_of: Dict[str, List[str]] = {}
    for key, data in cache.mem.items():
        if key.startswith("schema::") and isinstance(data, dict):
            for s in data.get("schemas") or []:
                for iid in s.get("instance_ids", []):
                    steps_of.setdefault(iid, s["method_steps"])
    targets = []
    for n, a in G.nodes(data=True):
        if a.get("type") == "exercise" and a.get("text"):
            targets.append({"id": n, "question": a["text"][:500], "expected_answer": "",
                            "method_steps": steps_of.get(n, [])})
    for key, data in list(cache.mem.items()):
        if key.startswith("misc::") and isinstance(data, dict) and data.get("diagnostic_question"):
            n = key.split("::", 1)[1]
            targets.append({"id": n, "question": data["diagnostic_question"],
                            "expected_answer": data.get("expected_answer", ""), "method_steps": []})
    return targets


def chain_valid(hints: Any, expected_answer: str) -> bool:
    if not isinstance(hints, list) or len(hints) != 3:
        return False
    ans = re.sub(r"\s+", " ", (expected_answer or "").strip().lower())
    for h in hints:
        if not isinstance(h, str) or not h.strip() or ANSWER_LEAK_RE.search(h):
            return False
        if ans and len(ans) > 3 and ans in re.sub(r"\s+", " ", h.lower()):
            return False
    return True


def run_hints(client, cache: Cache, issues: IssueLog, G, batch_size=25, limit=None):
    targets = [t for t in hint_targets(G, cache) if cache.get(f"hints::{t['id']}") is None]
    if limit:
        targets = targets[:limit]
    print(f"[hints] {len(targets)} exercise/diagnostic nodes need hint chains")

    def attempt(batch):
        items = [{"id": t["id"], "question": t["question"],
                  "method_steps": t["method_steps"][:8]} for t in batch]
        prompt = f"""For EACH problem below produce a FADED HINT CHAIN of exactly 3 hints for a Class 10 student:
hint 1 = conceptual nudge (which idea applies, no method), hint 2 = formula/method recall
(which tool/steps, no numbers from this problem worked out), hint 3 = partial first step
(set up the very first step only). HARD RULE: no hint may state, compute, or imply the final
answer, and never use phrases like "the answer is". Ground hints in the method_steps when given.
Return STRICT JSON: {{"items": [{{"id": "<copy exactly>", "hints": ["<hint1>", "<hint2>", "<hint3>"]}}]}} in order.

Problems:
{json.dumps(items, ensure_ascii=False, indent=1)}
"""
        payload = call_json(client, prompt)
        out = {}
        for obj in (payload.get("items") or []) if isinstance(payload, dict) else []:
            if isinstance(obj, dict) and obj.get("id"):
                out[obj["id"]] = obj.get("hints")
        return out

    by_id = {t["id"]: t for t in targets}
    pending = targets
    failed: List[dict] = []
    for round_no in (1, 2):
        failed = []
        for start in tqdm(range(0, len(pending), batch_size), desc=f"hint batches (round {round_no})"):
            batch = pending[start:start + batch_size]
            try:
                got = attempt(batch)
            except RuntimeError as e:
                issues.log("hints", f"batch failed: {e}")
                got = {}
            for t in batch:
                hints = got.get(t["id"])
                if chain_valid(hints, by_id[t["id"]]["expected_answer"]):
                    chain = [{"level": i + 1, "kind": HINT_KINDS[i], "text": h} for i, h in enumerate(hints)]
                    cache.put(f"hints::{t['id']}", chain)
                else:
                    failed.append(t)
        if not failed:
            break
        pending = failed
    for t in failed:
        issues.log("hints", f"{t['id']}: no leak-free 3-hint chain after retry")


# ---------------------------------------------------------------------------
# Stage: write-back
# ---------------------------------------------------------------------------
def apply_enrichment(concepts: List[dict], G: nx.DiGraph, cache_mem: Dict[str, Any]) -> Dict[str, int]:
    """Apply cached Phase-1 enrichment to concept cards + graph, in place.

    Pure mutation, no file IO — used by write_back here AND by build_index.py's
    consolidated rebuild (plan Phase 4 step 1), so a full rebuild reproduces the
    enrichment from cache without any LLM call.
    """
    stamp = {"source": "generated", "model": GEN_MODEL, "date": date.today().isoformat()}

    enriched_cards = 0
    for card in concepts:
        data = cache_mem.get(f"concept::{card['concept_id']}")
        if not data:
            continue
        # Curated links (e.g. the Polynomials seed's) stay verbatim, in front; the
        # generated ones append after, deduped by (target, transfer_type).
        curated = card.get("transfer_links") or []
        seen = {(t.get("target"), t.get("transfer_type")) for t in curated if isinstance(t, dict)}
        merged = curated + [t for t in data.get("transfer_links", [])
                            if (t["target"], t["transfer_type"]) not in seen]
        card.update({k: v for k, v in data.items() if k != "transfer_links"})
        card["transfer_links"] = merged
        card["enrichment"] = dict(stamp)
        enriched_cards += 1

    misc_done = 0
    for key, data in cache_mem.items():
        if key.startswith("misc::") and isinstance(data, dict) and data.get("why_wrong"):
            n = key.split("::", 1)[1]
            if n in G:
                G.nodes[n].update(data)
                G.nodes[n]["enrichment_source"] = "generated"
                misc_done += 1

    schema_nodes = 0
    for card in concepts:
        cid = card["concept_id"]
        data = cache_mem.get(f"schema::{cid}")
        if not data:
            continue
        for s in data.get("schemas") or []:
            sid = f"schema::{cid}::{s['slug']}"
            node_inst = [i for i in s["instance_ids"] if i in G]
            chunk_inst = [i for i in s["instance_ids"] if i not in G]
            G.add_node(sid, type="problem_schema", concept_id=cid, name=s["name"],
                       method_steps=s["method_steps"], isomorphic_variables=s["isomorphic_variables"],
                       trap_steps=s["trap_steps"], instance_ids=node_inst,
                       chunk_instance_ids=chunk_inst, source="generated")
            G.add_edge(cid, sid, relation="has_schema")
            for iid in node_inst:
                G.add_edge(sid, iid, relation="instantiated_by")
            schema_nodes += 1

    hint_done = 0
    for key, chain in cache_mem.items():
        if key.startswith("hints::") and isinstance(chain, list):
            n = key.split("::", 1)[1]
            if n in G:
                G.nodes[n]["hint_chain"] = chain
                hint_done += 1

    return {"enriched_cards": enriched_cards, "misconceptions_enriched": misc_done,
            "problem_schemas": schema_nodes, "hint_chains": hint_done}


def write_back(store: Path, cache: Cache, concepts, G: nx.DiGraph, repaired: int):
    for fname in ("concepts.json", "graph.json"):
        bak = store / f"{fname}.phase1.bak"
        if not bak.exists():
            shutil.copyfile(store / fname, bak)

    stats = apply_enrichment(concepts, G, cache.mem)
    enriched_cards = stats["enriched_cards"]
    misc_done = stats["misconceptions_enriched"]
    schema_nodes = stats["problem_schemas"]
    hint_done = stats["hint_chains"]
    stamp = {"source": "generated", "model": GEN_MODEL, "date": date.today().isoformat()}

    (store / "concepts.json").write_text(json.dumps(concepts, indent=2, ensure_ascii=False), encoding="utf-8")
    (store / "graph.json").write_text(json.dumps(nx.node_link_data(G), ensure_ascii=False, indent=2), encoding="utf-8")

    # meta: refresh node-type counts + record the enrichment pass (additive).
    meta_path = store / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    counts: Dict[str, int] = {}
    for _, a in G.nodes(data=True):
        counts[a.get("type", "unknown")] = counts.get(a.get("type", "unknown"), 0) + 1
    meta["node_type_counts"] = counts
    meta["graph_nodes"] = G.number_of_nodes()
    meta["graph_edges"] = G.number_of_edges()
    meta["phase1_enrichment"] = {**stamp, "enriched_cards": enriched_cards,
                                 "misconceptions_enriched": misc_done, "problem_schemas": schema_nodes,
                                 "hint_chains": hint_done, "repaired_edges": repaired}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[write] cards={enriched_cards} misconceptions={misc_done} schemas={schema_nodes} "
          f"hint_chains={hint_done} repaired_edges={repaired}")


# ---------------------------------------------------------------------------
def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="rag_store")
    ap.add_argument("--only", choices=["repair", "concepts", "misconceptions", "schemas", "hints", "write"],
                    default=None, help="Run a single stage (default: all, in order).")
    ap.add_argument("--limit", type=int, default=None, help="Per-stage item cap, for smoke tests.")
    ap.add_argument("--no-write", action="store_true", help="Skip the write-back stage.")
    args = ap.parse_args()

    store = Path(args.store)
    chunks, concepts, G = load_store(store)
    cache = Cache(store / "concept_enrich_cache.jsonl")
    issues = IssueLog(store / "concept_enrich_issues.log")
    valid_set = {c["concept_id"] for c in concepts}

    stages = [args.only] if args.only else ["repair", "concepts", "misconceptions", "schemas", "hints", "write"]
    client = make_client() if any(s in stages for s in ("concepts", "misconceptions", "schemas", "hints")) else None

    repaired = 0
    if "repair" in stages or "write" in stages:
        repaired = repair_dangling_edges(G, valid_set, issues)
        print(f"[repair] re-pointed {repaired} dangling-source edges")
    if "concepts" in stages:
        run_concepts(client, cache, issues, concepts, G, chunks, limit=args.limit)
    if "misconceptions" in stages:
        run_misconceptions(client, cache, issues, G, concepts, limit=args.limit)
    if "schemas" in stages:
        run_schemas(client, cache, issues, concepts, G, chunks, limit=args.limit)
    if "hints" in stages:
        run_hints(client, cache, issues, G, limit=args.limit)
    if "write" in stages and not args.no_write:
        write_back(store, cache, concepts, G, repaired)


if __name__ == "__main__":
    main()
