"""Generate student utterances for store concepts with zero dataset coverage.

LLM backend: the LOCAL Qwen model (qwen2.5-3b-instruct) served by llama.cpp on
the GPU — OpenAI-compatible endpoint at http://127.0.0.1:8080. No cloud client,
no offline stub. Start the server first:
    python F:/Projects/Pedagogical_study_pkg/scripts/run_llama_server.py

For each uncovered concept, generates ~50 short Indian-English student
utterances grounded in the concept card (name / aliases / vocabulary /
summary), validated for length, duplication, and on-topic keyword overlap.
Each row carries its own deterministic 80/10/10 split assignment so the
frozen Part 1 splits.json stays untouched.

Writes dataset/concept_gap_utterances.json. Resumable: dataset/gap_gen_cache.jsonl.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "dataset" / "exemplar_dataset_10000_curated.json"
CONCEPTS = ROOT / "rag_store" / "concepts.json"
DST = ROOT / "dataset" / "concept_gap_utterances.json"
CACHE = ROOT / "dataset" / "gap_gen_cache.jsonl"

SERVER = "http://127.0.0.1:8080"
PER_CONCEPT = 50
BATCH = 10
MAX_BATCHES = 14  # per concept, incl. retries for rejected rows
SEED = 11

STOPWORDS = set("a an the of in on for and or to is are this that with by from as at it its".split())

PROMPT = """You write synthetic chat messages from an Indian Class 10 student to a maths tutor bot.
Casual Indian-English student tone: short, sometimes broken grammar, "na", "pls", "sir" allowed.
Each message must clearly be about this maths concept:

CONCEPT: {name}
ALSO CALLED: {aliases}
KEY TERMS: {vocab}
WHAT IT IS: {summary}

Write {n} different student messages about this concept. Mix: confused questions, requests to
explain, doubts, "how to" questions, answer checks, real-life curiosity. 6 to 22 words each.
Vary the openings — do not start every message the same way. Use the concept's own words
(its key terms) naturally so the topic is recognizable.

Return ONLY a JSON array of {n} strings. No other text."""


def call_qwen(prompt: str, temperature: float = 0.9) -> str:
    resp = requests.post(
        f"{SERVER}/v1/chat/completions",
        json={
            "model": "qwen2.5-3b-instruct",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": 900,
        },
        timeout=240,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def parse_array(text: str) -> list[str]:
    """Lenient JSON-array parse for small-model output."""
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return [str(x) for x in data if isinstance(x, str)]
        except json.JSONDecodeError:
            pass
    # fallback: quoted lines
    return [q for q in re.findall(r'"([^"]{15,200})"', text)]


def content_words(*texts: str) -> set[str]:
    words = set()
    for t in texts:
        words |= {w for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in STOPWORDS}
    return words


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def main() -> None:
    try:
        requests.get(f"{SERVER}/health", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"llama.cpp server not reachable at {SERVER} ({exc}) — start it first")

    cards = json.loads(CONCEPTS.read_text(encoding="utf-8"))
    cards = cards if isinstance(cards, list) else cards["concepts"]
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    used = {r["concept_id"] for r in rows}
    missing = [c for c in cards if c["concept_id"] not in used]
    print(f"{len(missing)} uncovered concepts")

    cache: dict[str, str] = {}
    if CACHE.exists():
        for line in CACHE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                cache[rec["key"]] = rec["data"]

    seen = {_norm(r["student_utterance"]) for r in rows}
    rng = random.Random(SEED)
    out: list[dict] = []
    for card in missing:
        cid = card["concept_id"]
        anchor_words = content_words(
            card["name"], " ".join(card.get("aliases", [])), " ".join(card.get("vocabulary", []))
        )
        kept: list[str] = []
        for b in range(MAX_BATCHES):
            if len(kept) >= PER_CONCEPT:
                break
            key = f"{cid}::batch{b}"
            text = cache.get(key)
            if text is None:
                prompt = PROMPT.format(
                    name=card["name"],
                    aliases=", ".join(card.get("aliases", [])) or "-",
                    vocab=", ".join(card.get("vocabulary", [])) or "-",
                    summary=(card.get("summary") or "")[:400],
                    n=BATCH,
                )
                try:
                    text = call_qwen(prompt, temperature=0.9 if b < 8 else 1.0)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {key}: {exc} — skipped")
                    continue
                with CACHE.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "data": text}, ensure_ascii=False) + "\n")
                cache[key] = text
            for utt in parse_array(text):
                if len(kept) >= PER_CONCEPT:
                    break
                utt = utt.strip()
                n_words = len(utt.split())
                if not (5 <= n_words <= 26) or _norm(utt) in seen:
                    continue
                if not (content_words(utt) & anchor_words):
                    continue  # off-topic for the target concept
                seen.add(_norm(utt))
                kept.append(utt)
        # deterministic 80/10/10 split per concept (5 val + 5 test when full)
        order = list(range(len(kept)))
        rng.shuffle(order)
        n_val = max(1, round(len(kept) * 0.10))
        n_test = max(1, round(len(kept) * 0.10))
        split_of = {}
        for pos, idx in enumerate(order):
            split_of[idx] = "val" if pos < n_val else ("test" if pos < n_val + n_test else "train")
        for idx, utt in enumerate(kept):
            out.append({
                "student_utterance": utt,
                "concept_id": cid,
                "miniLM_labels": "",
                "hope_signals": "",
                "target_policy_action": "",
                "category": 0,
                "source": "gap_generation_qwen",
                "split": split_of[idx],
            })
        print(f"{cid}: kept {len(kept)}/{PER_CONCEPT}")

    DST.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(out)} rows -> {DST.name}")


if __name__ == "__main__":
    main()
