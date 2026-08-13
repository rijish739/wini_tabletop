"""Off-learner-path candidate generation helpers."""
from __future__ import annotations

import json
import re
from typing import Callable

from .contracts import CandidateItem


def generate_candidate(schema: dict, concept_id: str, concept_name: str,
                       generator: Callable[..., str], *, assessment_purpose: str,
                       avoid: list[str] | None = None,
                       generator_model: str | None = None) -> CandidateItem | None:
    """Generate an untrusted candidate at temperature 0. Verification is separate."""
    method = "; ".join((schema.get("method_steps") or [])[:6])
    variables = ", ".join((schema.get("isomorphic_variables") or [])[:4])
    avoid_text = "\n".join(f"- {q}" for q in (avoid or []) if q)
    prompt = (
        "Create ONE non-binary, one- or two-step Class 10 maths short-answer item.\n"
        f"CONCEPT: {concept_name}\nMETHOD: {method}\nVARIABLES: {variables}\n"
        + (f"DO NOT REPEAT:\n{avoid_text}\n" if avoid_text else "")
        + "Use plain spoken text, one exact answer, and no LaTeX. "
          'Return only JSON: {"question":"...","expected_answer":"...",'
          '"response_type":"short_exact"}.')
    raw = generator(prompt, temperature=0.0, max_tokens=220)
    match = re.search(r"\{.*\}", raw or "", re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return CandidateItem(
        concept_id=concept_id, kc_id=concept_id,
        question=str(data.get("question") or ""),
        expected_answer=str(data.get("expected_answer") or ""),
        response_type=str(data.get("response_type") or "short_exact"),
        assessment_purpose=assessment_purpose, reveal_policy="after_attempt",
        generator_model=generator_model, generator_version="candidate-v1",
        schema_id=schema.get("id") or schema.get("schema_id"),
    )
