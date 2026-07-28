"""llm_representative_audit.py
──────────────────────────────────────
Orchestrates an LLM semantic audit on 300 samples (first 100 from Categories 1, 2, and 3).
Performs zero rule-based/regex evaluation locally. The logic is entirely handled by the LLM.

Usage:
  python dataset/llm_representative_audit.py
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load paths relative to project root
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Set up UTF-8 console output for Windows
import codecs
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

# Gemini configuration
GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash")
ARTIFACT_DIR = Path("C:/Users/LENOVO/.gemini/antigravity/brain/d6bb5526-12af-46f5-9f08-1da962472141")

# LLM Audit Prompt Template
AUDIT_SYSTEM_PROMPT = """You are a strict QA semantic judge evaluating the labels of a student math utterance dataset.

Given a student math utterance and its assigned annotations, verify if the labels and action are semantically correct, and check for any logical contradictions.

### Rules for Labels:
- `question`: Must be present if and only if the utterance is semantically a question (inquiring about how to do something, requesting explanation, asking about concepts, etc.).
- `curiosity`: Represents interest in understanding the 'why', derivations, utility, or testing edge cases. Must NOT be mixed with `confusion` unless they explicitly state they are confused.
- `confusion`: Represents lack of understanding of the current material. Do NOT confuse with curiosity.
- `representation_shift`/`request_representation`: Student asks to translate formulas/words into visual/diagrammatic representation (e.g., charts, drawings, moving visuals).
- `example_request`: Explicitly asking for a sum, problem, or numbers.
- `low_confidence`/`anxiety`: Expressing personal doubt, exam fear, or struggle.

### Rules for Policy Actions:
- If `example_request` is active, the action must be `WORKED_EXAMPLE` or `ANALOGOUS_EXAMPLE` (NOT `REPRESENTATION_TRANSLATION` or `EXPLAIN`).
- If `curiosity` is active without confusion, the action should NOT be `MISCONCEPTION_PROBE` unless the student actively asserts a wrong mathematical belief.
- Asking for alternative explanations must NOT trigger `MISCONCEPTION_PROBE`.
- Help-seeking questions on how to write steps or do homework must NOT trigger `QUIZ`.

### Output Format:
Return a JSON object with these exact keys:
- "is_valid": true/false (false if there is a mismatch or contradiction)
- "mismatches": A list of strings describing any incorrect labels, missing labels, or wrong signals. Empty list if none.
- "contradictions": A list of strings describing any logical contradictions (e.g. policy action contradicts request, opposing hope signals). Empty list if none.
- "explanation": A brief, one-sentence description of the issue.

Return ONLY the raw JSON object. Do not include markdown formatting or fences."""

def audit_sample(client: genai.Client, row: dict, row_idx: int) -> dict:
    """Send a single sample to Gemini for semantic validation."""
    prompt = f"""Utterance: "{row['student_utterance']}"
Concept ID: {row['concept_id']}
Assigned miniLM_labels: {row['miniLM_labels']}
Assigned hope_signals: {row['hope_signals']}
Assigned target_policy_action: {row['target_policy_action']}
Category: {row['category']}"""

    try:
        resp = client.models.generate_content(
            model=GEN_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=AUDIT_SYSTEM_PROMPT,
                temperature=0.0,  # Strict evaluation
            )
        )
        text = (resp.text or "").strip()
        # Clean markdown fences if any
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        
        result = json.loads(text)
        result["row_data"] = row
        result["row_index"] = row_idx
        return result
    except Exception as e:
        return {
            "is_valid": True,  # Fail open on network errors but log the error
            "mismatches": [],
            "contradictions": [],
            "explanation": f"API Error: {str(e)}",
            "row_data": row,
            "row_index": row_idx,
            "error": True
        }

def main():
    input_path = ROOT / "dataset" / "exemplar_dataset_10000_fixed.json"
    output_path = ARTIFACT_DIR / "audit_300_report.md"

    if not input_path.exists():
        print(f"Error: {input_path} not found.")
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    
    # Filter first 100 of categories 1, 2, and 3
    cat1 = [r for r in data if r["category"] == 1][:100]
    cat2 = [r for r in data if r["category"] == 2][:100]
    cat3 = [r for r in data if r["category"] == 3][:100]
    
    audit_data = cat1 + cat2 + cat3
    
    print(f"==================================================")
    print(f"  RUNNING SEMANTIC AUDIT FOR 300 REPRESENTATIVE ROWS")
    print(f"==================================================")
    print(f"Category 1: {len(cat1)} rows")
    print(f"Category 2: {len(cat2)} rows")
    print(f"Category 3: {len(cat3)} rows")
    print(f"==================================================")

    client = genai.Client()
    violations = []
    processed = 0
    errors = 0

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(audit_sample, client, row, i): i for i, row in enumerate(audit_data, 1)}
        
        for fut in as_completed(futures):
            row_idx = futures[fut]
            res = fut.result()
            processed += 1
            
            if res.get("error"):
                errors += 1
            elif not res.get("is_valid"):
                violations.append(res)
                print(f"Row {row_idx:3d} (Cat {res['row_data']['category']}) | Mismatches: {len(res['mismatches'])} | Contradictions: {len(res['contradictions'])} | {res['explanation']}")
            
            if processed % 30 == 0:
                print(f"  Progress: {processed}/300 rows processed... ({len(violations)} violations)")

    elapsed = time.time() - start_time
    
    # Group violations by category
    by_cat = {1: [], 2: [], 3: []}
    for v in violations:
        by_cat[v["row_data"]["category"]].append(v)

    # Generate markdown report
    md = []
    md.append("# Semantic Audit Report (300 Representative Samples)")
    md.append("")
    md.append("This report details the semantic validation of the first 3 categories (100 samples each) in `exemplar_dataset_10000_fixed.json`.")
    md.append("")
    md.append("## Summary Statistics")
    md.append("")
    md.append(f"- **Total Rows Checked**: 300")
    md.append(f"- **Total Semantic Violations**: {len(violations)}")
    md.append(f"- **Violation Rate**: {len(violations)*100/300:.1f}%")
    md.append(f"- **Errors/Timeouts**: {errors}")
    md.append(f"- **Time Elapsed**: {elapsed:.1f} seconds")
    md.append("")
    md.append("### Violation Rate by Category")
    md.append("")
    md.append("| Category | Checked | Violations | Violation Rate | Description |")
    md.append("|---|---|---|---|---|")
    md.append(f"| Cat 1 | 100 | {len(by_cat[1])} | {len(by_cat[1])}% | Representation & Sensemaking Requests |")
    md.append(f"| Cat 2 | 100 | {len(by_cat[2])} | {len(by_cat[2])}% | Context, Analogy & Transfer Requests |")
    md.append(f"| Cat 3 | 100 | {len(by_cat[3])} | {len(by_cat[3])}% | Motivation, Resistance & System Gaming |")
    md.append("")
    
    for cat_id in [1, 2, 3]:
        cat_name = {1: "Representation & Sensemaking", 2: "Context, Analogy & Transfer", 3: "Motivation, Resistance & System Gaming"}[cat_id]
        md.append(f"## Category {cat_id} Details: {cat_name}")
        md.append("")
        if not by_cat[cat_id]:
            md.append("✓ No semantic mismatches or contradictions identified in this category.")
            md.append("")
            continue
            
        md.append(f"Identified {len(by_cat[cat_id])} semantic violations:")
        md.append("")
        md.append("| Index | Student Utterance | Assigned Labels | Assigned Action | Issues | Explanation |")
        md.append("|---|---|---|---|---|---|")
        for v in sorted(by_cat[cat_id], key=lambda x: x["row_index"]):
            row = v["row_data"]
            mismatches = "<br>".join(v["mismatches"]) if v["mismatches"] else "None"
            contras = "<br>".join(v["contradictions"]) if v["contradictions"] else "None"
            issues = []
            if mismatches != "None":
                issues.append(f"**Mismatches**:<br>{mismatches}")
            if contras != "None":
                issues.append(f"**Contradictions**:<br>{contras}")
            issues_str = "<br>".join(issues)
            
            md.append(f"| {v['row_index']} | *\"{row['student_utterance']}\"* | {row['miniLM_labels']} | {row['target_policy_action']} | {issues_str} | {v['explanation']} |")
        md.append("")

    output_path.write_text("\n".join(md), encoding="utf-8")
    
    print(f"\n==================================================")
    print(f"  AUDIT COMPLETE. Report saved to {output_path.name}")
    print(f"==================================================")

if __name__ == "__main__":
    main()
