"""
generate_exemplar_dataset.py
─────────────────────────────
Generates MiniLM Exemplar Classifier training data using Gemini.
Reads concept IDs from rag_store/concepts.json and examples.md rules,
then produces realistic, noisy student utterances with proper annotations.

Usage:
  python generate_exemplar_dataset.py --count 100   # pilot batch
  python generate_exemplar_dataset.py --count 10000  # full dataset
"""

from __future__ import annotations
import argparse, csv, json, os, re, time, random
from pathlib import Path
from typing import Any, Dict, List
from dotenv import load_dotenv
from google import genai
from google.genai import types
from rag_core import make_client

# ── Config ───────────────────────────────────────────────────────────
# Vertex AI mode: uses gcloud auth application-default credentials
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
load_dotenv()
GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")
RAG_STORE = Path("rag_store")
CONCEPTS_PATH = RAG_STORE / "concepts.json"
EXAMPLES_PATH = Path("examples.md")
OUTPUT_DIR = Path("dataset")
OUTPUT_DIR.mkdir(exist_ok=True)

BATCH_SIZE = 10  # samples per Gemini call (reduced for API stability)

# ── 9 categories (Section 10 is INHERIT-only, folded into the others) ──
CATEGORIES = [
    {
        "id": 1,
        "name": "Representation & Sensemaking Requests",
        "description": "Student is struggling with HOW the concept is presented (diagram vs equation vs verbal). They want a different representation.",
        "inherit_ratio": 0.45,
        "miniLM_labels_pool": ["confusion", "question", "diagrammatic", "algebraic", "graphical", "self_correction", "representation_shift"],
        "hope_signals_pool": ["High load_risk", "Moderate load_risk", "Partial mastery", "High productive_struggle", "High ki_score opportunity"],
        "policy_actions_pool": ["REPRESENTATION_TRANSLATION", "EXPLAIN", "SOCRATIC_Q", "VISUAL_ANALOGY"],
    },
    {
        "id": 2,
        "name": "Context, Analogy & Transfer Requests",
        "description": "Student is trying to connect the concept to real life, another domain, or another math topic. High curiosity / transfer signal.",
        "inherit_ratio": 0.45,
        "miniLM_labels_pool": ["transfer_attempt", "verbal_analogy", "curiosity", "abstraction_attempt", "request_hint", "example_request", "question"],
        "hope_signals_pool": ["High kt_score", "High ct_score", "Moderate kt_score", "High ki_score", "Active hint_dependency"],
        "policy_actions_pool": ["VISUAL_ANALOGY", "TRANSFER_PROBLEM", "SOCRATIC_COUNTEREXAMPLE", "ANALOGOUS_EXAMPLE", "EXPLAIN", "REPRESENTATION_TRANSLATION"],
    },
    {
        "id": 3,
        "name": "Motivation, Resistance & System Gaming",
        "description": "Student is frustrated, bored, seeking shortcuts, or trying to game the system. Emotional/affective utterances.",
        "inherit_ratio": 0.45,
        "miniLM_labels_pool": ["frustration", "disengagement", "confusion", "shortcut_seeking", "topic_shift", "curiosity", "abstraction_attempt"],
        "hope_signals_pool": ["Low productive_struggle", "High load_risk", "Moderate ct_score", "Surface engagement"],
        "policy_actions_pool": ["ENCOURAGE", "METACOGNITIVE_REFLECT", "SOCRATIC_COUNTEREXAMPLE", "EXPLAIN", "REVIEW", "SOCRATIC_Q"],
    },
    {
        "id": 4,
        "name": "Flow & Prerequisite Management",
        "description": "Student wants to move forward, go back, skip, or is hitting a prerequisite wall. Pacing and curriculum flow.",
        "inherit_ratio": 0.30,
        "miniLM_labels_pool": ["topic_shift", "ready_for_next", "frustration", "confusion", "self_monitoring"],
        "hope_signals_pool": ["Mastery threshold met", "Prerequisite weakness", "High confidence", "Prerequisite awareness"],
        "policy_actions_pool": ["TRANSFER_PROBLEM", "BRIDGE_RECAP", "QUIZ", "REVIEW"],
    },
    {
        "id": 5,
        "name": "Self-Doubt & Math Anxiety",
        "description": "Student expresses low confidence, anxiety about exams, self-deprecation, or wants to give up. Cognitive overload expressed as personal failure.",
        "inherit_ratio": 0.40,
        "miniLM_labels_pool": ["low_confidence", "frustration", "disengagement", "anxiety", "self_monitoring", "confusion"],
        "hope_signals_pool": ["High load_risk", "Low confidence", "Recurring Misconception", "Recurring error"],
        "policy_actions_pool": ["ENCOURAGE", "METACOGNITIVE_REFLECT", "MISCONCEPTION_PROBE", "ISOMORPHIC_PRACTICE", "VISUAL_ANALOGY", "WORKED_EXAMPLE"],
    },
    {
        "id": 6,
        "name": "Procedural Fixation & Board Exam Pressure",
        "description": "Student wants only formulas, memorized steps, or asks if something is 'important for boards'. Rote memorization over understanding.",
        "inherit_ratio": 0.45,
        "miniLM_labels_pool": ["procedural_focus", "shortcut_seeking", "hint_dependency", "question", "curiosity", "anxiety", "ready_for_next", "answer_attempt"],
        "hope_signals_pool": ["Low productive_struggle", "Low ki_score", "Low ct_score", "Surface engagement", "Moderate load_risk"],
        "policy_actions_pool": ["SOCRATIC_Q", "EXPLAIN", "WORKED_EXAMPLE", "TRANSFER_PROBLEM"],
    },
    {
        "id": 7,
        "name": "Skepticism & Teacher/Textbook Conflict",
        "description": "Student questions correctness, reports conflict between tutor and school teacher, or says textbook answer differs.",
        "inherit_ratio": 0.40,
        "miniLM_labels_pool": ["conflict", "confusion", "skepticism", "self_correction", "misconception_clue", "question", "diagrammatic"],
        "hope_signals_pool": ["High ki_score opportunity", "Active misconception check", "Moderate ct_score", "Active misconception"],
        "policy_actions_pool": ["REPRESENTATION_TRANSLATION", "EXPLAIN", "WORKED_EXAMPLE", "MISCONCEPTION_PROBE", "SOCRATIC_COUNTEREXAMPLE"],
    },
    {
        "id": 8,
        "name": "Vague Troubleshooting & Inarticulate Confusion",
        "description": "Student can't articulate what's wrong. Very vague statements like 'it's not working', 'something is off', 'graph looks weird'.",
        "inherit_ratio": 0.45,
        "miniLM_labels_pool": ["confusion", "low_confidence", "frustration", "graphical", "cognitive_overload", "self_correction", "skepticism", "diagrammatic"],
        "hope_signals_pool": ["High load_risk", "Active misconception", "Moderate load_risk", "Moderate ct_score"],
        "policy_actions_pool": ["SOCRATIC_Q", "MISCONCEPTION_PROBE", "VISUAL_ANALOGY", "WORKED_EXAMPLE", "BRIDGE_RECAP"],
    },
    {
        "id": 9,
        "name": "Task-Based Grounding",
        "description": "Student wants to use physical objects (blocks, clay, paper, dice) to understand a concept. Embodied/physical learning requests.",
        "inherit_ratio": 0.40,
        "miniLM_labels_pool": ["request_representation", "physical", "graphical", "transfer_attempt", "curiosity", "confusion", "environmental_feedback"],
        "hope_signals_pool": ["High ki_score", "High kt_score", "High ct_score", "Moderate load_risk", "Low productive_struggle"],
        "policy_actions_pool": ["REPRESENTATION_TRANSLATION", "TRANSFER_PROBLEM", "WORKED_EXAMPLE", "ENCOURAGE"],
    },
]


def load_concepts() -> List[Dict[str, Any]]:
    """Load all concept cards from the RAG store."""
    raw = json.loads(CONCEPTS_PATH.read_text(encoding="utf-8"))
    return [
        {
            "concept_id": c["concept_id"],
            "name": c["name"],
            "aliases": c.get("aliases", []),
            "summary": c.get("summary", ""),
            "chapter_doc": c.get("chapter_doc", ""),
            "misconceptions": c.get("misconceptions", []),
        }
        for c in raw
    ]


def load_seed_examples() -> str:
    """Load examples.md as a string for few-shot context."""
    return EXAMPLES_PATH.read_text(encoding="utf-8")


def build_concept_reference(concepts: List[Dict]) -> str:
    """Build a compact concept reference string for the prompt."""
    lines = []
    for c in concepts:
        aliases = ", ".join(c["aliases"]) if c["aliases"] else "none"
        lines.append(f'- {c["concept_id"]} | {c["name"]} | aliases: {aliases}')
    return "\n".join(lines)


def build_system_prompt(concepts: List[Dict], seed_examples: str) -> str:
    """Build the system prompt with ALL rules baked in."""
    concept_ref = build_concept_reference(concepts)

    return f"""You are a dataset generation engine for a MiniLM Exemplar Classifier that classifies 10th-standard (Class 10 CBSE/NCERT) Indian math students' utterances.

## YOUR TASK
Generate realistic, diverse student utterances with proper annotations. Each sample must have:
1. `student_utterance` — what the student actually types/says
2. `concept_id` — either a specific ID from the ALLOWED list below, or `INHERIT_CURRENT_CONCEPT`
3. `miniLM_labels` — comma-separated classification labels
4. `hope_signals` — HOPE detector state signals
5. `target_policy_action` — the pedagogical action the system should take
6. `category` — which of the 9 categories (1-9) this utterance belongs to

## CRITICAL RULES — VIOLATING ANY OF THESE MAKES THE SAMPLE INVALID

### Rule 1: Concept ID Assignment
- Use `INHERIT_CURRENT_CONCEPT` for generic utterances where the student does NOT explicitly name a mathematical concept.
- A specific `concept_id` should ONLY be assigned when the utterance **explicitly and unambiguously** names a mathematical concept that maps to an entry in the ALLOWED list.
- Examples of INHERIT: "what is this diagram", "this is so boring", "ok what next", "can you explain again"
- Examples of SPECIFIC: "i dont understand trigonometry" → jemh108__intro_trigonometry, "parabola graph confuses me" → jemh102__quadratic_zero_geometry
- NEVER invent concept IDs. ONLY use IDs from the ALLOWED CONCEPT LIST below.

### Rule 2: Utterance Style — REAL STUDENT LANGUAGE
- Write like a REAL 10th-standard Indian student, NOT like a textbook or ChatGPT.
- Grammar errors, missing articles, dropped punctuation ("cant", "dont", "pls", "na", "n all")
- Layman terms ("that U shape graph", "plus minus formula", "that angle looking up thing")
- Run-on sentences, casual tone, emotional outbursts ("just tell me the answer pls i wont tell anyone")
- Abbreviations ("AP", "BPT", "sin cos", "HCF", "LCM")
- Indian English patterns ("i didnt understand only", "is it coming in boards na?", "one is enough na")
- DO NOT use Hindi or Hinglish. English only (with Indian English patterns).
- NEVER produce grammatically perfect, synthetic-sounding utterances.

### Rule 3: MiniLM Labels
Valid labels (use 1-3 per sample): confusion, question, diagrammatic, algebraic, graphical, self_correction, representation_shift, transfer_attempt, verbal_analogy, curiosity, abstraction_attempt, request_hint, example_request, frustration, disengagement, shortcut_seeking, topic_shift, low_confidence, anxiety, self_monitoring, procedural_focus, hint_dependency, answer_attempt, ready_for_next, conflict, skepticism, misconception_clue, cognitive_overload, request_representation, physical, environmental_feedback, tabular

### Rule 4: HOPE / State Signals
Valid signals: High load_risk, Moderate load_risk, Low productive_struggle, High productive_struggle, High kt_score, High ct_score, Moderate kt_score, Moderate ct_score, High ki_score, Moderate ki_score, Low ki_score, Low ct_score, Active hint_dependency, Surface engagement, Mastery threshold met, Prerequisite weakness, High confidence, Low confidence, Prerequisite awareness, Partial mastery, Recurring Misconception, Recurring error, Active misconception, Active misconception check, Active engagement

### Rule 5: Target Policy Actions
Valid actions: EXPLAIN, VISUAL_ANALOGY, WORKED_EXAMPLE, SOCRATIC_Q, SOCRATIC_COUNTEREXAMPLE, MISCONCEPTION_PROBE, REPRESENTATION_TRANSLATION, TRANSFER_PROBLEM, BRIDGE_RECAP, REVIEW, QUIZ, ENCOURAGE, METACOGNITIVE_REFLECT, ISOMORPHIC_PRACTICE, ANALOGOUS_EXAMPLE, RESUME_STATE

### Rule 6: Diversity Requirements
- Spread concept_ids across ALL chapters (jemh101 through jemh114, jemh1a1, jemh1a2).
- Do NOT over-represent trigonometry or any single chapter.
- Vary the emotional tone: some students are calm, some frustrated, some anxious, some curious.
- Vary utterance length: some very short ("ok what next"), some medium, some long run-on sentences.
- Each sample must be UNIQUE — no duplicates or near-duplicates.

## ALLOWED CONCEPT LIST (ONLY use these concept_ids):
{concept_ref}

## REFERENCE EXAMPLES (from examples.md — follow this style):

Here are some real examples showing the correct format and style:

| "what is this diagram, i am not able to understand" | INHERIT_CURRENT_CONCEPT | confusion, question, diagrammatic | High load_risk | REPRESENTATION_TRANSLATION |
| "i can solve the quadratic equation but parabola confuses me" | jemh102__quadratic_zero_geometry | confusion, question, graphical | Moderate load_risk, High ki_score opportunity | REPRESENTATION_TRANSLATION |
| "why distance formula has square root in it, i dont get it" | jemh107__distance_formula | confusion, question, algebraic | Moderate load_risk | EXPLAIN |
| "probability is just guessing only, why we need formula for that" | jemh114__theoretical_probability_formula | frustration, curiosity | Low productive_struggle, Moderate ct_score | SOCRATIC_COUNTEREXAMPLE |
| "surface area n all are too long, just give me the answer, please, i wont tell anyone" | jemh112__surface_area_combined_solids | frustration, shortcut_seeking | Low productive_struggle, High load_risk | METACOGNITIVE_REFLECT |
| "i already know substitution method, skip to elimination pls" | jemh103__elimination_method | topic_shift, ready_for_next | High confidence | QUIZ |
| "before all this, i want to understand sin cos etc" | jemh108__fundamental_trig_ratios | self_monitoring, topic_shift | Prerequisite awareness | REVIEW |
| "i will never understand discriminant and nature of roots, its too much for me" | jemh104__discriminant_nature_of_roots | low_confidence, frustration, confusion | High load_risk | ENCOURAGE + VISUAL_ANALOGY |
| "my teacher said sum of zeroes is b/a not minus b/a, who is correct?" | jemh102__quadratic_coefficients | conflict, confusion, misconception_clue | Active misconception | MISCONCEPTION_PROBE |
| "i put values in probability formula but answer is coming more than 1, how is that possible" | jemh114__probability_range | confusion, frustration | Active misconception, High load_risk | MISCONCEPTION_PROBE |
| "can you show parabola shape of quadratic using rope or blocks or something" | jemh102__quadratic_zero_geometry | request_representation, physical, graphical | High ki_score | REPRESENTATION_TRANSLATION |
| "this is so boring" | INHERIT_CURRENT_CONCEPT | frustration, disengagement | Low productive_struggle | ENCOURAGE |
| "ok what next" | INHERIT_CURRENT_CONCEPT | topic_shift, ready_for_next | Mastery threshold met | TRANSFER_PROBLEM |
| "wait wait, let me think for a sec" | INHERIT_CURRENT_CONCEPT | self_monitoring | productive_struggle | ENCOURAGE |

## OUTPUT FORMAT
Return ONLY a JSON array. Each element is an object with these exact keys:
- "student_utterance" (string)
- "concept_id" (string — either a valid concept_id or "INHERIT_CURRENT_CONCEPT")
- "miniLM_labels" (string — comma-separated)
- "hope_signals" (string)
- "target_policy_action" (string)
- "category" (integer 1-9)

Return ONLY the JSON array, no markdown fences, no explanation."""


def generate_batch(
    client: genai.Client,
    system_prompt: str,
    category: Dict,
    batch_size: int,
    existing_utterances: set,
) -> List[Dict]:
    """Call Gemini to generate one batch of samples for a category."""

    user_prompt = f"""Generate exactly {batch_size} unique student utterances for category {category['id']}: "{category['name']}".

Category description: {category['description']}

Requirements for THIS category:
- Approximately {int(category['inherit_ratio'] * 100)}% should be INHERIT_CURRENT_CONCEPT (generic utterances)
- The remaining {int((1 - category['inherit_ratio']) * 100)}% should have specific concept_ids from the ALLOWED list
- Preferred MiniLM labels for this category: {', '.join(category['miniLM_labels_pool'])}
- Preferred HOPE signals: {', '.join(category['hope_signals_pool'])}
- Preferred policy actions: {', '.join(category['policy_actions_pool'])}
- Spread concept_ids across DIFFERENT chapters (jemh101-jemh114, jemh1a1, jemh1a2)
- All utterances MUST be in messy, natural, real student language (grammar errors, casual tone, abbreviations)
- Do NOT repeat any of these already-generated utterances: {json.dumps(list(existing_utterances)[-50:]) if existing_utterances else '[]'}

Return ONLY the JSON array."""

    resp = client.models.generate_content(
        model=GEN_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=1.0,  # high creativity for diversity
            top_p=0.95,
        ),
    )

    text = (resp.text or "").strip()
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    try:
        samples = json.loads(text)
        if not isinstance(samples, list):
            print(f"  WARNING: Expected list, got {type(samples)}. Wrapping.")
            samples = [samples]
        return samples
    except json.JSONDecodeError as e:
        print(f"  ERROR parsing JSON: {e}")
        print(f"  Raw response (first 500 chars): {text[:500]}")
        return []


def validate_sample(sample: Dict, valid_concept_ids: set) -> tuple[bool, str]:
    """Validate a single sample against all rules. Returns (is_valid, reason)."""
    required_keys = {"student_utterance", "concept_id", "miniLM_labels", "hope_signals", "target_policy_action", "category"}
    if not required_keys.issubset(sample.keys()):
        return False, f"Missing keys: {required_keys - set(sample.keys())}"

    cid = sample["concept_id"]
    if cid != "INHERIT_CURRENT_CONCEPT" and cid not in valid_concept_ids:
        return False, f"Invalid concept_id: {cid}"

    utterance = sample.get("student_utterance", "")
    if not utterance or len(utterance) < 3:
        return False, "Utterance too short"

    cat = sample.get("category")
    if not isinstance(cat, int) or cat < 1 or cat > 9:
        return False, f"Invalid category: {cat}"

    return True, "OK"


def main():
    parser = argparse.ArgumentParser(description="Generate MiniLM exemplar dataset using Gemini")
    parser.add_argument("--count", type=int, default=100, help="Total samples to generate")
    parser.add_argument("--output", type=str, default=None, help="Output CSV filename")
    args = parser.parse_args()

    total = args.count
    output_name = args.output or f"exemplar_dataset_{total}.csv"
    output_path = OUTPUT_DIR / output_name

    print(f"═══════════════════════════════════════════════════")
    print(f"  MiniLM Exemplar Dataset Generator")
    print(f"  Target: {total} samples → {output_path}")
    print(f"  Model: {GEN_MODEL}")
    print(f"═══════════════════════════════════════════════════")

    # Load concepts
    concepts = load_concepts()
    valid_ids = {c["concept_id"] for c in concepts}
    print(f"Loaded {len(concepts)} concepts from {CONCEPTS_PATH}")

    # Load examples for few-shot
    seed_examples = load_seed_examples()

    # Build system prompt
    system_prompt = build_system_prompt(concepts, seed_examples)

    # Initialize client (uses Vertex AI via rag_core.make_client)
    client = make_client()
    print(f"Gemini client initialized\n")

    # Distribute samples across categories (roughly equal, with small buffer)
    samples_per_category = total // len(CATEGORIES)
    remainder = total % len(CATEGORIES)

    all_samples: List[Dict] = []
    existing_utterances: set = set()
    invalid_count = 0

    json_path = output_path.with_suffix(".json")
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                all_samples = json.load(f)
            for s in all_samples:
                existing_utterances.add(s["student_utterance"].strip().lower())
            print(f"Resumed from existing file. Loaded {len(all_samples)} samples from {json_path}")
        except Exception as e:
            print(f"Failed to load existing JSON: {e}. Starting fresh.")
            all_samples = []
            existing_utterances = set()

    fieldnames = [
        "student_utterance",
        "concept_id",
        "miniLM_labels",
        "hope_signals",
        "target_policy_action",
        "category",
    ]

    def save_progress():
        # Write JSON
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(all_samples, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving JSON progress: {e}")
        # Write CSV
        try:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for s in all_samples:
                    writer.writerow({k: s.get(k, "") for k in fieldnames})
        except Exception as e:
            print(f"Error saving CSV progress: {e}")

    for i, cat in enumerate(CATEGORIES):
        target = samples_per_category + (1 if i < remainder else 0)
        
        # Calculate how many samples are already collected for this category
        collected = sum(1 for s in all_samples if s.get("category") == cat["id"])
        
        if collected >= target:
            print(f"── Category {cat['id']}: {cat['name']} (target: {target}) ── Already completed ({collected}/{target})")
            continue

        print(f"── Category {cat['id']}: {cat['name']} (target: {target}, remaining: {target - collected}) ──")
        retries = 0
        max_retries = 5

        while collected < target and retries < max_retries:
            batch_needed = min(BATCH_SIZE, target - collected)
            print(f"  Requesting batch of {batch_needed}...", end=" ", flush=True)

            try:
                samples = generate_batch(
                    client, system_prompt, cat, batch_needed, existing_utterances
                )
            except Exception as e:
                print(f"API ERROR: {e}")
                retries += 1
                time.sleep(5)
                continue

            valid_in_batch = 0
            for s in samples:
                is_valid, reason = validate_sample(s, valid_ids)
                if is_valid:
                    utt = s["student_utterance"].strip().lower()
                    if utt not in existing_utterances:
                        existing_utterances.add(utt)
                        all_samples.append(s)
                        collected += 1
                        valid_in_batch += 1
                    else:
                        invalid_count += 1
                else:
                    invalid_count += 1

            print(f"got {len(samples)}, valid: {valid_in_batch}, total: {collected}/{target}")

            if valid_in_batch == 0:
                retries += 1
                time.sleep(2)
            else:
                retries = 0  # reset on success
                # Save progress after every successful batch
                save_progress()

            # Rate limiting
            time.sleep(1)

        print(f"  ✓ Collected {collected} samples for category {cat['id']}\n")

    # Final write to confirm all is saved
    save_progress()

    # Print stats
    print(f"\n{'═' * 50}")
    print(f"  GENERATION COMPLETE")
    print(f"  Total valid samples: {len(all_samples)}")
    print(f"  Rejected samples: {invalid_count}")
    print(f"  CSV: {output_path}")
    print(f"  JSON: {json_path}")

    # Category distribution
    cat_dist = {}
    for s in all_samples:
        c = s.get("category", "?")
        cat_dist[c] = cat_dist.get(c, 0) + 1
    print(f"\n  Category distribution:")
    for c in sorted(cat_dist.keys()):
        print(f"    Cat {c}: {cat_dist[c]} samples")

    # Concept distribution
    inherit_count = sum(1 for s in all_samples if s["concept_id"] == "INHERIT_CURRENT_CONCEPT")
    specific_count = len(all_samples) - inherit_count
    print(f"\n  INHERIT_CURRENT_CONCEPT: {inherit_count} ({inherit_count*100//max(len(all_samples),1)}%)")
    print(f"  Specific concept_ids: {specific_count} ({specific_count*100//max(len(all_samples),1)}%)")

    # Chapter coverage
    chapters = set()
    for s in all_samples:
        cid = s["concept_id"]
        if cid != "INHERIT_CURRENT_CONCEPT" and "__" in cid:
            chapters.add(cid.split("__")[0])
    print(f"  Chapters covered: {sorted(chapters)}")
    print(f"{'═' * 50}")


if __name__ == "__main__":
    main()
