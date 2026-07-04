import json, random
from pathlib import Path
from collections import Counter

# Set UTF-8 output mode for Windows console
import sys
import codecs
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# raw 10k was re-pointed to dataset/archive/ when _fixed.json became canonical;
# fall back to the archived copy so this provenance verifier still runs.
data_path = Path("dataset/exemplar_dataset_10000.json")
if not data_path.exists():
    data_path = Path("dataset/archive/exemplar_dataset_10000.json")
if not data_path.exists():
    print("Error: exemplar_dataset_10000.json not found (checked dataset/ and dataset/archive/).")
    sys.exit(1)

data = json.loads(data_path.read_text(encoding="utf-8"))
print(f"==================================================")
print(f"  VERIFICATION REPORT FOR 10,000 SAMPLES")
print(f"==================================================")
print(f"Loaded: {len(data)} samples successfully.\n")

# 1. Category distribution
cats = Counter(s["category"] for s in data)
cat_names = {
    1: "Representation & Sensemaking Requests",
    2: "Context, Analogy & Transfer Requests",
    3: "Motivation, Resistance & System Gaming",
    4: "Flow & Prerequisite Management",
    5: "Self-Doubt & Math Anxiety",
    6: "Procedural Fixation & Board Exam Pressure",
    7: "Skepticism & Teacher/Textbook Conflict",
    8: "Vague Troubleshooting & Inarticulate Confusion",
    9: "Task-Based Grounding"
}
print("=== CATEGORY DISTRIBUTION ===")
for c in sorted(cats):
    print(f"  Cat {c} ({cat_names.get(c, '?')}): {cats[c]} samples")

# 2. Concept Split
inherit = sum(1 for s in data if s["concept_id"] == "INHERIT_CURRENT_CONCEPT")
specific = len(data) - inherit
print(f"\n=== CONCEPT SPLIT ===")
print(f"  INHERIT_CURRENT_CONCEPT: {inherit} ({inherit*100/len(data):.1f}%)")
print(f"  Specific concept_ids: {specific} ({specific*100/len(data):.1f}%)")

# 3. Chapter coverage
chapters = Counter()
for s in data:
    cid = s["concept_id"]
    if cid != "INHERIT_CURRENT_CONCEPT" and "__" in cid:
        chapters[cid.split("__")[0]] += 1
print(f"\n=== CHAPTER COVERAGE ({len(chapters)} chapters) ===")
for ch in sorted(chapters):
    print(f"  {ch}: {chapters[ch]} samples")

# 4. Unique concepts
unique_cids = set(s["concept_id"] for s in data if s["concept_id"] != "INHERIT_CURRENT_CONCEPT")
print(f"\n=== UNIQUE CONCEPT IDS: {len(unique_cids)} ===")

# 5. Sample utterances (random 5)
print(f"\n=== RANDOM SAMPLE UTTERANCES ===")
random.seed(42)
for i, s in enumerate(random.sample(data, 5), 1):
    print(f"\nSample #{i}:")
    print(f"  Utterance: \"{s['student_utterance']}\"")
    print(f"  Category:  {s['category']} ({cat_names[s['category']]})")
    print(f"  Concept:   {s['concept_id']}")
    print(f"  MiniLM:    {s['miniLM_labels']}")
    print(f"  HOPE:      {s['hope_signals']}")
    print(f"  Policy:    {s['target_policy_action']}")
print(f"\n==================================================")
