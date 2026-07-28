import json
from pathlib import Path
from collections import Counter
import random

data = json.loads(Path("dataset/exemplar_dataset_100.json").read_text("utf-8"))

# Category distribution
cats = Counter(s["category"] for s in data)
cat_names = {1:"Representation", 2:"Transfer", 3:"Motivation", 4:"Flow", 5:"Anxiety", 6:"Procedural", 7:"Skepticism", 8:"Vague", 9:"Grounding"}
print("=== CATEGORY DISTRIBUTION ===")
for c in sorted(cats):
    print(f"  Cat {c} ({cat_names.get(c, '?')}): {cats[c]}")

# Concept distribution
inherit = sum(1 for s in data if s["concept_id"] == "INHERIT_CURRENT_CONCEPT")
specific = len(data) - inherit
print(f"\n=== CONCEPT SPLIT ===")
print(f"  INHERIT: {inherit} ({inherit}%)")
print(f"  Specific: {specific} ({specific}%)")

# Chapter coverage
chapters = Counter()
for s in data:
    cid = s["concept_id"]
    if cid != "INHERIT_CURRENT_CONCEPT" and "__" in cid:
        chapters[cid.split("__")[0]] += 1
print(f"\n=== CHAPTER COVERAGE ({len(chapters)} chapters) ===")
for ch in sorted(chapters):
    print(f"  {ch}: {chapters[ch]} samples")

# Unique concepts
unique_cids = set(s["concept_id"] for s in data if s["concept_id"] != "INHERIT_CURRENT_CONCEPT")
print(f"\n=== UNIQUE CONCEPT IDS: {len(unique_cids)} ===")
for cid in sorted(unique_cids):
    print(f"  {cid}")

# Sample utterances
print(f"\n=== SAMPLE UTTERANCES (random 10) ===")
random.seed(42)
for s in random.sample(data, 10):
    utt = s["student_utterance"][:90]
    suffix = "..." if len(s["student_utterance"]) > 90 else ""
    print(f"  [Cat{s['category']}] {utt}{suffix}")
    print(f"         concept_id: {s['concept_id']}")
    print(f"         labels: {s['miniLM_labels']}")
    print()
