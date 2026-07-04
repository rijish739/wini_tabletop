"""llm_fixed_audit_orchestrator.py
───────────────────────────────────
Orchestrator to run Gemini LLM semantic validation on the entire 10,000 fixed utterances.
Performs zero rule-based/regex evaluation locally. The logic is entirely handled by the LLM.

Usage:
  python dataset/llm_fixed_audit_orchestrator.py --limit 100   # test run
  python dataset/llm_fixed_audit_orchestrator.py               # full 10k run
"""

from __future__ import annotations
import argparse
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

# LLM Audit Prompt Template
AUDIT_SYSTEM_PROMPT = """You are a strict QA semantic judge evaluating the labels of a student math utterance dataset.

Given a student utterance and its assigned annotations, verify if the labels and action are semantically correct, and check for any logical contradictions.

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

def audit_sample(client: genai.Client, row: dict) -> dict:
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
        return result
    except Exception as e:
        return {
            "is_valid": True,  # Fail open on network errors but log the error
            "mismatches": [],
            "contradictions": [],
            "explanation": f"API Error: {str(e)}",
            "row_data": row,
            "error": True
        }

def main():
    parser = argparse.ArgumentParser(description="Run LLM semantic audit on fixed dataset")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows to check")
    parser.add_argument("--threads", type=int, default=10, help="Number of concurrent API worker threads")
    args = parser.parse_args()

    input_path = ROOT / "dataset" / "exemplar_dataset_10000_fixed.json"
    output_path = ROOT / "dataset" / "llm_fixed_audit_report.json"

    if not input_path.exists():
        print(f"Error: {input_path} not found.")
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if args.limit:
        data = data[:args.limit]

    print(f"==================================================")
    print(f"  LLM SEMANTIC AUDIT FOR FIXED DATASET")
    print(f"==================================================")
    print(f"File: {input_path.name}")
    print(f"Rows to check: {len(data)}")
    print(f"Workers: {args.threads} threads")
    print(f"Target: {output_path.name}")
    print(f"==================================================")

    client = genai.Client()
    violations = []
    processed = 0
    errors = 0

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        futures = {executor.submit(audit_sample, client, row): i for i, row in enumerate(data, 1)}
        
        for fut in as_completed(futures):
            row_idx = futures[fut]
            res = fut.result()
            processed += 1
            
            if res.get("error"):
                errors += 1
            elif not res.get("is_valid"):
                res["row_index"] = row_idx
                violations.append(res)
                print(f"Row {row_idx:5d} | Mismatches: {len(res['mismatches'])} | Contradictions: {len(res['contradictions'])} | {res['explanation']}")
            
            if processed % 50 == 0:
                print(f"  Progress: {processed}/{len(data)} rows processed... ({len(violations)} violations, {errors} errors)")

    elapsed = time.time() - start_time
    
    # Save results
    report = {
        "summary": {
            "total_rows_checked": len(data),
            "total_violations": len(violations),
            "errors": errors,
            "elapsed_seconds": round(elapsed, 2),
            "violation_rate": f"{len(violations)*100/max(len(data),1):.1f}%"
        },
        "violations": violations
    }
    
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\n==================================================")
    print(f"  AUDIT COMPLETE")
    print(f"==================================================")
    print(f"Checked: {len(data)}")
    print(f"Violations identified: {len(violations)} ({report['summary']['violation_rate']})")
    print(f"Errors encountered: {errors}")
    print(f"Report saved to: {output_path}")
    print(f"Time taken: {elapsed:.1f}s (avg {elapsed/len(data):.2f}s per row)")
    print(f"==================================================")

if __name__ == "__main__":
    main()
